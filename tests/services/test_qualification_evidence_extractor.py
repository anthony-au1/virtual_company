"""Grounded structured qualification-fact extraction with provider stubs."""

import asyncio
import json
from types import SimpleNamespace
from typing import TypeVar, cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from virtual_company.domain.criteria import (
    CompanySizeBound,
    CompanySizeCriteria,
    CriterionRequirement,
    TechnologyCriteria,
)
from virtual_company.domain.qualification import QualificationStatus
from virtual_company.research.models import (
    CategoricalEvidenceFact,
    EmployeeCountEvidenceFact,
    QualificationFacts,
    QualificationFactsCacheStatus,
)
from virtual_company.services.qualification import qualify_company
from virtual_company.services.qualification_evidence_extractor import (
    QualificationEvidenceExtractor,
)

T = TypeVar("T", bound=BaseModel)


class ProviderStub:
    def __init__(self, output: object, delay: float = 0) -> None:
        self.output = output
        self.delay = delay
        self.calls: list[dict[str, object]] = []
        self.active = 0
        self.max_active = 0

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_model: type[T]
    ) -> T:
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "model": response_model}
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            if isinstance(self.output, BaseException):
                raise self.output
            return cast(T, self.output)
        finally:
            self.active -= 1


class ProviderSequence:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_model: type[T]
    ) -> T:
        self.calls += 1
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return cast(T, output)


def campaign(technologies: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        target_market="Australia",
        industry="fintech",
        technologies=TechnologyCriteria(required=technologies or ["Kafka"]),
        company_size=None,
    )


def evidence(
    text: str,
    criterion: str = "technology",
    subject: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        criterion=criterion,
        subject=subject,
        claim=text,
        evidence_text=text,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wording,criterion_id",
    [
        ("Kafka-based event streaming platform", "criterion_2"),
        ("large-scale distributed event processing infrastructure", "criterion_2"),
        ("digital payments provider", "criterion_1"),
        ("transaction processing company", "criterion_1"),
    ],
)
async def test_different_wording_reaches_the_same_semantic_schema(
    wording: str, criterion_id: str
) -> None:
    criterion = "technology" if criterion_id == "criterion_2" else "industry"
    subject = "Kafka" if criterion == "technology" else "fintech"
    item = evidence(wording, criterion, subject)
    output = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id=criterion_id, state="supported", evidence_ids=[item.id]
            )
        ]
    )
    provider = ProviderStub(output)
    result = await QualificationEvidenceExtractor(provider).extract(campaign(), [item])
    assert result.facts == output
    assert wording in str(provider.calls[0]["user"])
    assert provider.calls[0]["model"] is QualificationFacts
    assert "semantic meaning" in str(provider.calls[0]["system"])


@pytest.mark.asyncio
async def test_explicit_and_vague_size_are_not_strengthened() -> None:
    explicit = evidence("employs approximately 1,500 people", "company_size")
    vague = evidence("a global technology company", "company_size")
    output = QualificationFacts(
        employee_counts=[
            EmployeeCountEvidenceFact(
                value=1500,
                relation="approximately",
                scope="unknown",
                evidence_ids=[explicit.id],
            )
        ]
    )
    result = await QualificationEvidenceExtractor(ProviderStub(output)).extract(
        campaign(), [explicit, vague]
    )
    assert result.facts == output
    assert not any(vague.id in fact.evidence_ids for fact in output.employee_counts)


@pytest.mark.asyncio
async def test_wrong_technology_evidence_is_downgraded_to_unknown() -> None:
    java = evidence("Our backend uses Java", subject="Java")
    output = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id="criterion_2", state="supported", evidence_ids=[java.id]
            )
        ]
    )
    result = await QualificationEvidenceExtractor(ProviderStub(output)).extract(
        campaign(["Spring"]), [java]
    )
    assert result.facts is not None
    assert result.facts.categorical[0].state == "unknown"
    assert result.facts.categorical[0].evidence_ids == []


