"""Grounded structured qualification-fact extraction with provider stubs."""

import asyncio
import json
from types import SimpleNamespace
from typing import TypeVar, cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from virtual_company.domain.criteria import TechnologyCriteria
from virtual_company.research.models import (
    CategoricalEvidenceFact,
    EmployeeCountEvidenceFact,
    QualificationFacts,
)
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


def campaign() -> SimpleNamespace:
    return SimpleNamespace(
        target_market="Australia",
        industry="fintech",
        technologies=TechnologyCriteria(required=["Kafka"]),
        company_size=None,
    )


def evidence(text: str, criterion: str = "technology") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), criterion=criterion, subject=None, claim=text, evidence_text=text
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
    item = evidence(wording)
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
