"""Semantic evidence extraction for deterministic company qualification."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from virtual_company.domain.criteria import CampaignForQualification, campaign_criteria
from virtual_company.llm.base import LLMProvider
from virtual_company.observability import get_observability
from virtual_company.research.models import (
    QualificationFacts,
    QualificationFactsCacheEntry,
)
from virtual_company.workflows.research.prompts import (
    EXTRACT_QUALIFICATION_FACTS_PROMPT,
    extract_qualification_facts_system_prompt,
    extract_qualification_facts_user_prompt,
)


class EvidenceForExtraction(Protocol):
    id: UUID
    criterion: str | None
    subject: str | None
    claim: str
    evidence_text: str


class QualificationEvidenceExtractor:
    """Use an LLM to state what Evidence says, never whether a company qualifies."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        concurrency: int = 3,
        timeout_seconds: float = 30,
    ) -> None:
        self._provider = provider
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout_seconds = timeout_seconds

    async def extract(
        self,
        campaign: CampaignForQualification,
        evidence: Sequence[EvidenceForExtraction],
    ) -> QualificationFactsCacheEntry:
        evidence_ids = sorted({item.id for item in evidence}, key=str)
        if not evidence_ids:
            return QualificationFactsCacheEntry(
                evidence_ids=[], facts=QualificationFacts()
            )

        criteria = [
            {
                "criterion_id": f"criterion_{index}",
                "criterion": criterion.criterion,
                "subject": criterion.subject,
            }
            for index, criterion in enumerate(campaign_criteria(campaign))
            if criterion.criterion != "company_size"
        ]
        allowed_criterion_ids = {item["criterion_id"] for item in criteria}
        allowed_evidence_ids = set(evidence_ids)
        observability = get_observability()
        metadata = {
            "prompt_name": EXTRACT_QUALIFICATION_FACTS_PROMPT.name,
            "prompt_version": EXTRACT_QUALIFICATION_FACTS_PROMPT.version,
            "evidence_count": len(evidence_ids),
        }
        try:
            async with self._semaphore, asyncio.timeout(self._timeout_seconds):
                response = await self._provider.generate_structured(
                    system_prompt=extract_qualification_facts_system_prompt(),
                    user_prompt=extract_qualification_facts_user_prompt(
                        criteria, evidence
                    ),
                    response_model=QualificationFacts,
                )
                facts = QualificationFacts.model_validate(
                    response.model_dump()
                    if isinstance(response, BaseModel)
                    else response
                )
                self._validate_references(
                    facts, allowed_criterion_ids, allowed_evidence_ids
                )
        except Exception as error:  # noqa: BLE001 - one company stays unknown
            observability.event(
                "qualification_fact_extraction_failed",
                error_type=type(error).__name__,
                outcome="unknown",
                **metadata,
            )
            return QualificationFactsCacheEntry(evidence_ids=evidence_ids, facts=None)

        observability.event(
            "qualification_facts_extracted",
            categorical_count=len(facts.categorical),
            employee_count_fact_count=len(facts.employee_counts),
            **metadata,
        )
        return QualificationFactsCacheEntry(evidence_ids=evidence_ids, facts=facts)

    @staticmethod
    def _validate_references(
        facts: QualificationFacts,
        allowed_criterion_ids: set[str],
        allowed_evidence_ids: set[UUID],
    ) -> None:
        seen_criteria: set[str] = set()
        for fact in facts.categorical:
            if fact.criterion_id not in allowed_criterion_ids:
                raise ValueError("Qualification facts reference an unknown criterion")
            if fact.criterion_id in seen_criteria:
                raise ValueError("Qualification facts duplicate a criterion")
            seen_criteria.add(fact.criterion_id)
            references = set(fact.evidence_ids)
            if not references <= allowed_evidence_ids:
                raise ValueError("Qualification facts reference unknown Evidence")
            if fact.state != "unknown" and not references:
                raise ValueError("Supported or conflicting facts require Evidence")
        for fact in facts.employee_counts:
            if not set(fact.evidence_ids) <= allowed_evidence_ids:
                raise ValueError("Employee facts reference unknown Evidence")
