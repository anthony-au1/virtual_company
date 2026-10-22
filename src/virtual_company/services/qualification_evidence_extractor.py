"""Semantic evidence extraction for deterministic company qualification."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from virtual_company.domain.criteria import (
    CampaignCriterion,
    CampaignForQualification,
    campaign_criteria,
    normalize_subject,
)
from virtual_company.domain.research import QualificationFacts
from virtual_company.llm.base import LLMProvider
from virtual_company.workflows.research.models import (
    QualificationFactsCacheEntry,
    QualificationFactsCacheStatus,
)
from virtual_company.workflows.research.observability.qualification import (
    QualificationObservability,
)
from virtual_company.workflows.research.prompts import (
    extract_qualification_facts_system_prompt,
    extract_qualification_facts_user_prompt,
)


class ResearchEvidenceForExtraction(Protocol):
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
        observability: QualificationObservability | None = None,
    ) -> None:
        self._provider = provider
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout_seconds = timeout_seconds
        self._observability = observability or QualificationObservability()

    async def extract(
        self,
        campaign: CampaignForQualification,
        evidence: Sequence[ResearchEvidenceForExtraction],
        *,
        previous_entry: QualificationFactsCacheEntry | None = None,
        target_criterion_ids: set[str] | None = None,
        research_run_id: UUID | None = None,
        company_id: UUID | None = None,
        company_name: str | None = None,
        evaluation_stage: str = "intermediate",
        investigation_round: int | None = None,
    ) -> QualificationFactsCacheEntry:
        evidence_ids = sorted({item.id for item in evidence}, key=str)
        same_evidence = (
            previous_entry is not None and previous_entry.evidence_ids == evidence_ids
        )
        previous_attempts = (
            previous_entry.attempt_count
            if same_evidence
            and previous_entry.status
            in {
                QualificationFactsCacheStatus.FAILED_RETRYABLE,
                QualificationFactsCacheStatus.FAILED_EXHAUSTED,
            }
            else 0
        )
        if previous_attempts >= 2:
            return previous_entry
        attempt_number = previous_attempts + 1
        if not evidence_ids:
            return QualificationFactsCacheEntry(
                evidence_ids=[],
                facts=(
                    previous_entry.facts
                    if previous_entry is not None and previous_entry.facts is not None
                    else QualificationFacts()
                ),
                status=QualificationFactsCacheStatus.SUCCESS,
                attempt_count=0,
                provenance_by_criterion=(
                    previous_entry.provenance_by_criterion
                    if previous_entry is not None
                    else {}
                ),
            )

        configured_criteria = campaign_criteria(campaign)
        if target_criterion_ids is not None and not target_criterion_ids:
            return QualificationFactsCacheEntry(
                evidence_ids=evidence_ids,
                facts=(
                    previous_entry.facts
                    if previous_entry is not None and previous_entry.facts is not None
                    else QualificationFacts()
                ),
                status=QualificationFactsCacheStatus.SUCCESS,
                attempt_count=max(
                    previous_entry.attempt_count if previous_entry is not None else 0,
                    1,
                ),
                provenance_by_criterion=(
                    previous_entry.provenance_by_criterion
                    if previous_entry is not None
                    else {}
                ),
            )
        extractable_criteria = [
            (index, criterion)
            for index, criterion in enumerate(configured_criteria)
            if criterion.criterion != "company_size"
            and (
                target_criterion_ids is None
                or f"criterion_{index}" in target_criterion_ids
            )
        ]
        include_company_size = target_criterion_ids is None or any(
            criterion.criterion == "company_size"
            and f"criterion_{index}" in target_criterion_ids
            for index, criterion in enumerate(configured_criteria)
        )
        prompt_evidence = (
            evidence
            if include_company_size
            else [item for item in evidence if item.criterion != "company_size"]
        )
        criteria = [
            {
                "criterion_id": f"criterion_{index}",
                "criterion": criterion.criterion,
                "subject": criterion.subject,
            }
            for index, criterion in extractable_criteria
        ]
        criterion_by_id = {
            f"criterion_{index}": criterion for index, criterion in extractable_criteria
        }
        allowed_evidence_ids = set(evidence_ids)
        evidence_by_id = {item.id: item for item in evidence}
        criterion_ids = [
            f"criterion_{index}"
            for index, criterion in enumerate(configured_criteria)
            if target_criterion_ids is None
            or f"criterion_{index}" in target_criterion_ids
        ]
        metadata = self._observability.extraction_metadata(
            evidence_ids=evidence_ids,
            prompt_evidence_ids=[item.id for item in prompt_evidence],
            criterion_ids=criterion_ids,
            research_run_id=research_run_id,
            company_id=company_id,
            company_name=company_name,
            evaluation_stage=evaluation_stage,
            investigation_round=investigation_round,
            model=str(getattr(self._provider, "model", "unknown")),
        )
        if attempt_number > 1:
            self._observability.record_extraction_retry(
                attempt_number=attempt_number,
                metadata=metadata,
            )
        try:
            with self._observability.context(**metadata):
                async with self._semaphore, asyncio.timeout(self._timeout_seconds):
                    response = await self._provider.generate_structured(
                        system_prompt=extract_qualification_facts_system_prompt(),
                        user_prompt=extract_qualification_facts_user_prompt(
                            criteria, prompt_evidence
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
            status = (
                QualificationFactsCacheStatus.FAILED_RETRYABLE
                if attempt_number < 2
                else QualificationFactsCacheStatus.FAILED_EXHAUSTED
            )
            self._observability.record_extraction_failure(
                error=error,
                status=status,
                attempt_number=attempt_number,
                metadata=metadata,
            )
            return QualificationFactsCacheEntry(
                evidence_ids=evidence_ids,
                facts=(previous_entry.facts if previous_entry is not None else None),
                status=status,
                attempt_count=attempt_number,
                provenance_by_criterion=(
                    previous_entry.provenance_by_criterion
                    if previous_entry is not None
                    else {}
                ),
            )

        provenance = (
            dict(previous_entry.provenance_by_criterion)
            if previous_entry is not None
            else {}
        )
        provenance.update(
            self._observability.extraction_provenance(
                evaluation_stage=evaluation_stage,
                investigation_round=investigation_round,
                prompt_evidence_ids=[item.id for item in prompt_evidence],
                model=str(getattr(self._provider, "model", "unknown")),
                criterion_ids=criterion_ids,
            )
        )
        self._observability.record_extracted_facts(
            facts=facts,
            attempt_number=attempt_number,
            metadata=metadata,
        )
        return QualificationFactsCacheEntry(
            evidence_ids=evidence_ids,
            facts=facts,
            status=QualificationFactsCacheStatus.SUCCESS,
            attempt_count=attempt_number,
            provenance_by_criterion=provenance,
        )

    @staticmethod
    def _validate_references(
        facts: QualificationFacts,
        criteria_by_id: dict[str, CampaignCriterion],
        evidence_by_id: dict[UUID, ResearchEvidenceForExtraction],
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
        evidence: ResearchEvidenceForExtraction, criterion: CampaignCriterion
    ) -> bool:
        if evidence.criterion != criterion.criterion:
            return False
        if criterion.criterion != "keyword":
            return normalize_subject(criterion.criterion, criterion.subject) == (
                normalize_subject(criterion.criterion, evidence.subject)
            )
        expected = normalize_subject("keyword", criterion.subject)
        observed = normalize_subject("keyword", evidence.subject)
        return expected == observed
