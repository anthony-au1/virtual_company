"""Semantic evidence extraction for deterministic company qualification."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from virtual_company.domain.criteria import (
    CampaignCriterion,
    CampaignForQualification,
    campaign_criteria,
    normalize_subject,
    technology_subjects,
)
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

        configured_criteria = campaign_criteria(campaign)
        extractable_criteria = [
            (index, criterion)
            for index, criterion in enumerate(configured_criteria)
            if criterion.criterion != "company_size"
        ]
        criteria = [
            {
                "criterion_id": f"criterion_{index}",
                "criterion": criterion.criterion,
                "subject": criterion.subject,
            }
            for index, criterion in extractable_criteria
        ]
        criterion_by_id = {
            f"criterion_{index}": criterion
            for index, criterion in extractable_criteria
        }
        allowed_evidence_ids = set(evidence_ids)
        evidence_by_id = {item.id: item for item in evidence}
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
                facts = self._validate_references(
                    facts, criterion_by_id, evidence_by_id, allowed_evidence_ids
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
        criteria_by_id: dict[str, CampaignCriterion],
        evidence_by_id: dict[UUID, EvidenceForExtraction],
        allowed_evidence_ids: set[UUID],
    ) -> QualificationFacts:
        categorical = []
        seen_criteria: set[str] = set()
        for fact in facts.categorical:
            criterion = criteria_by_id.get(fact.criterion_id)
            if criterion is None:
                raise ValueError("Qualification facts reference an unknown criterion")
            if fact.criterion_id in seen_criteria:
                raise ValueError("Qualification facts duplicate a criterion")
            seen_criteria.add(fact.criterion_id)
            references = set(fact.evidence_ids)
            if not references <= allowed_evidence_ids:
                raise ValueError("Qualification facts reference unknown Evidence")
            admissible = {
                evidence_id
                for evidence_id in references
                if QualificationEvidenceExtractor._evidence_supports_criterion(
                    evidence_by_id[evidence_id], criterion
                )
            }
            if fact.state != "unknown" and not admissible:
                categorical.append(
                    fact.model_copy(update={"state": "unknown", "evidence_ids": []})
                )
            else:
                categorical.append(
                    fact.model_copy(
                        update={"evidence_ids": sorted(admissible, key=str)}
                    )
                )
        employee_counts = []
        for fact in facts.employee_counts:
            references = set(fact.evidence_ids)
            if not references <= allowed_evidence_ids:
                raise ValueError("Employee facts reference unknown Evidence")
            admissible = sorted(
                (
                    evidence_id
                    for evidence_id in references
                    if evidence_by_id[evidence_id].criterion == "company_size"
                ),
                key=str,
            )
            if admissible:
                employee_counts.append(
                    fact.model_copy(update={"evidence_ids": admissible})
                )
        return QualificationFacts(
            categorical=categorical, employee_counts=employee_counts
        )

    @staticmethod
    def _evidence_supports_criterion(
        evidence: EvidenceForExtraction, criterion: CampaignCriterion
    ) -> bool:
        if evidence.criterion != criterion.criterion:
            return False
        if criterion.criterion != "technology":
            return normalize_subject(criterion.criterion, criterion.subject) == (
                normalize_subject(criterion.criterion, evidence.subject)
            )
        expected = normalize_subject("technology", criterion.subject)
        observed = normalize_subject("technology", evidence.subject)
        return expected in technology_subjects(observed) or (
            QualificationEvidenceExtractor._technology_is_named(
                expected, f"{evidence.claim} {evidence.evidence_text}"
            )
        )

    @staticmethod
    def _technology_is_named(technology: str, text: str) -> bool:
        words = technology.split()
        if not words:
            return False
        pattern = r"(?<!\w)" + r"[\W_]+".join(map(re.escape, words)) + r"(?!\w)"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
