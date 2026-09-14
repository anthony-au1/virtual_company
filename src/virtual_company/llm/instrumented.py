"""Provider-neutral LLM observability decorator."""

from __future__ import annotations

import time
from typing import Any

from virtual_company.llm.base import LLMProvider, T
from virtual_company.observability import Observability, get_observability


class InstrumentedLLMProvider:
    """Record LLM request metadata while preserving the LLMProvider contract."""

    def __init__(self, provider: LLMProvider, observability: Observability | None = None) -> None:
        self._provider = provider
        self._observability = observability or get_observability()

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        """Generate structured output and record metadata, latency, and errors."""
        metadata = self._metadata()
        self._observability.event("llm_request_started", **metadata)
        started = time.perf_counter()
        with self._observability.span("llm.generate_structured", as_type="generation", **metadata) as observation:
            try:
                if hasattr(observation, "update") and self._observability.capture_io:
                    observation.update(input={"system": system_prompt, "user": user_prompt})
                result = await self._provider.generate_structured(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_model=response_model,
                )
            except Exception as error:
                duration = time.perf_counter() - started
                self._observability.record("llm_requests_total", status="failed", **metadata)
                self._observability.record("llm_request_failures_total", **metadata)
                self._observability.record("llm_request_duration_seconds", duration, status="failed", **metadata)
                self._observability.event("llm_request_failed", duration_ms=int(duration * 1000), error_type=type(error).__name__, **metadata)
                raise
            if hasattr(observation, "update") and self._observability.capture_io:
                observation.update(output=result.model_dump())
        duration = time.perf_counter() - started
        self._observability.record("llm_requests_total", status="completed", **metadata)
        self._observability.record("llm_request_duration_seconds", duration, status="completed", **metadata)
        self._observability.event("llm_request_completed", duration_ms=int(duration * 1000), **metadata)
        return result

    def _metadata(self) -> dict[str, str]:
        provider: Any = self._provider
        return {
            "provider": str(getattr(provider, "provider", "unknown")),
            "model": str(getattr(provider, "model", "unknown")),
            "role": str(getattr(provider, "role", "unknown")),
        }
