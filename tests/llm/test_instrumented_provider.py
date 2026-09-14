"""Tests for provider-neutral LLM observability."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from pydantic import BaseModel

from virtual_company.llm.instrumented import InstrumentedLLMProvider


class Output(BaseModel):
    """Minimal structured response."""

    value: str


class ProviderFake:
    provider = "openai"
    model = "gpt-5.6-terra"
    role = "research"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def generate_structured(self, **_: object) -> Output:
        if self.error is not None:
            raise self.error
        return Output(value="ok")


class ObservabilityFake:
    capture_io = False

    def __init__(self) -> None:
        self.events: list[str] = []
        self.metrics: list[tuple[str, dict[str, str]]] = []

    def event(self, name: str, **_: object) -> None:
        self.events.append(name)

    @contextmanager
    def span(self, *_: object, **__: object):
        yield object()

    def record(self, name: str, _value: float = 1, **attributes: str) -> None:
        self.metrics.append((name, attributes))


@pytest.mark.asyncio
async def test_instrumented_provider_preserves_result_and_records_metadata() -> None:
    observability = ObservabilityFake()
    provider = InstrumentedLLMProvider(ProviderFake(), observability=observability)  # type: ignore[arg-type]

    result = await provider.generate_structured(
        system_prompt="System", user_prompt="User", response_model=Output
    )

    assert result == Output(value="ok")
    assert observability.events == ["llm_request_started", "llm_request_completed"]
    assert ("llm_requests_total", {"status": "completed", "provider": "openai", "model": "gpt-5.6-terra", "role": "research"}) in observability.metrics


@pytest.mark.asyncio
async def test_instrumented_provider_preserves_original_error() -> None:
    observability = ObservabilityFake()
    provider = InstrumentedLLMProvider(
        ProviderFake(RuntimeError("unavailable")), observability=observability  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="unavailable"):
        await provider.generate_structured(
            system_prompt="System", user_prompt="User", response_model=Output
        )

    assert "llm_request_failed" in observability.events
    assert any(name == "llm_request_failures_total" for name, _ in observability.metrics)
