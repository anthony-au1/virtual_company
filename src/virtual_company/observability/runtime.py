"""OpenTelemetry, Langfuse, metrics, and correlation helpers."""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langfuse import Langfuse
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider

from virtual_company.config import Settings, get_settings
from virtual_company.observability.logging import configure_logging

logger = logging.getLogger(__name__)
_context: ContextVar[dict[str, str] | None] = ContextVar(
    "observability_context", default=None
)


class Observability:
    """Small facade that keeps telemetry SDK details out of business code."""

    def __init__(self) -> None:
        self._initialized = False
        self._langfuse: Langfuse | None = None
        self._capture_io = False
        self._tracer = trace.get_tracer("virtual_company")
        self._meter = metrics.get_meter("virtual_company")
        self._instruments: dict[str, Any] = {}

    def initialize(self, settings: Settings) -> None:
        """Initialize process-wide telemetry once; disabled telemetry remains no-op."""
        configure_logging(level=settings.log_level, log_format=settings.log_format)
        if self._initialized:
            return
        if settings.otel_enabled:
            resource = Resource.create(
                {
                    SERVICE_NAME: settings.otel_service_name,
                    "deployment.environment": settings.environment,
                }
            )
            provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(provider)
            metrics.set_meter_provider(MeterProvider(resource=resource))
            self._tracer = trace.get_tracer("virtual_company")
            self._meter = metrics.get_meter("virtual_company")
            if settings.langfuse_enabled and self._langfuse_configured(settings):
                self._langfuse = Langfuse(
                    public_key=settings.langfuse_public_key.get_secret_value(),
                    secret_key=settings.langfuse_secret_key.get_secret_value(),
                    base_url=settings.langfuse_base_url,
                    environment=settings.environment,
                    tracer_provider=provider,
                )
        self._capture_io = settings.langfuse_capture_io
        self._create_instruments()
        self._initialized = True

    @staticmethod
    def _langfuse_configured(settings: Settings) -> bool:
        return (
            settings.langfuse_public_key is not None
            and settings.langfuse_secret_key is not None
        )

    def bind(self, **values: str | None) -> None:
        """Attach business correlation fields to subsequent events in this task."""
        current = dict(_context.get() or {})
        current.update(
            {key: value for key, value in values.items() if value is not None}
        )
        _context.set(current)

    @contextmanager
    def context(self, **values: str | None) -> Generator[None, None, None]:
        """Temporarily enrich correlated telemetry without leaking values to later work."""
        current = dict(_context.get() or {})
        current.update(
            {key: value for key, value in values.items() if value is not None}
        )
        token = _context.set(current)
        try:
            yield
        finally:
            _context.reset(token)

    def event(self, name: str, **context: Any) -> None:
        """Emit a structured, metadata-only application event."""
        merged = {
            **(_context.get() or {}),
            **{key: value for key, value in context.items() if value is not None},
        }
        logger.info(name, extra={"context": merged})

    @contextmanager
    def span(
        self, name: str, *, as_type: str = "span", **attributes: Any
    ) -> Generator[Any, None, None]:
        """Create a correlated OTel span and optional Langfuse observation."""
        merged = {**(_context.get() or {}), **attributes}
        started = time.perf_counter()
        if self._langfuse is not None:
            with self._langfuse.start_as_current_observation(
                name=name,
                as_type=as_type,  # type: ignore[arg-type]
                metadata=merged,
                model=attributes.get("model"),
            ) as observation:
                try:
                    yield observation
                except Exception as error:
                    observation.update(level="ERROR", status_message=str(error))
                    raise
                finally:
                    observation.update(
                        metadata={
                            **merged,
                            "duration_ms": int((time.perf_counter() - started) * 1000),
                        }
                    )
            return
        with self._tracer.start_as_current_span(name) as span:
            for key, value in merged.items():
                span.set_attribute(key, str(value))
            try:
                yield span
            except Exception as error:
                span.record_exception(error)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(error)))
                raise

    def record(self, instrument: str, value: float = 1, **attributes: str) -> None:
        """Record a bounded metric measurement."""
        metric = self._instruments.get(instrument)
        if metric is None:
            return
        if instrument.endswith("_total"):
            metric.add(value, attributes)
        else:
            metric.record(value, attributes)

    def shutdown(self) -> None:
        """Flush optional Langfuse export without affecting application shutdown."""
        if self._langfuse is not None:
            try:
                self._langfuse.shutdown()
            except Exception:
                logger.exception("langfuse_shutdown_failed")

    @property
    def capture_io(self) -> bool:
        """Whether Langfuse I/O capture was explicitly enabled."""
        return self._capture_io

    def _create_instruments(self) -> None:
        self._instruments = {
            "research_runs_total": self._meter.create_counter("research_runs_total"),
            "research_run_failures_total": self._meter.create_counter(
                "research_run_failures_total"
            ),
            "research_run_duration_seconds": self._meter.create_histogram(
                "research_run_duration_seconds"
            ),
            "llm_requests_total": self._meter.create_counter("llm_requests_total"),
            "llm_request_failures_total": self._meter.create_counter(
                "llm_request_failures_total"
            ),
            "llm_request_duration_seconds": self._meter.create_histogram(
                "llm_request_duration_seconds"
            ),
            "llm_input_tokens_total": self._meter.create_counter(
                "llm_input_tokens_total"
            ),
            "llm_output_tokens_total": self._meter.create_counter(
                "llm_output_tokens_total"
            ),
            "companies_discovered_total": self._meter.create_counter(
                "companies_discovered_total"
            ),
            "company_candidates_extracted_total": self._meter.create_counter(
                "company_candidates_extracted_total"
            ),
            "company_candidates_aggregated_total": self._meter.create_counter(
                "company_candidates_aggregated_total"
            ),
            "company_research_queries_generated_total": self._meter.create_counter(
                "company_research_queries_generated_total"
            ),
            "company_research_sources_found_total": self._meter.create_counter(
                "company_research_sources_found_total"
            ),
            "company_research_sources_selected_total": self._meter.create_counter(
                "company_research_sources_selected_total"
            ),
            "followup_queries_generated_total": self._meter.create_counter(
                "followup_queries_generated_total"
            ),
            "attributable_pages_total": self._meter.create_counter(
                "attributable_pages_total"
            ),
            "coverage_criteria_total": self._meter.create_counter(
                "coverage_criteria_total"
            ),
            "coverage_found_total": self._meter.create_counter(
                "coverage_found_total"
            ),
            "coverage_missing_total": self._meter.create_counter(
                "coverage_missing_total"
            ),
            "web_search_requests_total": self._meter.create_counter(
                "web_search_requests_total"
            ),
            "web_search_request_failures_total": self._meter.create_counter(
                "web_search_request_failures_total"
            ),
            "web_search_request_duration_seconds": self._meter.create_histogram(
                "web_search_request_duration_seconds"
            ),
            "web_search_results_total": self._meter.create_counter(
                "web_search_results_total"
            ),
            "web_fetch_requests_total": self._meter.create_counter(
                "web_fetch_requests_total"
            ),
            "web_fetch_failures_total": self._meter.create_counter(
                "web_fetch_failures_total"
            ),
            "web_fetch_duration_seconds": self._meter.create_histogram(
                "web_fetch_duration_seconds"
            ),
            "web_fetch_content_chars": self._meter.create_histogram(
                "web_fetch_content_chars"
            ),
            "web_pages_fetched_total": self._meter.create_counter(
                "web_pages_fetched_total"
            ),
            "web_pages_truncated_total": self._meter.create_counter(
                "web_pages_truncated_total"
            ),
            "web_pages_considered_total": self._meter.create_counter(
                "web_pages_considered_total"
            ),
            "evidence_extraction_calls_total": self._meter.create_counter(
                "evidence_extraction_calls_total"
            ),
            "evidence_extraction_failures_total": self._meter.create_counter(
                "evidence_extraction_failures_total"
            ),
            "evidence_items_extracted_total": self._meter.create_counter(
                "evidence_items_extracted_total"
            ),
            "evidence_items_validated_total": self._meter.create_counter(
                "evidence_items_validated_total"
            ),
            "evidence_items_rejected_total": self._meter.create_counter(
                "evidence_items_rejected_total"
            ),
            "evidence_items_persisted_total": self._meter.create_counter(
                "evidence_items_persisted_total"
            ),
            "pages_with_evidence_total": self._meter.create_counter(
                "pages_with_evidence_total"
            ),
            "pages_without_evidence_total": self._meter.create_counter(
                "pages_without_evidence_total"
            ),
        }


_observability = Observability()


def get_observability() -> Observability:
    """Return the process-wide observability facade."""
    return _observability


def configure_observability(settings: Settings | None = None) -> Observability:
    """Configure the shared facade using application settings."""
    observability = get_observability()
    observability.initialize(settings or get_settings())
    return observability


def shutdown_observability() -> None:
    """Flush the shared facade at application shutdown."""
    get_observability().shutdown()
