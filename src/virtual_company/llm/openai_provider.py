"""OpenAI-backed structured-output provider."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any, cast

import httpx
from openai import AsyncOpenAI, AuthenticationError, RateLimitError
from pydantic import SecretStr, ValidationError

from virtual_company.config import get_settings
from virtual_company.llm.base import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMStructuredOutputError,
    T,
)
from virtual_company.llm.usage import report_llm_usage

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """Generate structured output through the OpenAI Responses API."""

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        model: str | None,
        role: str | None = None,
        client: AsyncOpenAI | None = None,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        resolved_api_key = (
            api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        )
        if not resolved_api_key or not model:
            raise LLMConfigurationError(
                "OPENAI_API_KEY and an OpenAI model must be configured to use OpenAIProvider"
            )

        self._model = model
        self._role = role
        settings = get_settings()
        self._configured_max_retries = settings.openai_max_retries
        if max_output_tokens is None:
            max_output_tokens = (
                settings.openai_research_max_output_tokens
                if role == "research"
                and settings.openai_research_max_output_tokens is not None
                else settings.openai_max_output_tokens
            )
        if reasoning_effort is None:
            reasoning_effort = (
                settings.openai_research_reasoning_effort
                if role == "research"
                and settings.openai_research_reasoning_effort is not None
                else settings.openai_reasoning_effort
            )
        if max_output_tokens < 1:
            raise LLMConfigurationError("OpenAI max output tokens must be positive")
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        if client is None:
            read_timeout = settings.openai_read_timeout_seconds
            self._client = AsyncOpenAI(
                api_key=resolved_api_key,
                timeout=httpx.Timeout(
                    connect=settings.openai_connect_timeout_seconds,
                    read=read_timeout,
                    write=read_timeout,
                    pool=read_timeout,
                ),
                max_retries=settings.openai_max_retries,
            )
        else:
            self._client = client

    @property
    def provider(self) -> str:
        """Return the provider identifier used for observability."""
        return "openai"

    @property
    def model(self) -> str:
        """Return the configured provider model."""
        return self._model

    @property
    def role(self) -> str | None:
        """Return the configured application role."""
        return self._role

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        """Generate Pydantic-validated structured output."""
        logger.info(
            "LLM structured generation provider=%s model=%s role=%s",
            "openai",
            self._model,
            self._role,
        )
        request_options: dict[str, object] = {
            "max_output_tokens": self._max_output_tokens
        }
        if self._reasoning_effort is not None:
            request_options["reasoning"] = {"effort": self._reasoning_effort}
        started = time.perf_counter()
        try:
            raw_response = await self._client.responses.with_raw_response.parse(
                model=self._model,
                instructions=system_prompt,
                input=user_prompt,
                text_format=response_model,
                **request_options,
            )
        except AuthenticationError as error:
            raise LLMAuthenticationError("OpenAI authentication failed") from error
        except RateLimitError as error:
            raise LLMRateLimitError("OpenAI rate limit exceeded") from error
        response_metadata = self._response_metadata(raw_response)
        try:
            # The SDK's raw response wrapper exposes a local synchronous parser;
            # it parses the already-received body and performs no second request.
            response = raw_response.parse()
        except Exception as error:
            try:
                self._report_parse_failure(
                    error,
                    response_metadata,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            except Exception:  # noqa: BLE001 - diagnostics must not mask parse errors
                logger.warning("openai_structured_output_diagnostic_failed")
            raise
        duration_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage", None)
        input_details = getattr(usage, "input_tokens_details", None)
        output_details = getattr(usage, "output_tokens_details", None)
        incomplete_details = getattr(response, "incomplete_details", None)
        status = getattr(response, "status", None)
        outcome = (
            "completed"
            if status == "completed"
            else "incomplete"
            if status == "incomplete"
            else "unknown"
            if status is None
            else "other"
        )
        report_llm_usage(
            provider="openai",
            model=getattr(response, "model", None) or self._model,
            role=self._role,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            reasoning_tokens=getattr(output_details, "reasoning_tokens", None),
            configured_output_tokens=self._max_output_tokens,
            configured_max_retries=self._configured_max_retries,
            cached_input_tokens=getattr(input_details, "cached_tokens", None),
            cache_write_input_tokens=getattr(input_details, "cache_write_tokens", None),
            response_id=getattr(response, "id", None),
            request_id=getattr(response, "_request_id", None),
            service_tier=getattr(response, "service_tier", None),
            response_status=status,
            incomplete_reason=getattr(incomplete_details, "reason", None),
            duration_ms=duration_ms,
            request_outcome=outcome,
        )
        if status is not None and status != "completed":
            reason = getattr(incomplete_details, "reason", None) or "unspecified"
            raise LLMStructuredOutputError(
                f"OpenAI response was not completed (status={status}, reason={reason})"
            )
        if getattr(response, "output_parsed", None) is None:
            raise LLMStructuredOutputError("OpenAI returned no structured output")
        return cast(T, response.output_parsed)

    def _response_metadata(self, raw_response: Any) -> dict[str, Any]:
        """Read only provider metadata from the SDK raw response, never its text."""
        metadata: dict[str, Any] = {
            "http_status": getattr(raw_response, "status_code", None),
            "request_id": getattr(raw_response, "request_id", None),
        }
        try:
            payload = raw_response.http_response.json()
        except Exception:  # noqa: BLE001 - diagnostics must not mask response parsing
            return metadata
        if not isinstance(payload, Mapping):
            return metadata

        metadata["response_id"] = payload.get("id")
        metadata["response_status"] = payload.get("status")
        metadata["model"] = payload.get("model") or self._model
        incomplete = payload.get("incomplete_details")
        if isinstance(incomplete, Mapping):
            metadata["incomplete_reason"] = incomplete.get("reason")
        usage = payload.get("usage")
        if isinstance(usage, Mapping):
            metadata["input_tokens"] = usage.get("input_tokens")
            metadata["output_tokens"] = usage.get("output_tokens")
            metadata["total_tokens"] = usage.get("total_tokens")
            output_details = usage.get("output_tokens_details")
            if isinstance(output_details, Mapping):
                metadata["reasoning_tokens"] = output_details.get("reasoning_tokens")
        return metadata

    def _report_parse_failure(
        self,
        error: Exception,
        response_metadata: dict[str, Any],
        *,
        duration_ms: int,
    ) -> None:
        """Emit metadata-only diagnostics for a structured response parse failure."""
        if isinstance(error, ValidationError):
            try:
                errors = error.errors(include_input=False, include_url=False)
                error_types = {str(item.get("type", "")) for item in errors}
            except Exception:  # noqa: BLE001 - preserve the original parse error
                error_types = set()
            category = (
                "malformed_json"
                if "json_invalid" in error_types
                or "value_error.jsondecode" in error_types
                else "schema_validation"
            )
        else:
            category = "provider_sdk_parse_error"
        from virtual_company.observability import get_observability

        context = get_observability().current_context
        get_observability().event(
            "llm_structured_output_parse_failed",
            provider="openai",
            operation_name=context.get("prompt_name") or context.get("workflow_node"),
            role=self._role,
            model=response_metadata.get("model") or self._model,
            logical_llm_call_id=context.get("logical_llm_call_id"),
            request_id=response_metadata.get("request_id"),
            response_id=response_metadata.get("response_id"),
            http_status=response_metadata.get("http_status"),
            response_status=response_metadata.get("response_status"),
            incomplete_reason=response_metadata.get("incomplete_reason"),
            configured_max_output_tokens=self._max_output_tokens,
            input_tokens=response_metadata.get("input_tokens"),
            output_tokens=response_metadata.get("output_tokens"),
            reasoning_tokens=response_metadata.get("reasoning_tokens"),
            exception_type=type(error).__name__,
            error_category=category,
            duration_ms=duration_ms,
        )
