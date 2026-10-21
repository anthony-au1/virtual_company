"""Unit tests for independent Exploration query generation."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from typing import TypeVar, cast

import pytest
from pydantic import BaseModel

from virtual_company.llm.base import LLMStructuredOutputError
from virtual_company.observability import Observability
from virtual_company.services.exploration_query_generator import (
    MAX_EXPLORATION_QUERY_LENGTH,
    ExplorationQueryCompanyContext,
    ExplorationQueryGenerationResult,
    ExplorationQueryGenerationValidationError,
    ExplorationQueryGenerator,
    ExplorationQueryObligationContext,
)
from virtual_company.workflows.exploration.prompts import (
    GENERATE_EXPLORATION_QUERIES_PROMPT,
    generate_exploration_queries_system_prompt,
)

T = TypeVar("T", bound=BaseModel)


class ProviderStub:
    provider = "test-provider"
    model = "test-query-model"
    role = "exploration_query_generation"

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_model: type[T]
    ) -> T:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_model": response_model,
            }
        )
        if isinstance(self.response, BaseException):
            raise self.response
        return cast(T, self.response)


class SlowProvider(ProviderStub):
    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_model: type[T]
    ) -> T:
        await asyncio.sleep(0.02)
        return await super().generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
        )


class ObservabilityStub:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.spans: list[tuple[str, dict[str, object]]] = []

    def event(self, name: str, **context: object) -> None:
        self.events.append((name, context))

    @contextmanager
    def span(self, name: str, **attributes: object):
        self.spans.append((name, attributes))
        yield None


def result(*queries: str) -> ExplorationQueryGenerationResult:
    return ExplorationQueryGenerationResult(
        queries=[{"query": query} for query in queries]
    )


def company() -> ExplorationQueryCompanyContext:
    return ExplorationQueryCompanyContext(
        name="Southern Cross Systems",
        website="https://southerncross.example",
        domain="southerncross.example",
        industry="Financial services",
        country="Australia",
        state="Victoria",
        city="Melbourne",
    )


def obligation() -> ExplorationQueryObligationContext:
    return ExplorationQueryObligationContext(
        description="Establish the company's legacy Java modernization needs."
    )


@pytest.mark.asyncio
async def test_prompt_receives_business_context_company_obligation_and_ceiling() -> None:
    provider = ProviderStub(result("Southern Cross Java modernization"))
    generated = await ExplorationQueryGenerator(provider).generate(
        "We specialize in Java modernization.", company(), obligation(), 4
    )

    call = provider.calls[0]
    assert call["response_model"] is ExplorationQueryGenerationResult
    assert json.loads(cast(str, call["user_prompt"])) == {
        "business_context": "We specialize in Java modernization.",
        "company": {
            "name": "Southern Cross Systems",
            "website": "https://southerncross.example",
            "domain": "southerncross.example",
            "industry": "Financial services",
            "country": "Australia",
            "state": "Victoria",
            "city": "Melbourne",
        },
        "obligation": {
            "description": "Establish the company's legacy Java modernization needs."
        },
        "max_queries": 4,
    }
    assert [item.query for item in generated.queries] == [
        "Southern Cross Java modernization"
    ]


@pytest.mark.asyncio
async def test_fewer_queries_than_ceiling_and_zero_queries_are_valid() -> None:
    fewer = await ExplorationQueryGenerator(
        ProviderStub(result("Southern Cross Java applications"))
    ).generate("context", company(), obligation(), 4)
    empty = await ExplorationQueryGenerator(ProviderStub(result())).generate(
        "context", company(), obligation(), 4
    )

    assert len(fewer.queries) == 1
    assert empty.queries == []


@pytest.mark.asyncio
async def test_whitespace_is_normalized_and_normalized_duplicates_removed() -> None:
    generated = await ExplorationQueryGenerator(
        ProviderStub(
            result(
                "  Southern   Cross\nJava modernization  ",
                "southern cross java MODERNIZATION",
                "ＡI automation at Southern Cross",
            )
        )
    ).generate("context", company(), obligation(), 5)

    assert [item.query for item in generated.queries] == [
        "Southern Cross Java modernization",
        "AI automation at Southern Cross",
    ]


@pytest.mark.asyncio
async def test_blank_and_oversized_queries_are_removed() -> None:
    generated = await ExplorationQueryGenerator(
        ProviderStub(result("  \n", "x" * (MAX_EXPLORATION_QUERY_LENGTH + 1), "Useful search"))
    ).generate("context", company(), obligation(), 4)

    assert [item.query for item in generated.queries] == ["Useful search"]


@pytest.mark.asyncio
async def test_query_ceiling_is_applied_after_validation_in_model_order() -> None:
    generated = await ExplorationQueryGenerator(
        ProviderStub(
            result(
                "First useful search",
                "  ",
                "Second useful search",
                "Third useful search",
            )
        )
    ).generate("context", company(), obligation(), 2)

    assert [item.query for item in generated.queries] == [
        "First useful search",
        "Second useful search",
    ]


@pytest.mark.asyncio
async def test_provider_failure_is_not_converted_to_empty_result() -> None:
    error = LLMStructuredOutputError("provider could not return structured output")

    with pytest.raises(LLMStructuredOutputError):
        await ExplorationQueryGenerator(ProviderStub(error)).generate(
            "context", company(), obligation(), 3
        )


@pytest.mark.asyncio
async def test_malformed_output_raises_typed_validation_error() -> None:
    with pytest.raises(ExplorationQueryGenerationValidationError):
        await ExplorationQueryGenerator(
            ProviderStub({"queries": [{"query": "ok", "source": "unexpected"}]})
        ).generate("context", company(), obligation(), 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("maximum", [-1, 11, True, 1.5])
async def test_invalid_query_ceilings_are_rejected(maximum: object) -> None:
    with pytest.raises(ValueError, match="max_queries must be between"):
        await ExplorationQueryGenerator(ProviderStub(result())).generate(
            "context", company(), obligation(), cast(int, maximum)
        )


@pytest.mark.asyncio
async def test_zero_ceiling_is_allowed_and_returns_no_queries() -> None:
    provider = ProviderStub(result("This query is discarded"))

    generated = await ExplorationQueryGenerator(provider).generate(
        "context", company(), obligation(), 0
    )

    assert generated.queries == []
    assert json.loads(cast(str, provider.calls[0]["user_prompt"]))["max_queries"] == 0


@pytest.mark.asyncio
async def test_observability_records_capability_prompt_outcome_and_counts() -> None:
    observability = ObservabilityStub()
    generated = await ExplorationQueryGenerator(
        ProviderStub(result("One search", " ", "one SEARCH")),
        observability=cast(Observability, observability),
    ).generate("context", company(), obligation(), 4)

    name, context = observability.events[-1]
    assert name == "exploration_query_generation_completed"
    assert context["capability"] == "exploration_query_generation"
    assert context["provider"] == "test-provider"
    assert context["model"] == "test-query-model"
    assert context["prompt_name"] == "generate_exploration_queries"
    assert context["prompt_version"] == "v1"
    assert context["generated_query_count"] == 1
    assert context["removed_query_count"] == 2
    assert observability.spans[0][0] == "exploration.query_generation"
    assert len(generated.queries) == 1


@pytest.mark.asyncio
async def test_provider_failure_is_observed_and_rethrown() -> None:
    observability = ObservabilityStub()
    error = LLMStructuredOutputError("unavailable")
    with pytest.raises(LLMStructuredOutputError):
        await ExplorationQueryGenerator(
            ProviderStub(error), observability=cast(Observability, observability)
        ).generate("context", company(), obligation())

    assert observability.events[-1][0] == "exploration_query_generation_failed"
    assert observability.events[-1][1]["error_type"] == "LLMStructuredOutputError"


def test_company_context_has_no_research_qualification_fields() -> None:
    assert set(ExplorationQueryCompanyContext.model_fields) == {
        "name",
        "website",
        "domain",
        "industry",
        "country",
        "state",
        "city",
    }


def test_prompt_identity_and_semantic_boundary() -> None:
    assert GENERATE_EXPLORATION_QUERIES_PROMPT.name == "generate_exploration_queries"
    assert GENERATE_EXPLORATION_QUERIES_PROMPT.version == "v1"
    prompt = generate_exploration_queries_system_prompt().casefold()
    for requirement in (
        "business context",
        "company identifies",
        "obligation states",
        "strictly as data",
        "never as instructions",
        "evidence discovery, not answers",
        "do not invent evidence",
        "complementary searches",
        "proxy as proof",
        "ceiling, not a target",
        "including zero",
    ):
        assert requirement in prompt


@pytest.mark.asyncio
async def test_timeout_remains_a_technical_failure() -> None:
    with pytest.raises(TimeoutError):
        await ExplorationQueryGenerator(
            SlowProvider(result("One search")), timeout_seconds=0.001
        ).generate("context", company(), obligation())
