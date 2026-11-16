"""Canonical provider usage reporting shared by LLM SDK adapters."""

from __future__ import annotations

from typing import Any

from virtual_company.observability import get_observability


def report_llm_usage(
    *,
    provider: str,
    model: str,
    role: str | None,
    duration_ms: int,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    reasoning_tokens: int | None = None,
    configured_output_tokens: int | None = None,
    configured_max_retries: int | None = None,
    cached_input_tokens: int | None = None,
    cache_write_input_tokens: int | None = None,
    response_id: str | None = None,
    request_id: str | None = None,
    service_tier: str | None = None,
    response_status: str | None = None,
    incomplete_reason: str | None = None,
    request_outcome: str = "completed",
) -> None:
    """Emit reported provider usage without altering the provider return contract."""
    observability = get_observability()
    context: dict[str, Any] = observability.current_context
    operation_name = context.get("prompt_name") or context.get("workflow_node")
    observability.event(
        "llm_usage_reported",
        provider=provider,
        model=model,
        role=role,
        operation_name=operation_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=reasoning_tokens,
        configured_output_tokens=configured_output_tokens,
        configured_max_retries=configured_max_retries,
        cached_input_tokens=cached_input_tokens,
        cache_write_input_tokens=cache_write_input_tokens,
        response_id=response_id,
        request_id=request_id,
        service_tier=service_tier,
        response_status=response_status,
        incomplete_reason=incomplete_reason,
        duration_ms=duration_ms,
        request_outcome=request_outcome,
    )

    metric_attributes = {
        "provider": provider,
        "model": model,
        "role": role or "unknown",
        "workflow_node": context.get("workflow_node", "unknown"),
    }
    token_values = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_input_tokens": cache_write_input_tokens,
    }
    instruments = {
        "input_tokens": "llm_input_tokens_total",
        "output_tokens": "llm_output_tokens_total",
        "reasoning_tokens": "llm_reasoning_tokens_total",
        "cached_input_tokens": "llm_cached_input_tokens_total",
        "cache_write_input_tokens": "llm_cache_write_input_tokens_total",
    }
    for field, value in token_values.items():
        if isinstance(value, int) and not isinstance(value, bool):
            observability.record(instruments[field], value, **metric_attributes)
