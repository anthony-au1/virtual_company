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
        self.span_errors: list[str] = []
        self.updates: list[object] = []

    def event(self, name: str, **_: object) -> None:
        self.events.append(name)

    @contextmanager
    def span(self, *_: object, **__: object):
        class Observation:
            def __init__(self, updates: list[object]) -> None:
                self._updates = updates

            def update(self, **data: object) -> None:
                self._updates.append(data)

        try:
            yield Observation(self.updates)
        except Exception as error:
            self.span_errors.append(str(error))
            raise

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


@pytest.mark.asyncio
async def test_safe_instrumentation_disables_io_capture_and_sanitizes_span_errors() -> None:
    observability = ObservabilityFake()
    observability.capture_io = True
    secret = "raw provider detail and page contents"
    provider = InstrumentedLLMProvider(
        ProviderFake(RuntimeError(secret)),  # type: ignore[arg-type]
        observability=observability,  # type: ignore[arg-type]
        capture_io=False,
        sanitize_errors=True,
    )

    with pytest.raises(RuntimeError, match=secret):
        await provider.generate_structured(
            system_prompt="private system",
            user_prompt="private page content",
            response_model=Output,
        )

    assert observability.updates == []
    assert observability.span_errors == []
    assert all(secret not in str(event) for event in observability.events)
