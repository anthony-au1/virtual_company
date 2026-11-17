"""Tests for provider-neutral LLM observability."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from pydantic import BaseModel

from virtual_company.llm import usage as usage_module
from virtual_company.llm.instrumented import InstrumentedLLMProvider
from virtual_company.observability.runtime import Observability


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
        self.event_data: list[tuple[str, dict[str, object]]] = []
        self.metrics: list[tuple[str, dict[str, str]]] = []
        self.span_errors: list[str] = []
        self.updates: list[object] = []

    def event(self, name: str, **data: object) -> None:
        self.events.append(name)
        self.event_data.append((name, data))

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
async def test_instrumented_provider_reports_qualification_role_and_model() -> None:
    observability = ObservabilityFake()
    provider = ProviderFake()
    provider.model = "gpt-6.1-terra"
    provider.role = "qualification_fact_extraction"
    instrumented = InstrumentedLLMProvider(
        provider, observability=observability  # type: ignore[arg-type]
    )

    await instrumented.generate_structured(
        system_prompt="System", user_prompt="User", response_model=Output
    )

    started = next(
        data for name, data in observability.event_data if name == "llm_request_started"
    )
    assert started["model"] == "gpt-6.1-terra"
    assert started["role"] == "qualification_fact_extraction"


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
    failure_event = next(
        data for name, data in observability.event_data if name == "llm_request_failed"
    )
    assert failure_event["provider"] == "openai"
    assert failure_event["model"] == "gpt-5.6-terra"
    assert failure_event["role"] == "research"
    assert failure_event["duration_ms"] >= 0
    assert failure_event["error_type"] == "RuntimeError"


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


@pytest.mark.asyncio
async def test_instrumentation_sanitizes_provider_errors_by_default() -> None:
    observability = ObservabilityFake()
    secret = "confidential provider response"
    provider = InstrumentedLLMProvider(
        ProviderFake(RuntimeError(secret)),  # type: ignore[arg-type]
        observability=observability,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match=secret):
        await provider.generate_structured(
            system_prompt="private system",
            user_prompt="private document",
            response_model=Output,
        )

    assert observability.span_errors == []
    assert all(secret not in str(event) for event in observability.events)


@pytest.mark.asyncio
async def test_provider_usage_shares_logical_call_and_research_correlation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability = Observability()
    emitted: list[tuple[str, dict[str, object]]] = []

    def record_event(name: str, **data: object) -> None:
        emitted.append((name, {**observability.current_context, **data}))

    monkeypatch.setattr(observability, "event", record_event)
    monkeypatch.setattr(usage_module, "get_observability", lambda: observability)

    class UsageProviderFake(ProviderFake):
        async def generate_structured(self, **_: object) -> Output:
            usage_module.report_llm_usage(
                provider=self.provider,
                model=self.model,
                role=self.role,
                input_tokens=10,
                output_tokens=4,
                duration_ms=12,
            )
            return Output(value="ok")

    provider = InstrumentedLLMProvider(
        UsageProviderFake(), observability=observability  # type: ignore[arg-type]
    )
    with observability.context(
        research_run_id="run-1",
        campaign_id="campaign-1",
        company_id="company-1",
        workflow_node="extract_evidence",
        prompt_name="evidence_extraction",
    ):
        await provider.generate_structured(
            system_prompt="private system",
            user_prompt="private page content",
            response_model=Output,
        )

    started = next(data for name, data in emitted if name == "llm_request_started")
    usage = next(data for name, data in emitted if name == "llm_usage_reported")
    assert usage["logical_llm_call_id"] == started["logical_llm_call_id"]
    assert usage["research_run_id"] == "run-1"
    assert usage["campaign_id"] == "campaign-1"
    assert usage["company_id"] == "company-1"
    assert usage["workflow_node"] == "extract_evidence"
    assert usage["operation_name"] == "evidence_extraction"
    assert "private page content" not in str(emitted)
