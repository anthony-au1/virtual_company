"""Deterministic tests for standalone Exploration obligation generation."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from typing import TypeVar, cast

import pytest
from pydantic import BaseModel

from virtual_company.llm.base import LLMStructuredOutputError
from virtual_company.services.obligation_generator import (
    ObligationGenerationResult,
    ObligationGenerationValidationError,
    ObligationGenerator,
)
from virtual_company.workflows.exploration.prompts import (
    GENERATE_EXPLORATION_OBLIGATIONS_PROMPT,
    generate_exploration_obligations_system_prompt,
)

T = TypeVar("T", bound=BaseModel)


class ProviderStub:
    provider = "test-provider"
    model = "test-reasoning-model"
    role = "obligation_generation"

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

    def event(self, name: str, **context: object) -> None:
        self.events.append((name, context))

    @contextmanager
    def span(self, _name: str, **_attributes: object):
        yield None


def result(*descriptions: str) -> ObligationGenerationResult:
    return ObligationGenerationResult(
        obligations=[{"description": description} for description in descriptions]
    )


@pytest.mark.asyncio
async def test_generator_accepts_empty_single_and_multiple_results() -> None:
    empty = await ObligationGenerator(ProviderStub(result())).generate("gibberish", 10)
    one = await ObligationGenerator(
        ProviderStub(result("Determine which licences apply to the planned activity."))
    ).generate("Enter a regulated market", 10)
    many = await ObligationGenerator(
        ProviderStub(
            result(
                "Determine which licences apply.",
                "Determine whether local demand supports entry.",
            )
        )
    ).generate("Assess market entry", 2)

    assert empty.obligations == []
    assert len(one.obligations) == 1
    assert len(many.obligations) == 2


@pytest.mark.asyncio
async def test_generator_accepts_fewer_than_max_and_exactly_max() -> None:
    below = await ObligationGenerator(
        ProviderStub(result("One requirement."))
    ).generate("context", 3)
    exact = await ObligationGenerator(
        ProviderStub(result("First requirement.", "Second requirement."))
    ).generate("context", 2)

    assert len(below.obligations) == 1
    assert len(exact.obligations) == 2


@pytest.mark.asyncio
async def test_generator_passes_context_and_maximum_to_prompt() -> None:
    provider = ProviderStub(result())
    await ObligationGenerator(provider).generate("Regulatory entry context", 7)

    call = provider.calls[0]
    assert call["response_model"] is ObligationGenerationResult
    assert json.loads(cast(str, call["user_prompt"])) == {
        "business_context": "Regulatory entry context",
        "max_obligations": 7,
    }


@pytest.mark.asyncio
async def test_generator_records_capability_prompt_and_result_count() -> None:
    observability = ObservabilityStub()
    result_value = await ObligationGenerator(
        ProviderStub(result("One.")), observability=observability
    ).generate("context", 3)

    completed_name, metadata = observability.events[-1]
    assert completed_name == "obligation_generation_completed"
    assert metadata["capability"] == "obligation_generation"
    assert metadata["provider"] == "test-provider"
    assert metadata["model"] == "test-reasoning-model"
    assert metadata["prompt_name"] == "generate_exploration_obligations"
    assert metadata["prompt_version"] == "v1"
    assert metadata["max_obligations"] == 3
    assert metadata["generated_obligation_count"] == len(result_value.obligations)


@pytest.mark.asyncio
async def test_generator_rejects_excess_output_without_truncating() -> None:
    generator = ObligationGenerator(ProviderStub(result("One.", "Two.")))

    with pytest.raises(ObligationGenerationValidationError, match="exceeds"):
        await generator.generate("context", 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("maximum", [0, 21, None, True, "2"])
async def test_generator_rejects_invalid_maximum(maximum: object) -> None:
    with pytest.raises(ValueError, match="between 1 and 20"):
        await ObligationGenerator(ProviderStub(result())).generate(
            "context", cast(int, maximum)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("description", ["", "   ", "\n\t"])
async def test_generator_rejects_empty_descriptions(description: str) -> None:
    with pytest.raises(ObligationGenerationValidationError, match="invalid"):
        await ObligationGenerator(
            ProviderStub({"obligations": [{"description": description}]})
        ).generate("context", 2)


@pytest.mark.asyncio
async def test_generator_rejects_punctuation_only_descriptions() -> None:
    provider = ProviderStub({"obligations": [{"description": "...?!"}]})

    with pytest.raises(ObligationGenerationValidationError, match="meaningful text"):
        await ObligationGenerator(provider).generate("context", 2)


@pytest.mark.asyncio
async def test_generator_rejects_normalized_duplicates() -> None:
    generator = ObligationGenerator(
        ProviderStub(
            result(
                "Determine which licences apply.",
                "  Determine WHICH licences apply.  ",
            )
        )
    )

    with pytest.raises(ObligationGenerationValidationError, match="duplicate"):
        await generator.generate("context", 4)


@pytest.mark.asyncio
async def test_generator_rejects_malformed_structured_response() -> None:
    provider = ProviderStub(
        {"obligations": [{"description": "Valid", "title": "No title"}]}
    )

    with pytest.raises(ObligationGenerationValidationError, match="invalid"):
        await ObligationGenerator(provider).generate("context", 2)


@pytest.mark.asyncio
async def test_generator_requires_obligations_to_be_a_list() -> None:
    provider = ProviderStub({"obligations": ("not", "a list")})

    with pytest.raises(ObligationGenerationValidationError, match="invalid"):
        await ObligationGenerator(provider).generate("context", 3)


@pytest.mark.asyncio
async def test_generator_normalizes_whitespace_in_descriptions() -> None:
    generated = await ObligationGenerator(
        ProviderStub(result("  Determine   which licences\n apply.  "))
    ).generate("context", 2)

    assert generated.obligations[0].description == "Determine which licences apply."


@pytest.mark.asyncio
async def test_provider_failure_remains_a_technical_failure() -> None:
    provider_error = LLMStructuredOutputError("provider returned malformed output")

    with pytest.raises(LLMStructuredOutputError):
        await ObligationGenerator(ProviderStub(provider_error)).generate("context", 2)


@pytest.mark.asyncio
async def test_timeout_remains_a_technical_failure() -> None:
    generator = ObligationGenerator(SlowProvider(result("One.")), timeout_seconds=0.001)

    with pytest.raises(TimeoutError):
        await generator.generate("context", 2)


@pytest.mark.asyncio
async def test_obligation_subject_is_not_forced_to_be_a_company() -> None:
    generated = await ObligationGenerator(
        ProviderStub(result("Determine which consumer-protection requirements apply."))
    ).generate("Enter a regulated market", 4)

    assert "consumer-protection" in generated.obligations[0].description
    assert "the company" not in generated.obligations[0].description.casefold()


def test_prompt_identity_and_contract_are_versioned() -> None:
    assert GENERATE_EXPLORATION_OBLIGATIONS_PROMPT.name == (
        "generate_exploration_obligations"
    )
    assert GENERATE_EXPLORATION_OBLIGATIONS_PROMPT.version == "v1"
    prompt = generate_exploration_obligations_system_prompt().casefold()
    for requirement in (
        "free-text",
        "holistically",
        "not inherently company-specific",
        "what must be established",
        "search or workflow action",
        "facts, answers, conclusions, or hypotheses",
        "distinct",
        "minimum useful set",
        "hard ceiling, not a target",
        "zero obligations is valid",
        "do not invent requirements",
    ):
        assert requirement in prompt
