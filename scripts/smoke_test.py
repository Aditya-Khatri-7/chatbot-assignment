import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
failures = []


def call(path, body=None, simulate=None):
    headers = {"Content-Type": "application/json"}
    if simulate:
        headers["X-Simulate-Failure"] = simulate
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def check(name, passed, seen):
    print(("PASS " if passed else "FAIL ") + name)
    if not passed:
        print("     got:", json.dumps(seen)[:400])
        failures.append(name)


def chat(session, message, simulate=None):
    return call("/chat", {"session_id": session, "message": message}, simulate)


run = uuid.uuid4().hex[:8]
question = f"Reply with one short sentence about the number {int(time.time())}."

status, body = call("/health")
check("health", status == 200 and body.get("keys_configured", 0) >= 2, body)

status, live = chat(f"a-{run}", question)
meta = live.get("metadata", {})
check("live call", status == 200 and meta.get("resolution_source") == "LIVE_INFERENCE", live)

status, hit = chat(f"b-{run}", question)
hit_meta = hit.get("metadata", {})
check(
    "cache hit",
    hit_meta.get("resolution_source") == "LLM_CACHE"
    and hit.get("reply") == live.get("reply")
    and hit_meta.get("key_id") is None
    and hit_meta.get("latency_ms", 10**9) < meta.get("latency_ms", 0),
    hit,
)

for simulate in ("key_1=429", "key_1=500"):
    status, body = chat(f"c-{run}-{simulate[-3:]}", question, simulate)
    check(f"failover {simulate}", status == 200 and body["metadata"]["key_id"] == "key_2", body)

status, body = chat(f"k2-{run}", f"Say hello. {run}", "key_1=503")
check("second key answers", status == 200 and body["metadata"]["key_id"] == "key_2", body)

status, body = chat(f"d-{run}", question, "*=429")
check("all keys fail gives 503", status == 503 and body == {"detail": "all providers unavailable"}, body)
status, body = call(f"/sessions/d-{run}/messages")
check("failed request not saved / 404", status == 404, body)

session = f"m-{run}"
chat(session, "My favourite word is 'pineapple'. Please remember it.")
status, body = chat(session, "What is my favourite word?")
check("multi-turn memory", "pineapple" in body.get("reply", "").lower(), body)
status, body = call(f"/sessions/{session}/messages")
check("history", status == 200 and [m["role"] for m in body["messages"]] == ["user", "assistant"] * 2, body)

status, body = chat(session, "   ")
check("422 validation", status == 422 and "detail" in body, body)

print(f"\n{len(failures)} failed")
sys.exit(1 if failures else 0)
