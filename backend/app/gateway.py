import logging
from dataclasses import dataclass

import litellm
from litellm import Router
from litellm.caching.caching import Cache

from .config import Settings

log = logging.getLogger("gateway")


class AllProvidersFailed(Exception):
    pass


@dataclass
class Completion:
    reply: str
    model: str
    input_tokens: int
    output_tokens: int
    resolution_source: str
    key_id: str | None
    fallback_attempts: int


_SIMULATED_ERRORS = {
    429: litellm.RateLimitError,
    500: litellm.InternalServerError,
    502: litellm.BadGatewayError,
    503: litellm.ServiceUnavailableError,
}


def parse_simulation(header: str | None) -> dict[str, int]:
    failures: dict[str, int] = {}
    for pair in (header or "").split(","):
        key_id, _, status = pair.partition("=")
        status = status.strip()
        if key_id.strip() and status.isdecimal() and int(status) in _SIMULATED_ERRORS:
            failures[key_id.strip()] = int(status)
    return failures


def _simulated_error(status: int, model: str) -> Exception:
    return _SIMULATED_ERRORS[status](
        message=f"simulated HTTP {status}",
        llm_provider=model.split("/")[0],
        model=model,
    )


class Gateway:
    def __init__(self, settings: Settings):
        self.deployments = [
            (f"key_{i + 1}", settings.models[i % len(settings.models)])
            for i in range(len(settings.api_keys))
        ]
        model_list = [
            {"model_name": key_id, "litellm_params": {"model": model, "api_key": api_key}}
            for (key_id, model), api_key in zip(self.deployments, settings.api_keys)
        ]
        self.router = (
            Router(
                model_list=model_list,
                num_retries=0,
                disable_cooldowns=True,
                timeout=settings.timeout_seconds,
                default_litellm_params={"max_retries": 0},
            )
            if model_list
            else None
        )
        cache_options = {"type": settings.cache_type, "ttl": settings.cache_ttl_seconds}
        if settings.cache_type == "disk":
            cache_options["disk_cache_dir"] = settings.cache_dir
        self.cache = Cache(**cache_options)

    @property
    def key_count(self) -> int:
        return len(self.deployments)

    def _cache_key(self, model: str, messages: list[dict]) -> str:
        return self.cache.get_cache_key(model=model, messages=messages)

    async def _cached(self, messages: list[dict]) -> Completion | None:
        for model in dict.fromkeys(model for _, model in self.deployments):
            hit = await self.cache.async_get_cache(cache_key=self._cache_key(model, messages))
            if hit:
                return Completion(**hit, resolution_source="LLM_CACHE", key_id=None, fallback_attempts=0)
        return None

    async def complete(self, messages: list[dict], simulated: dict[str, int]) -> Completion:
        if not simulated:
            cached = await self._cached(messages)
            if cached:
                return cached

        for attempts, (key_id, model) in enumerate(self.deployments):
            try:
                status = simulated.get(key_id, simulated.get("*"))
                extra = {}
                if status:
                    extra["mock_response"] = _simulated_error(status, model)
                response = await self.router.acompletion(model=key_id, messages=messages, **extra)
                reply = (response.choices[0].message.content or "").strip()
                if not reply:
                    raise ValueError("provider returned an empty reply")
                stored = {
                    "reply": reply,
                    "model": model,
                    "input_tokens": int(response.usage.prompt_tokens),
                    "output_tokens": int(response.usage.completion_tokens),
                }
            except Exception as error:
                log.warning(
                    "%s failed: %s (status %s)",
                    key_id,
                    type(error).__name__,
                    getattr(error, "status_code", "n/a"),
                )
                continue
            if not simulated:
                await self.cache.async_add_cache(stored, cache_key=self._cache_key(model, messages))
            return Completion(
                **stored, resolution_source="LIVE_INFERENCE", key_id=key_id, fallback_attempts=attempts
            )

        raise AllProvidersFailed()