@pytest.mark.asyncio
async def test_matching_and_directional_technology_implication_are_admissible() -> None:
    spring = evidence("Spring services", subject="Spring")
    spring_boot = evidence("Spring Boot services", subject="Spring Boot")
    for item in (spring, spring_boot):
        output = QualificationFacts(
            categorical=[
                CategoricalEvidenceFact(
                    criterion_id="criterion_2",
                    state="supported",
                    evidence_ids=[item.id],
                )
            ]
        )
        result = await QualificationEvidenceExtractor(ProviderStub(output)).extract(
            campaign(["Spring"]), [item]
        )
        assert result.facts == output

    spring_only = evidence("Spring framework", subject="Spring")
    reverse_output = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id="criterion_2",
                state="supported",
                evidence_ids=[spring_only.id],
            )
        ]
    )
    reverse = await QualificationEvidenceExtractor(ProviderStub(reverse_output)).extract(
        campaign(["Spring Boot"]), [spring_only]
    )
    assert reverse.facts is not None
    assert reverse.facts.categorical[0].state == "unknown"


@pytest.mark.asyncio
async def test_shared_multi_technology_excerpt_can_support_both_criteria() -> None:
    shared = evidence(
        "Our services are built using Java and Spring Boot.", subject="Java"
    )
    output = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id="criterion_2", state="supported", evidence_ids=[shared.id]
            ),
            CategoricalEvidenceFact(
                criterion_id="criterion_3", state="supported", evidence_ids=[shared.id]
            ),
        ]
    )
    result = await QualificationEvidenceExtractor(ProviderStub(output)).extract(
        campaign(["Java", "Spring"]), [shared]
    )
    assert result.facts == output


@pytest.mark.asyncio
async def test_technology_evidence_cannot_support_employee_count() -> None:
    technology = evidence("Uses Kafka", subject="Kafka")
    output = QualificationFacts(
        employee_counts=[
            EmployeeCountEvidenceFact(
                value=1500, relation="exact", evidence_ids=[technology.id]
            )
        ]
    )
    result = await QualificationEvidenceExtractor(ProviderStub(output)).extract(
        campaign(), [technology]
    )
    assert result.facts == QualificationFacts()
    size_campaign = campaign()
    size_campaign.company_size = CompanySizeCriteria(
        min=CompanySizeBound(value=1000, requirement=CriterionRequirement.REQUIRED)
    )
    assert qualify_company(size_campaign, result.facts)[-1].status is QualificationStatus.UNKNOWN


@pytest.mark.asyncio
async def test_invalid_fact_does_not_discard_a_valid_fact() -> None:
    java = evidence("Our backend uses Java", subject="Java")
    output = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id="criterion_2", state="supported", evidence_ids=[java.id]
            ),
            CategoricalEvidenceFact(
                criterion_id="criterion_3", state="supported", evidence_ids=[java.id]
            ),
        ]
    )
    result = await QualificationEvidenceExtractor(ProviderStub(output)).extract(
        campaign(["Java", "Spring"]), [java]
    )
    assert result.facts is not None
    assert result.facts.categorical[0].state == "supported"
    assert result.facts.categorical[1].state == "unknown"


