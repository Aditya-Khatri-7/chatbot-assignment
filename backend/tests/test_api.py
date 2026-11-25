import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        api_keys=["fake-key-one", "fake-key-two"],
        models=["gemini/gemini-2.5-flash"],
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        allowed_origins=["http://localhost:3000"],
        simulation_enabled=True,
        default_system_prompt="default prompt",
        timeout_seconds=5,
        cache_type="local",
        cache_dir=str(tmp_path / "cache"),
        cache_ttl_seconds=60,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def provider(monkeypatch):
    real = litellm.acompletion
    calls = []

    async def fake(*args, **kwargs):
        if kwargs.get("mock_response") is None:
            calls.append(kwargs["messages"])
            words = sum(len(m["content"].split()) for m in kwargs["messages"])
            kwargs["mock_response"] = f"reply number {len(calls)} ({words} words)"
        return await real(*args, **kwargs)

    monkeypatch.setattr(litellm, "acompletion", fake)
    return calls


@pytest.fixture
def client(tmp_path, provider):
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        yield test_client


def chat(client, session="s-1", message="What is the capital of France?", header=None, **extra):
    headers = {"X-Simulate-Failure": header} if header else {}
    return client.post("/chat", json={"session_id": session, "message": message, **extra}, headers=headers)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_chat_contract(client):
    body = chat(client).json()
    assert body["session_id"] == "s-1" and body["reply"]
    meta = body["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-2.5-flash"
    assert meta["key_id"] == "key_1" and meta["fallback_attempts"] == 0
    for field in ("latency_ms", "input_tokens", "output_tokens"):
        assert isinstance(meta[field], int)


def test_same_first_message_in_new_session_is_cached(client, provider):
    first = chat(client, "a").json()
    second = chat(client, "b").json()
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"]
    assert second["metadata"]["key_id"] is None
    assert second["metadata"]["fallback_attempts"] == 0
    for field in ("model", "input_tokens", "output_tokens"):
        assert second["metadata"][field] == first["metadata"][field]
    assert len(provider) == 1


def test_different_message_or_prompt_is_not_cached(client):
    chat(client, "a")
    other = chat(client, "b", "What is the capital of Spain?").json()
    prompted = chat(client, "c", system_prompt="Answer in French").json()
    assert other["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert prompted["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_multi_turn_history_and_session_isolation(client, provider):
    chat(client, "a", "My name is Sam")
    chat(client, "a", "What is my name?")
    assert [m["content"] for m in provider[-1] if m["role"] == "user"] == ["My name is Sam", "What is my name?"]
    chat(client, "b", "Hello")
    assert [m["role"] for m in provider[-1]] == ["system", "user"]

    history = client.get("/sessions/a/messages").json()
    assert history["session_id"] == "a"
    assert [m["role"] for m in history["messages"]] == ["user", "assistant", "user", "assistant"]
    assert "metadata" not in history["messages"][0]
    assert history["messages"][1]["metadata"]["input_tokens"] > 0


def test_system_prompt_persists_for_session(client, provider):
    chat(client, "a", "one", system_prompt="Be brief")
    chat(client, "a", "two")
    assert provider[-1][0] == {"role": "system", "content": "Be brief"}


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_failover_to_second_key(client, status):
    response = chat(client, header=f"key_1={status}")
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_2"
    assert response.json()["metadata"]["fallback_attempts"] == 1


@pytest.mark.parametrize("header", ["*=429", "key_1=429,key_2=500"])
def test_all_keys_failing_returns_503_and_saves_nothing(client, header):
    response = chat(client, header=header)
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s-1/messages").status_code == 404


def test_simulation_is_not_hidden_by_cache_and_is_one_request_only(client):
    chat(client, "a")
    assert chat(client, "b", header="*=429").status_code == 503
    assert chat(client, "c", header="key_1=429").json()["metadata"]["key_id"] == "key_2"
    assert chat(client, "d").json()["metadata"]["resolution_source"] == "LLM_CACHE"
    assert chat(client, "e", "new question").json()["metadata"]["key_id"] == "key_1"


def test_real_provider_error_fails_over(client, monkeypatch):
    real = litellm.acompletion

    async def first_key_broken(*args, **kwargs):
        if kwargs["api_key"] == "fake-key-one":
            raise litellm.RateLimitError("quota exceeded", "gemini", kwargs["model"])
        return await real(*args, **kwargs)

    monkeypatch.setattr(litellm, "acompletion", first_key_broken)
    assert chat(client).json()["metadata"]["key_id"] == "key_2"


def test_simulation_ignored_when_disabled(tmp_path, provider):
    with TestClient(create_app(make_settings(tmp_path, simulation_enabled=False))) as c:
        assert chat(c, header="*=429").status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"session_id": "a"},
        {"message": "hi"},
        {"session_id": "", "message": "hi"},
        {"session_id": "x" * 129, "message": "hi"},
        {"session_id": "a", "message": "   "},
        {"session_id": "a", "message": "x" * 4001},
        {"session_id": "a", "message": 5},
    ],
)
def test_validation_errors(client, payload):
    response = client.post("/chat", json=payload)
    assert response.status_code == 422 and "detail" in response.json()


@pytest.mark.parametrize("raw", [b"{not json", b'{"session_id":"a","message":"\\ud800"}'])
def test_bad_body_is_422(client, raw):
    response = client.post("/chat", content=raw, headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and "detail" in response.json()


def test_message_limit_applies_after_trimming(client):
    assert chat(client, message="  " + "x" * 4000 + "  ").status_code == 200


def test_unknown_session(client):
    response = client.get("/sessions/nope/messages")
    assert response.status_code == 404 and response.json() == {"detail": "session not found"}


def test_history_survives_restart(tmp_path, provider):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as c:
        chat(c)
    with TestClient(create_app(settings)) as c:
        assert len(c.get("/sessions/s-1/messages").json()["messages"]) == 2


def test_cors_allows_frontend_origin(client):
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
