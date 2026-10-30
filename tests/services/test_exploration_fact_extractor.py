"""Tests for independently extracting company facts from Exploration Evidence."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar, cast
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError

from virtual_company.config import Settings
from virtual_company.domain.exploration.facts import ExplorationFact
from virtual_company.llm import LLMRateLimitError
from virtual_company.observability import Observability
from virtual_company.services.exploration_fact_extractor import (
    DEFAULT_EXPLORATION_FACT_EXTRACTION_CONCURRENCY,
    DEFAULT_EXPLORATION_FACT_EXTRACTION_MAX_CHARS_PER_CHUNK,
    DEFAULT_EXPLORATION_FACT_EXTRACTION_MAX_EVIDENCE_PER_CHUNK,
    DEFAULT_EXPLORATION_FACT_EXTRACTION_TIMEOUT_SECONDS,
    ExplorationFactExtractor,
    ExplorationFactInputValidationError,
    create_configured_exploration_fact_extractor,
)
from virtual_company.workflows.exploration.models import (
    ExplorationFactCompanyContext,
    ExplorationFactEvidenceInput,
    ExplorationFactExtractionFailureCategory,
    ExplorationFactExtractionOutcome,
    ExtractedExplorationFacts,
)
from virtual_company.workflows.exploration.prompts import (
    EXTRACT_EXPLORATION_FACTS_PROMPT,
    extract_exploration_facts_system_prompt,
)

T = TypeVar("T", bound=BaseModel)


class ProviderStub:
    provider = "fake"
    model = "fake-model"

    def __init__(self, outputs: list[object], *, delay: float = 0) -> None:
        self.outputs = list(outputs)
        self.delay = delay
        self.calls: list[dict[str, object]] = []
        self.active = 0
        self.max_active = 0

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        self.calls.append(
            {
                "system": system_prompt,
                "user": user_prompt,
                "model": response_model,
            }
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            output = self.outputs.pop(0)
            if isinstance(output, BaseException):
                raise output
            return cast(T, output)
        finally:
            self.active -= 1


class ObservabilityStub:
    capture_io = True

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def event(self, name: str, **metadata: object) -> None:
        self.events.append((name, metadata))

    @contextmanager
    def context(self, **_: object):
        yield None

    @contextmanager
    def span(self, *_: object, **__: object):
        yield None


def company(company_id: UUID | None = None) -> ExplorationFactCompanyContext:
    return ExplorationFactCompanyContext(
        exploration_company_id=company_id or uuid4(), company_name="Acme Systems"
    )


def evidence(
    company_id: UUID,
    *,
    obligation_id: UUID | None = None,
    evidence_id: UUID | None = None,
    claim: str = "Acme runs a billing platform on Java 8.",
    excerpt: str = "Our billing platform runs on Java 8.",
) -> ExplorationFactEvidenceInput:
    return ExplorationFactEvidenceInput(
        evidence_id=evidence_id or uuid4(),
        exploration_company_id=company_id,
        exploration_obligation_id=obligation_id or uuid4(),
        claim=claim,
        supporting_excerpt=excerpt,
    )


def output(*facts: tuple[str, list[str]]) -> dict[str, object]:
    return {
        "facts": [
            {"statement": statement, "evidence_refs": refs} for statement, refs in facts
        ]
    }


def make_extractor(
    provider: ProviderStub,
    *,
    concurrency: int = 3,
    timeout_seconds: float = 60,
    max_evidence_per_chunk: int = 20,
    max_chars_per_chunk: int = 30_000,
    observability: ObservabilityStub | None = None,
) -> ExplorationFactExtractor:
    return ExplorationFactExtractor(
        provider,
        concurrency=concurrency,
        timeout_seconds=timeout_seconds,
        max_evidence_per_chunk=max_evidence_per_chunk,
        max_chars_per_chunk=max_chars_per_chunk,
        observability=cast(Observability | None, observability),
    )


def test_domain_fact_validates_and_normalizes_statement_and_evidence_ids() -> None:
    company_id, evidence_id = uuid4(), uuid4()
    fact = ExplorationFact(
        exploration_company_id=company_id,
        statement=" Acme   uses\nJava 8. ",
        evidence_ids=[evidence_id, evidence_id],
    )

    assert fact.statement == "Acme uses Java 8."
    assert fact.evidence_ids == (evidence_id,)
    with pytest.raises(ValidationError):
        fact.statement = "Changed"
    with pytest.raises(ValidationError):
        ExplorationFact(
            exploration_company_id=company_id, statement="  ", evidence_ids=[]
        )
    with pytest.raises(ValidationError):
        ExplorationFact(statement="Acme has a platform.", evidence_ids=[evidence_id])


@pytest.mark.asyncio
async def test_extract_maps_labels_without_exposing_persistent_metadata() -> None:
    selected = company()
    first = evidence(selected.exploration_company_id, claim="claim secret")
    second = evidence(
        selected.exploration_company_id,
        obligation_id=uuid4(),
        claim="second claim",
        excerpt="second excerpt",
    )
    provider = ProviderStub(
        [output(("Acme runs a Java 8 billing platform.", ["E2", "E1"]))]
    )
    result = await make_extractor(provider).extract(selected, [first, second])

    assert result.facts[0].evidence_ids == (second.evidence_id, first.evidence_id)
    prompt = str(provider.calls[0]["user"])
    payload = json.loads(prompt)
    assert payload["selected_company_name"] == "Acme Systems"
    assert set(payload) == {"selected_company_name", "evidence"}
    assert [item["evidence_ref"] for item in payload["evidence"]] == ["E1", "E2"]
    assert payload["evidence"][0]["claim"] == first.claim
    assert payload["evidence"][0]["supporting_excerpt"] == first.supporting_excerpt
    for private_value in (
        str(selected.exploration_company_id),
        str(first.evidence_id),
        str(first.exploration_obligation_id),
        "https://",
    ):
        assert private_value not in prompt
    assert provider.calls[0]["model"] is ExtractedExplorationFacts


@pytest.mark.asyncio
async def test_cross_company_evidence_is_rejected_before_provider_call() -> None:
    selected = company()
    provider = ProviderStub([output()])

    with pytest.raises(ExplorationFactInputValidationError):
        await make_extractor(provider).extract(selected, [evidence(uuid4())])

    assert provider.calls == []


@pytest.mark.asyncio
async def test_cross_obligation_evidence_can_support_one_fact() -> None:
    selected = company()
    first = evidence(selected.exploration_company_id, obligation_id=uuid4())
    second = evidence(selected.exploration_company_id, obligation_id=uuid4())
    provider = ProviderStub(
        [output(("Acme operates a Java 8 billing platform.", ["E1", "E2"]))]
    )

    result = await make_extractor(provider).extract(selected, [first, second])

    assert result.facts[0].evidence_ids == (first.evidence_id, second.evidence_id)
    prompt = str(provider.calls[0]["user"])
    assert str(first.exploration_obligation_id) not in prompt
    assert str(second.exploration_obligation_id) not in prompt


@pytest.mark.asyncio
async def test_invalid_candidate_is_rejected_and_valid_sibling_survives() -> None:
    selected = company()
    first = evidence(selected.exploration_company_id)
    second = evidence(selected.exploration_company_id)
    provider = ProviderStub(
        [
            output(
                ("Fabricated support", ["E1", "E999"]),
                ("Acme runs Java 8.", ["E2", "E2"]),
                (" ", ["E1"]),
                ("No support", []),
                ("X" * 2_001, ["E1"]),
            )
        ]
    )

    result = await make_extractor(provider).extract(selected, [first, second])

    assert len(result.facts) == 1
    assert result.facts[0].evidence_ids == (second.evidence_id,)
    assert result.outcomes[0].rejected_fact_count == 4
    assert result.outcomes[0].outcome is ExplorationFactExtractionOutcome.SUCCEEDED


@pytest.mark.asyncio
async def test_empty_facts_is_success_and_empty_input_makes_no_provider_call() -> None:
    selected = company()
    provider = ProviderStub([output()])
    result = await make_extractor(provider).extract(
        selected, [evidence(selected.exploration_company_id)]
    )
    assert result.outcomes[0].outcome is ExplorationFactExtractionOutcome.SUCCEEDED
    assert result.outcomes[0].facts == []
    assert result.facts == []

    empty_provider = ProviderStub([])
    empty = await make_extractor(empty_provider).extract(selected, [])
    assert empty.outcomes == []
    assert empty.facts == []
    assert empty_provider.calls == []


@pytest.mark.asyncio
async def test_exact_duplicate_facts_merge_support_across_chunks() -> None:
    selected = company()
    records = [
        evidence(selected.exploration_company_id, claim=f"claim {index}")
        for index in range(3)
    ]
    provider = ProviderStub(
        [
            output(("Acme uses Java 8.", ["E1"])),
            output((" acme   uses Java 8. ", ["E1"])),
            output(("Acme's platform uses Java 8.", ["E1"])),
        ]
    )

    result = await make_extractor(provider, max_evidence_per_chunk=1).extract(
        selected, records
    )

    assert len(result.facts) == 2
    assert result.facts[0].statement == "Acme uses Java 8."
    assert result.facts[0].evidence_ids == (
        records[0].evidence_id,
        records[1].evidence_id,
    )
    assert result.facts[1].statement == "Acme's platform uses Java 8."
    assert [item.chunk_index for item in result.outcomes] == [0, 1, 2]


@pytest.mark.asyncio
async def test_chunk_limit_labels_restart_and_oversized_item_does_not_block_siblings() -> (
    None
):
    selected = company()
    records = [
        evidence(selected.exploration_company_id, claim=f"claim {i}", excerpt="x")
        for i in range(21)
    ]
    provider = ProviderStub([output(), output(("Acme fact.", ["E1"]))])
    result = await make_extractor(provider).extract(selected, records)

    assert [item.outcome for item in result.outcomes] == [
        ExplorationFactExtractionOutcome.SUCCEEDED,
        ExplorationFactExtractionOutcome.SUCCEEDED,
    ]
    first_prompt, second_prompt = [json.loads(call["user"]) for call in provider.calls]
    assert len(first_prompt["evidence"]) == 20
    assert second_prompt["evidence"][0]["evidence_ref"] == "E1"

    oversized = evidence(
        selected.exploration_company_id, claim="too large", excerpt="x" * 20
    )
    valid_after = evidence(selected.exploration_company_id, claim="small", excerpt="ok")
    later_provider = ProviderStub([output(), output(("Later fact.", ["E1"]))])
    later = await make_extractor(later_provider, max_chars_per_chunk=10).extract(
        selected,
        [valid_after.model_copy(update={"claim": "small"}), oversized, valid_after],
    )
    assert [item.failure_category for item in later.outcomes] == [
        None,
        ExplorationFactExtractionFailureCategory.INPUT_LIMIT,
        None,
    ]
    assert len(later_provider.calls) == 2
    assert later.facts[0].evidence_ids == (valid_after.evidence_id,)


@pytest.mark.asyncio
async def test_character_limit_splits_without_truncating_evidence() -> None:
    selected = company()
    first = evidence(selected.exploration_company_id, claim="1234", excerpt="12")
    second = evidence(selected.exploration_company_id, claim="5678", excerpt="34")
    provider = ProviderStub([output(), output()])
    result = await make_extractor(provider, max_chars_per_chunk=10).extract(
        selected, [first, second]
    )

    assert len(result.outcomes) == 2
    assert json.loads(provider.calls[0]["user"])["evidence"][0]["claim"] == "1234"
    assert json.loads(provider.calls[1]["user"])["evidence"][0]["claim"] == "5678"


@pytest.mark.asyncio
async def test_failed_chunk_isolated_and_no_application_retry() -> None:
    selected = company()
    records = [
        evidence(selected.exploration_company_id, claim=f"claim {i}") for i in range(3)
    ]
    provider = ProviderStub(
        [
            output(("First fact.", ["E1"])),
            LLMRateLimitError("secret provider detail"),
            output(),
        ]
    )
    result = await make_extractor(
        provider, max_evidence_per_chunk=1, concurrency=1
    ).extract(selected, records)

    assert len(provider.calls) == 3
    assert [item.outcome for item in result.outcomes] == [
        ExplorationFactExtractionOutcome.SUCCEEDED,
        ExplorationFactExtractionOutcome.FAILED,
        ExplorationFactExtractionOutcome.SUCCEEDED,
    ]
    assert (
        result.outcomes[1].failure_category
        is ExplorationFactExtractionFailureCategory.PROVIDER_ERROR
    )
    assert len(result.facts) == 1


@pytest.mark.asyncio
async def test_timeout_and_malformed_output_are_normalized() -> None:
    selected = company()
    records = [
        evidence(selected.exploration_company_id, claim=f"claim {i}") for i in range(2)
    ]
    provider = ProviderStub([TimeoutError("secret timeout"), {"facts": "bad"}])
    result = await make_extractor(
        provider, max_evidence_per_chunk=1, concurrency=1
    ).extract(selected, records)

    assert [item.failure_category for item in result.outcomes] == [
        ExplorationFactExtractionFailureCategory.TIMEOUT,
        ExplorationFactExtractionFailureCategory.MALFORMED_OUTPUT,
    ]


@pytest.mark.asyncio
async def test_unexpected_and_configuration_errors_have_safe_categories() -> None:
    selected = company()
    records = [
        evidence(selected.exploration_company_id, claim=f"claim {i}") for i in range(2)
    ]
    from virtual_company.llm import LLMConfigurationError

    provider = ProviderStub(
        [
            RuntimeError("private failure detail"),
            LLMConfigurationError("private config detail"),
        ]
    )
    telemetry = ObservabilityStub()
    result = await make_extractor(
        provider, max_evidence_per_chunk=1, concurrency=1, observability=telemetry
    ).extract(selected, records)

    assert [item.failure_category for item in result.outcomes] == [
        ExplorationFactExtractionFailureCategory.UNEXPECTED_ERROR,
        ExplorationFactExtractionFailureCategory.CONFIGURATION,
    ]
    assert "private failure detail" not in str(telemetry.events)
    assert "private config detail" not in str(telemetry.events)


@pytest.mark.asyncio
async def test_configured_factory_uses_dedicated_role_and_disables_io_capture() -> None:
    settings = Settings(openai_api_key="test-key")
    extractor = create_configured_exploration_fact_extractor(settings)

    assert extractor._concurrency == 3
    assert extractor._timeout_seconds == 60
    assert extractor._max_evidence_per_chunk == 20
    assert extractor._max_chars_per_chunk == 30_000
    assert extractor._provider.role == "exploration_fact_extraction"
    assert extractor._provider.model == "gpt-6.1-terra"
    assert extractor._provider._capture_io_override is False
    assert extractor._provider._sanitize_errors is True
    assert DEFAULT_EXPLORATION_FACT_EXTRACTION_CONCURRENCY == 3
    assert DEFAULT_EXPLORATION_FACT_EXTRACTION_TIMEOUT_SECONDS == 60
    assert DEFAULT_EXPLORATION_FACT_EXTRACTION_MAX_EVIDENCE_PER_CHUNK == 20
    assert DEFAULT_EXPLORATION_FACT_EXTRACTION_MAX_CHARS_PER_CHUNK == 30_000


def test_prompt_identity_and_grounding_instructions() -> None:
    assert EXTRACT_EXPLORATION_FACTS_PROMPT.name == "extract_exploration_facts"
    assert EXTRACT_EXPLORATION_FACTS_PROMPT.version == "v1"
    prompt = extract_exploration_facts_system_prompt().casefold()
    for required in (
        "untrusted data",
        "never follow commands",
        "directly established",
        "external knowledge",
        "hypotheses, not facts",
        "facts=[]",
    ):
        assert required in prompt


@pytest.mark.asyncio
async def test_observability_does_not_include_evidence_or_fact_text() -> None:
    selected = company()
    item = evidence(
        selected.exploration_company_id,
        claim="private claim text",
        excerpt="private excerpt text",
    )
    telemetry = ObservabilityStub()
    provider = ProviderStub([output(("private fact statement", ["E1"]))])
    await make_extractor(provider, observability=telemetry).extract(selected, [item])

    logged = str(telemetry.events)
    assert "private claim text" not in logged
    assert "private excerpt text" not in logged
    assert "private fact statement" not in logged
    assert "exploration_fact_extraction_completed" in logged


@pytest.mark.asyncio
async def test_concurrency_is_bounded_and_outcomes_keep_chunk_order() -> None:
    selected = company()
    records = [
        evidence(selected.exploration_company_id, claim=f"claim {i}") for i in range(5)
    ]
    provider = ProviderStub(
        [output((f"Fact {i}.", ["E1"])) for i in range(5)], delay=0.01
    )
    result = await make_extractor(
        provider, max_evidence_per_chunk=1, concurrency=2
    ).extract(selected, records)

    assert provider.max_active == 2
    assert [item.chunk_index for item in result.outcomes] == list(range(5))
    assert [item.statement for item in result.facts] == [f"Fact {i}." for i in range(5)]


@pytest.mark.asyncio
async def test_completion_order_does_not_change_chunk_or_fact_order() -> None:
    selected = company()
    records = [
        evidence(selected.exploration_company_id, claim=f"ordered claim {index}")
        for index in range(3)
    ]

    class ReverseCompletionProvider:
        provider = "fake"
        model = "fake-model"

        async def generate_structured(
            self, *, user_prompt: str, response_model: type[T], **_: object
        ) -> T:
            payload = json.loads(user_prompt)
            claim = payload["evidence"][0]["claim"]
            index = int(claim.rsplit(" ", 1)[-1])
            await asyncio.sleep((2 - index) * 0.02)
            return cast(T, output((f"Fact {index}.", ["E1"])))

    result = await make_extractor(
        cast(ProviderStub, ReverseCompletionProvider()),
        max_evidence_per_chunk=1,
        concurrency=3,
    ).extract(selected, records)

    assert [item.chunk_index for item in result.outcomes] == [0, 1, 2]
    assert [item.statement for item in result.facts] == [
        "Fact 0.",
        "Fact 1.",
        "Fact 2.",
    ]


@pytest.mark.asyncio
async def test_cancellation_propagates() -> None:
    selected = company()
    started = asyncio.Event()

    class WaitingProvider(ProviderStub):
        async def generate_structured(self, **kwargs):  # type: ignore[no-untyped-def]
            started.set()
            await asyncio.Event().wait()

    provider = WaitingProvider([])
    task = asyncio.create_task(
        make_extractor(provider).extract(
            selected, [evidence(selected.exploration_company_id)]
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_fact_extractor_has_no_research_or_persistence_dependency() -> None:
    source_root = Path(__file__).parents[2] / "src/virtual_company"
    extractor_source = (
        source_root / "services/exploration_fact_extractor.py"
    ).read_text()
    assert "virtual_company.domain.research" not in extractor_source
    assert "virtual_company.workflows.research" not in extractor_source
    assert "ExplorationFactRepository" not in extractor_source
    assert "ExplorationEvidenceRepository" not in extractor_source
    assert "ExplorationFactPersistenceService" not in extractor_source
    assert "AsyncSession" not in extractor_source