@pytest.mark.asyncio
async def test_operational_extraction_failure_retries_once_for_same_evidence() -> None:
    item = evidence("Kafka services", subject="Kafka")
    output = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id="criterion_2", state="supported", evidence_ids=[item.id]
            )
        ]
    )
    provider = ProviderSequence([RuntimeError("temporary provider error"), output])
    extractor = QualificationEvidenceExtractor(provider)
    first = await extractor.extract(campaign(), [item])
    assert first.status is QualificationFactsCacheStatus.FAILED_RETRYABLE
    assert first.attempt_count == 1 and first.facts is None

    second = await extractor.extract(campaign(), [item], previous_entry=first)
    assert second.status is QualificationFactsCacheStatus.SUCCESS
    assert second.attempt_count == 2 and second.facts == output
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_operational_extraction_failure_exhausts_after_one_retry() -> None:
    item = evidence("Kafka services", subject="Kafka")
    provider = ProviderSequence(
        [RuntimeError("first failure"), RuntimeError("second failure"), QualificationFacts()]
    )
    extractor = QualificationEvidenceExtractor(provider)
    first = await extractor.extract(campaign(), [item])
    second = await extractor.extract(campaign(), [item], previous_entry=first)
    third = await extractor.extract(campaign(), [item], previous_entry=second)
    assert first.status is QualificationFactsCacheStatus.FAILED_RETRYABLE
    assert second.status is QualificationFactsCacheStatus.FAILED_EXHAUSTED
    assert second.attempt_count == 2 and second.facts is None
    assert third == second
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_successful_semantic_unknown_and_task1_downgrade_are_cached_as_success() -> None:
    java = evidence("Our backend uses Java", subject="Java")
    unsupported_spring = QualificationFacts(
        categorical=[
            CategoricalEvidenceFact(
                criterion_id="criterion_2",
                state="supported",
                evidence_ids=[java.id],
            )
        ]
    )
    provider = ProviderSequence([QualificationFacts(), unsupported_spring])
    extractor = QualificationEvidenceExtractor(provider)
    unknown = await extractor.extract(campaign(["Kafka"]), [java])
    assert unknown.status is QualificationFactsCacheStatus.SUCCESS
    assert unknown.facts == QualificationFacts()

    downgraded = await extractor.extract(campaign(["Spring"]), [java])
    assert downgraded.status is QualificationFactsCacheStatus.SUCCESS
    assert downgraded.facts is not None
    assert downgraded.facts.categorical[0].state == "unknown"
    assert provider.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [
        RuntimeError("unavailable"),
        {
            "categorical": [
                {
                    "criterion_id": "criterion_99",
                    "state": "supported",
                    "evidence_ids": [],
                }
            ]
        },
        {
            "categorical": [],
            "employee_counts": [
                {"value": 5, "relation": "exact", "evidence_ids": [str(uuid4())]}
            ],
        },
    ],
)
async def test_failures_and_invalid_references_become_unknown(output: object) -> None:
    item = evidence("some evidence")
    result = await QualificationEvidenceExtractor(ProviderStub(output)).extract(
        campaign(), [item]
    )
    assert result.facts is None
    assert result.evidence_ids == [item.id]


@pytest.mark.asyncio
async def test_empty_evidence_skips_provider_and_concurrency_is_bounded() -> None:
    provider = ProviderStub(QualificationFacts(), delay=0.001)
    extractor = QualificationEvidenceExtractor(provider, concurrency=2)
    empty = await extractor.extract(campaign(), [])
    assert empty.facts == QualificationFacts()
    assert not provider.calls
    await asyncio.gather(
        *(extractor.extract(campaign(), [evidence(str(index))]) for index in range(5))
    )
    assert provider.max_active == 2


def test_schema_rejects_decisions_and_invalid_employee_values() -> None:
    with pytest.raises(ValidationError):
        QualificationFacts.model_validate(
            {"categorical": [], "employee_counts": [], "decision": "MATCH"}
        )
    with pytest.raises(ValidationError):
        QualificationFacts.model_validate(
            {
                "employee_counts": [
                    {"value": -1, "relation": "exact", "evidence_ids": [str(uuid4())]}
                ]
            }
        )


def test_prompt_contains_only_compact_evidence_and_criteria() -> None:
    # Guard the serialized wire shape independently of a live provider.
    from virtual_company.workflows.research.prompts import (
        extract_qualification_facts_user_prompt,
    )

    item = evidence("payments platform")
    payload = json.loads(
        extract_qualification_facts_user_prompt(
            [
                {
                    "criterion_id": "criterion_1",
                    "criterion": "industry",
                    "subject": "fintech",
                }
            ],
            [item],
        )
    )
    assert payload["evidence"][0]["id"] == str(item.id)
    assert "source_url" not in payload["evidence"][0]
