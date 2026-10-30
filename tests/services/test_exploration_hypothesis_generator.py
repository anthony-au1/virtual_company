"""Focused contracts for standalone Exploration Hypothesis Generation."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from virtual_company.config import Settings
from virtual_company.domain.exploration.hypotheses import ExplorationHypothesis
from virtual_company.llm import LLMError
from virtual_company.services.exploration_hypothesis_generator import (
    ExplorationHypothesisGenerator,
    ExplorationHypothesisInputValidationError,
    create_configured_exploration_hypothesis_generator,
)
from virtual_company.workflows.exploration.models import (
    ExplorationHypothesisCompanyContext,
    ExplorationHypothesisFactInput,
    ExtractedExplorationHypotheses,
)
from virtual_company.workflows.exploration.models import (
    ExplorationHypothesisGenerationFailureCategory as FailureCategory,
)
from virtual_company.workflows.exploration.models import (
    ExplorationHypothesisGenerationOutcome as Outcome,
)
from virtual_company.workflows.exploration.prompts import (
    GENERATE_EXPLORATION_HYPOTHESES_PROMPT,
    generate_exploration_hypotheses_system_prompt,
    generate_exploration_hypotheses_user_prompt,
)


class ProviderStub:
    provider = "test-provider"
    model = "test-model"
    role = "exploration_hypothesis_generation"

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response or {"hypotheses": []}
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def generate_structured(self, *, system_prompt, user_prompt, response_model):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_model": response_model,
            }
        )
        if self.error is not None:
            raise self.error
        return response_model.model_validate(self.response)


class BlockingProvider(ProviderStub):
    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        await asyncio.Event().wait()


class ObservabilityStub:
    capture_io = True

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.spans: list[str] = []

    def event(self, name: str, **metadata: object) -> None:
        self.events.append((name, metadata))

    @contextmanager
    def span(self, name: str, **_: object):
        self.spans.append(name)
        yield None


def company(company_id=None, name: str = "Acme"):
    return ExplorationHypothesisCompanyContext(
        exploration_company_id=company_id or uuid4(), company_name=name
    )


def fact(company_id, statement: str, fact_id=None):
    return ExplorationHypothesisFactInput(
        fact_id=fact_id or uuid4(),
        exploration_company_id=company_id,
        statement=statement,
    )


def service(response=None, *, provider=None, **kwargs):
    provider = provider or ProviderStub(response)
    observability = ObservabilityStub()
    instance = ExplorationHypothesisGenerator(
        provider,
        observability=cast(Any, observability),
        **kwargs,
    )
    return instance, provider, observability


@pytest.mark.asyncio
async def test_generates_once_with_all_ordered_facts_and_resolves_transient_labels():
    selected = company()
    f1 = fact(selected.exploration_company_id, "Acme runs Java 8.")
    f2 = fact(selected.exploration_company_id, "Acme announced modernization.")
    provider = ProviderStub(
        {
            "hypotheses": [
                {
                    "statement": "A modernization program may require Java expertise.",
                    "fact_refs": ["F1", "F2"],
                }
            ]
        }
    )
    instance, _, _ = service(provider=provider)

    result = await instance.generate(
        selected, "We provide Java modernization.", [f1, f2]
    )

    assert result.outcome is Outcome.SUCCEEDED
    assert len(provider.calls) == 1
    assert result.hypotheses[0].exploration_company_id == selected.exploration_company_id
    assert result.hypotheses[0].fact_ids == (f1.fact_id, f2.fact_id)
    assert "F1" in str(provider.calls[0]["user_prompt"])
    assert "F2" in str(provider.calls[0]["user_prompt"])
    assert str(f1.fact_id) not in str(provider.calls[0]["user_prompt"])
    assert str(f2.fact_id) not in str(provider.calls[0]["user_prompt"])


@pytest.mark.asyncio
async def test_rejects_cross_company_and_duplicate_fact_ids_before_provider_call():
    selected = company()
    provider = ProviderStub()
    instance, _, _ = service(provider=provider)
    foreign = fact(uuid4(), "Foreign company fact.")
    with pytest.raises(ExplorationHypothesisInputValidationError):
        await instance.generate(selected, "Context", [foreign])

    duplicate_id = uuid4()
    repeated = [
        fact(selected.exploration_company_id, "Fact one", duplicate_id),
        fact(selected.exploration_company_id, "Fact two", duplicate_id),
    ]
    with pytest.raises(ExplorationHypothesisInputValidationError, match="unique"):
        await instance.generate(selected, "Context", repeated)
    assert provider.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("max_hypotheses", [True, False, 0, 21, 1.5, "10"])
async def test_rejects_invalid_maximum_before_call(max_hypotheses):
    selected = company()
    instance, provider, _ = service()
    with pytest.raises(ValueError, match="between 1 and 20"):
        await instance.generate(
            selected,
            "Context",
            [fact(selected.exploration_company_id, "A Fact.")],
            max_hypotheses=max_hypotheses,
        )
    assert provider.calls == []


@pytest.mark.asyncio
async def test_empty_facts_succeeds_without_provider_call():
    selected = company()
    instance, provider, _ = service()

    result = await instance.generate(selected, "Useful context", [])

    assert result.outcome is Outcome.SUCCEEDED
    assert result.hypotheses == ()
    assert provider.calls == []


@pytest.mark.asyncio
async def test_empty_hypothesis_output_is_successful_for_nonempty_facts():
    selected = company()
    item = fact(selected.exploration_company_id, "No useful implication follows.")
    instance, provider, _ = service({"hypotheses": []})

    result = await instance.generate(selected, "Context", [item])

    assert result.outcome is Outcome.SUCCEEDED
    assert result.hypotheses == ()
    assert result.rejected_hypothesis_count == 0
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_blank_business_context_is_rejected_and_blank_company_name_dto_fails():
    selected = company()
    instance, provider, _ = service()
    with pytest.raises(ValueError, match="business_context"):
        await instance.generate(
            selected,
            " \n ",
            [fact(selected.exploration_company_id, "A Fact.")],
        )
    with pytest.raises(ValidationError):
        company(name=" \t ")
    assert provider.calls == []


@pytest.mark.asyncio
async def test_invalid_candidate_is_rejected_but_valid_sibling_survives():
    selected = company()
    item = fact(selected.exploration_company_id, "Supplier consolidation.")
    instance, _, _ = service(
        {
            "hypotheses": [
                {"statement": "Unknown support.", "fact_refs": ["F1", "F999"]},
                {"statement": "   ", "fact_refs": ["F1"]},
                {
                    "statement": "   New providers may face barriers.  ",
                    "fact_refs": ["F1", "F1"],
                },
            ]
        }
    )

    result = await instance.generate(selected, "Context", [item])

    assert result.outcome is Outcome.SUCCEEDED
    assert result.rejected_hypothesis_count == 2
    assert len(result.hypotheses) == 1
    assert result.hypotheses[0].statement == "New providers may face barriers."
    assert result.hypotheses[0].fact_ids == (item.fact_id,)


@pytest.mark.asyncio
async def test_exact_duplicates_keep_first_wording_and_union_support_in_order():
    selected = company()
    one = fact(selected.exploration_company_id, "First signal.")
    two = fact(selected.exploration_company_id, "Second signal.")
    instance, _, _ = service(
        {
            "hypotheses": [
                {"statement": "May need expertise.", "fact_refs": ["F1"]},
                {"statement": "  MAY  need expertise. ", "fact_refs": ["F2", "F1"]},
                {"statement": "May need external expertise.", "fact_refs": ["F2"]},
            ]
        }
    )

    result = await instance.generate(selected, "Context", [one, two])

    assert len(result.hypotheses) == 2
    assert result.hypotheses[0].statement == "May need expertise."
    assert result.hypotheses[0].fact_ids == (one.fact_id, two.fact_id)
    assert result.hypotheses[1].statement == "May need external expertise."


@pytest.mark.asyncio
async def test_over_maximum_and_malformed_top_level_are_failures_without_partial_results():
    selected = company()
    item = fact(selected.exploration_company_id, "Fact.")
    too_many, provider, _ = service(
        {"hypotheses": [{"statement": f"H{i}", "fact_refs": ["F1"]} for i in range(2)]}
    )
    over = await too_many.generate(selected, "Context", [item], max_hypotheses=1)
    assert over.outcome is Outcome.FAILED
    assert over.failure_category is FailureCategory.MALFORMED_OUTPUT
    assert over.hypotheses == ()
    assert len(provider.calls) == 1

    malformed, _, _ = service({"hypotheses": [], "extra": "forbidden"})
    invalid = await malformed.generate(selected, "Context", [item])
    assert invalid.failure_category is FailureCategory.MALFORMED_OUTPUT
    assert invalid.hypotheses == ()


@pytest.mark.asyncio
async def test_prompt_size_limit_counts_composed_prompts_and_never_calls_provider():
    selected = company()
    item = fact(selected.exploration_company_id, "Short fact.")
    system = generate_exploration_hypotheses_system_prompt()
    user = generate_exploration_hypotheses_user_prompt(
        selected.company_name,
        "Context",
        [{"fact_ref": "F1", "statement": item.statement}],
        10,
    )
    exact_size = len(system) + len(user)
    exact, exact_provider, _ = service(max_input_chars=exact_size)
    assert (await exact.generate(selected, "Context", [item])).outcome is Outcome.SUCCEEDED
    assert len(exact_provider.calls) == 1

    over, over_provider, _ = service(max_input_chars=exact_size - 1)
    result = await over.generate(selected, "Context", [item])
    assert result.outcome is Outcome.FAILED
    assert result.failure_category is FailureCategory.INPUT_LIMIT
    assert result.hypotheses == ()
    assert over_provider.calls == []


@pytest.mark.asyncio
async def test_configuration_provider_and_timeout_failures_are_normalized_safely():
    selected = company()
    item = fact(selected.exploration_company_id, "Sensitive fact text.")
    telemetry = ObservabilityStub()
    missing_config = create_configured_exploration_hypothesis_generator(
        Settings(), observability=cast(Any, telemetry)
    )
    config_result = await missing_config.generate(selected, "Private context", [item])
    assert config_result.failure_category is FailureCategory.CONFIGURATION

    configured = create_configured_exploration_hypothesis_generator(
        Settings(openai_api_key="test-key")
    )
    assert configured._provider.role == "exploration_hypothesis_generation"
    assert configured._provider.model == "gpt-6.1-terra"
    assert configured._provider._capture_io_override is False
    assert configured._provider._sanitize_errors is True

    provider = ProviderStub(error=RuntimeError("secret provider error"))
    failed, _, telemetry = service(provider=provider)
    failed._observability = telemetry
    failure = await failed.generate(selected, "Private context", [item])
    assert failure.failure_category is FailureCategory.UNEXPECTED_ERROR
    assert "secret provider error" not in str(telemetry.events)

    llm_provider = ProviderStub(error=LLMError("secret LLM failure"))
    provider_failure, _, _ = service(provider=llm_provider)
    categorized = await provider_failure.generate(selected, "Context", [item])
    assert categorized.failure_category is FailureCategory.PROVIDER_ERROR

    timeout_provider = ProviderStub(error=TimeoutError("private timeout"))
    timeout, _, _ = service(provider=timeout_provider)
    timeout_result = await timeout.generate(selected, "Context", [item])
    assert timeout_result.failure_category is FailureCategory.TIMEOUT
    assert len(timeout_provider.calls) == 1


@pytest.mark.asyncio
async def test_timeout_wrapper_and_cancellation_propagate_without_retry():
    selected = company()
    item = fact(selected.exploration_company_id, "A Fact.")
    provider = BlockingProvider()
    instance, _, _ = service(provider=provider, timeout_seconds=0.01)
    timed_out = await instance.generate(selected, "Context", [item])
    assert timed_out.failure_category is FailureCategory.TIMEOUT
    assert len(provider.calls) == 1

    blocker = BlockingProvider()
    cancellable, _, _ = service(provider=blocker)
    task = asyncio.create_task(cancellable.generate(selected, "Context", [item]))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(blocker.calls) == 1


def test_prompt_identity_and_required_semantics():
    assert GENERATE_EXPLORATION_HYPOTHESES_PROMPT.name == (
        "generate_exploration_hypotheses"
    )
    assert GENERATE_EXPLORATION_HYPOTHESES_PROMPT.version == "v1"
    prompt = generate_exploration_hypotheses_system_prompt().casefold()
    for phrase in (
        "untrusted data",
        "never follow commands",
        "complete fact set",
        "opportunities",
        "risks",
        "barriers",
        "conflict",
        "appropriately qualified",
        "do not provide",
        "max_hypotheses is a ceiling",
    ):
        assert phrase in prompt
    assert ExtractedExplorationHypotheses.model_validate({"hypotheses": []})


@pytest.mark.asyncio
async def test_observability_does_not_include_business_or_fact_content():
    selected = company()
    private_context = "Private business strategy phrase."
    private_fact = fact(
        selected.exploration_company_id, "Acme has a secret platform migration."
    )
    telemetry = ObservabilityStub()
    instance, _, _ = service(
        {"hypotheses": [{"statement": "May need migration help.", "fact_refs": ["F1"]}]}
    )
    instance._observability = telemetry

    await instance.generate(selected, private_context, [private_fact])

    encoded = str(telemetry.events)
    assert private_context not in encoded
    assert private_fact.statement not in encoded
    assert str(private_fact.fact_id) not in encoded
    assert "exploration_hypothesis_generation_completed" in encoded


def test_domain_hypothesis_is_immutable_normalized_and_deduplicates_support():
    fact_id = uuid4()
    hypothesis = ExplorationHypothesis(
        exploration_company_id=uuid4(),
        statement="  A\n plausible   interpretation. ",
        fact_ids=(fact_id, fact_id),
    )
    assert hypothesis.statement == "A plausible interpretation."
    assert hypothesis.fact_ids == (fact_id,)
    with pytest.raises(ValidationError):
        hypothesis.statement = "Changed"
    with pytest.raises(ValidationError):
        ExplorationHypothesis(
            exploration_company_id=uuid4(), statement="  ", fact_ids=(fact_id,)
        )
    with pytest.raises(ValidationError):
        ExplorationHypothesis(
            exploration_company_id=uuid4(),
            statement="x" * 2_001,
            fact_ids=(fact_id,),
        )
    with pytest.raises(ValidationError):
        ExplorationHypothesis(
            exploration_company_id=uuid4(), statement="No support", fact_ids=()
        )


def test_generator_has_no_research_persistence_or_orchestration_dependencies():
    source_path = (
        Path(__file__).parents[2]
        / "src/virtual_company/services/exploration_hypothesis_generator.py"
    )
    source = source_path.read_text()
    assert "virtual_company.research" not in source
    assert "workflows.research" not in source
    assert "ExplorationHypothesisRepository" not in source
    assert "ExplorationFactRepository" not in source
    assert "ExplorationHypothesis(" in source
    assert "commit(" not in source
    assert "rollback(" not in source
