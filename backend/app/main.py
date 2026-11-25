import asyncio
import logging
import time
import weakref
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictStr, field_validator

from .config import Settings, load_settings
from .db import Database, now_iso
from .gateway import AllProvidersFailed, Gateway, parse_simulation

log = logging.getLogger("app")


def _valid_text(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("must be valid UTF-8 text") from None
    return value


class ChatRequest(BaseModel):
    session_id: StrictStr = Field(min_length=1, max_length=128)
    message: StrictStr
    system_prompt: StrictStr | None = Field(default=None, max_length=4000)

    @field_validator("session_id")
    @classmethod
    def check_session_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return _valid_text(value)

    @field_validator("message")
    @classmethod
    def check_message(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 4000:
            raise ValueError("must be 1-4000 characters after trimming whitespace")
        return _valid_text(value)

    @field_validator("system_prompt")
    @classmethod
    def check_system_prompt(cls, value: str | None) -> str | None:
        return _valid_text(value.strip()) or None if value is not None else None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.database_url)
    gateway = Gateway(settings)
    locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.init()
        if gateway.key_count < 2:
            log.warning("LLM_API_KEYS should contain at least 2 keys, found %d", gateway.key_count)
        yield

    app = FastAPI(title="LLM Chatbot with Key Failover and Caching", lifespan=lifespan)
    app.state.gateway = gateway

    @app.middleware("http")
    async def json_errors(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as error:
            log.error("unhandled %s on %s", type(error).__name__, request.url.path)
            return JSONResponse({"detail": "internal server error"}, status_code=500)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Simulate-Failure"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError):
        detail = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in error.errors()]
        return JSONResponse({"detail": detail}, status_code=422)

    @app.get("/health")
    def health():
        try:
            db.ping()
        except Exception:
            return JSONResponse({"detail": "database unreachable"}, status_code=503)
        if gateway.key_count == 0:
            return JSONResponse({"detail": "no API keys configured"}, status_code=503)
        return {"status": "ok", "keys_configured": gateway.key_count, "cache_enabled": True}

    @app.post("/chat")
    async def chat(body: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
        started = time.perf_counter()
        simulated = parse_simulation(x_simulate_failure) if settings.simulation_enabled else {}
        lock = locks.setdefault(body.session_id, asyncio.Lock())

        async with lock:
            asked_at = now_iso()
            history = await asyncio.to_thread(db.history, body.session_id)
            system_prompt = (
                body.system_prompt
                or await asyncio.to_thread(db.system_prompt, body.session_id)
                or settings.default_system_prompt
            )
            messages = [{"role": "system", "content": system_prompt}]
            messages += [{"role": m["role"], "content": m["content"]} for m in history]
            messages.append({"role": "user", "content": body.message})

            try:
                result = await gateway.complete(messages, simulated)
            except AllProvidersFailed:
                return JSONResponse({"detail": "all providers unavailable"}, status_code=503)

            metadata = {
                "resolution_source": result.resolution_source,
                "model": result.model,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "key_id": result.key_id,
                "fallback_attempts": result.fallback_attempts,
            }
            await asyncio.to_thread(
                db.save_turn,
                body.session_id,
                body.message,
                asked_at,
                result.reply,
                metadata,
                body.system_prompt,
            )

        return {"session_id": body.session_id, "reply": result.reply, "metadata": metadata}

    @app.get("/sessions/{session_id:path}/messages")
    def session_messages(session_id: str):
        messages = db.history(session_id)
        if not messages:
            return JSONResponse({"detail": "session not found"}, status_code=404)
        return {"session_id": session_id, "messages": messages}

    return app


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
app = create_app()
