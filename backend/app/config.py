import os
from dataclasses import dataclass

DEFAULT_PROMPT = "You are a helpful assistant. Answer clearly and concisely."


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    api_keys: list[str]
    models: list[str]
    database_url: str
    allowed_origins: list[str]
    simulation_enabled: bool
    default_system_prompt: str
    timeout_seconds: float
    cache_type: str
    cache_dir: str
    cache_ttl_seconds: int


def load_settings() -> Settings:
    env = os.environ.get
    return Settings(
        api_keys=_split(env("LLM_API_KEYS", "")),
        models=_split(env("LLM_MODEL", "")) or ["gemini/gemini-3.5-flash-lite"],
        database_url=env("DATABASE_URL", "sqlite:///./app.db"),
        allowed_origins=[o.rstrip("/") for o in _split(env("ALLOWED_ORIGINS", "http://localhost:3000"))],
        simulation_enabled=env("ENABLE_FAILURE_SIMULATION", "false").strip().lower() == "true",
        default_system_prompt=env("DEFAULT_SYSTEM_PROMPT", "").strip() or DEFAULT_PROMPT,
        timeout_seconds=float(env("LLM_TIMEOUT_SECONDS", "20")),
        cache_type=env("CACHE_TYPE", "local").strip().lower(),
        cache_dir=env("CACHE_DIR", "./.llm_cache"),
        cache_ttl_seconds=int(env("CACHE_TTL_SECONDS", "3600")),
    )
