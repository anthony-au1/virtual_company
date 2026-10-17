"""Qualification telemetry and provenance formatting for Research runs."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any
from uuid import UUID

from virtual_company.domain.qualification import (
    QualificationStatus,
    ResearchCompanyQualification,
)
from virtual_company.observability import Observability, get_observability
from virtual_company.research.models import (
    QualificationFacts,
    QualificationFactsCacheEntry,
    QualificationFactsCacheStatus,
)
from virtual_company.workflows.research.prompts import (
    EXTRACT_QUALIFICATION_FACTS_PROMPT,
)


class QualificationObservability:
    """Format and emit qualification telemetry without making decisions."""

    def __init__(self, observability: Observability | None = None) -> None:
        self._observability = observability or get_observability()

    def context(self, **values: str | None) -> AbstractContextManager[None]:
        return self._observability.context(**values)

    @staticmethod
    def extraction_metadata(
        *,
        evidence_ids: list[UUID],
        prompt_evidence_ids: list[UUID],
        criterion_ids: list[str],
        research_run_id: UUID | None,
        company_id: UUID | None,
        company_name: str | None,
        evaluation_stage: str,
        investigation_round: int | None,
        model: str,
    ) -> dict[str, Any]:
        return {
            "prompt_name": EXTRACT_QUALIFICATION_FACTS_PROMPT.name,
            "prompt_version": EXTRACT_QUALIFICATION_FACTS_PROMPT.version,
            "evidence_count": len(evidence_ids),
            "research_run_id": str(research_run_id) if research_run_id else None,
            "company_id": str(company_id) if company_id else None,
            "company_name": company_name,
            "workflow_stage": "qualification_fact_extraction",
            "evaluation_stage": evaluation_stage,
            "investigation_round": investigation_round,
            "criterion_ids": criterion_ids,
            "input_evidence_ids": [str(item) for item in prompt_evidence_ids],
            "model": model,
        }

    def record_extraction_retry(
        self, *, attempt_number: int, metadata: dict[str, Any]
    ) -> None:
        self._observability.event(
            "qualification_fact_extraction_retry",
            attempt_number=attempt_number,
            **metadata,
        )

    def record_extraction_failure(
        self,
        *,
        error: Exception,
        status: QualificationFactsCacheStatus,
        attempt_number: int,
        metadata: dict[str, Any],
    ) -> None:
        self._observability.event(
            "qualification_fact_extraction_failed",
            error_type=type(error).__name__,
            outcome=status.value,
            attempt_number=attempt_number,
            retry_remaining=attempt_number < 2,
            retry_exhausted=attempt_number >= 2,
            **metadata,
        )

    def record_extracted_facts(
        self,
        *,
        facts: QualificationFacts,
        attempt_number: int,
        metadata: dict[str, Any],
    ) -> None:
        self._observability.event(
            "qualification_facts_extracted",
            categorical_count=len(facts.categorical),
            employee_count_fact_count=len(facts.employee_counts),
            attempt_number=attempt_number,
            **metadata,
        )
        with self._observability.context(**metadata):
            for fact in facts.categorical:
                self._observability.event(
                    "qualification_fact_extracted",
                    criterion_id=fact.criterion_id,
                    fact_state=fact.state,
                    evidence_ids=[str(value) for value in fact.evidence_ids],
                )
            for fact in facts.employee_counts:
                self._observability.event(
                    "qualification_employee_count_fact_extracted",
                    value=fact.value,
                    relation=fact.relation,
                    year=fact.year,
                    scope=fact.scope,
                    evidence_ids=[str(value) for value in fact.evidence_ids],
                )

    @staticmethod
    def extraction_provenance(
        *,
        evaluation_stage: str,
        investigation_round: int | None,
        prompt_evidence_ids: list[UUID],
        model: str,
        criterion_ids: list[str],
    ) -> dict[str, dict[str, object]]:
        entry: dict[str, object] = {
            "prompt_name": EXTRACT_QUALIFICATION_FACTS_PROMPT.name,
            "prompt_version": EXTRACT_QUALIFICATION_FACTS_PROMPT.version,
            "model": model,
            "evaluation_stage": evaluation_stage,
            "investigation_round": str(investigation_round or ""),
            "input_evidence_ids": [str(item) for item in prompt_evidence_ids],
        }
        return {criterion_id: entry for criterion_id in criterion_ids}

    @staticmethod
    def final_provenance(
        facts_entry: QualificationFactsCacheEntry,
        source_search_observability: dict[str, object],
    ) -> dict[str, object]:
        return {
            "evaluation_stage": "final",
            "available_evidence_ids": [
                str(value) for value in facts_entry.evidence_ids
            ],
            "qualification_facts": (
                facts_entry.facts.model_dump(mode="json")
                if facts_entry.facts is not None
                else None
            ),
            "fact_extraction_by_criterion": facts_entry.provenance_by_criterion,
            "source_search_observability": source_search_observability,
        }

    def record_final_evaluation(
        self,
        *,
        research_run_id: UUID,
        result: ResearchCompanyQualification,
        facts_entry: QualificationFactsCacheEntry,
        company_name: str,
    ) -> None:
        metadata = {
            "company_id": str(result.company_id),
            "company_name": company_name,
            "qualification_status": result.status.value,
            "criteria_total": len(result.criteria),
            "criteria_match": sum(
                item.status is QualificationStatus.MATCH for item in result.criteria
            ),
            "criteria_mismatch": sum(
                item.status is QualificationStatus.MISMATCH for item in result.criteria
            ),
            "criteria_unknown": sum(
                item.status is QualificationStatus.UNKNOWN for item in result.criteria
            ),
        }
        with (
            self._observability.context(
                research_run_id=str(research_run_id),
                company_id=str(result.company_id),
                company_name=company_name,
                workflow_stage="final_company_qualification",
                evaluation_stage="final",
            ),
            self._observability.span("company_qualification", **metadata),
        ):
            for index, item in enumerate(result.criteria):
                criterion_id = f"criterion_{index}"
                fact = next(
                    (
                        value
                        for value in (
                            facts_entry.facts.categorical if facts_entry.facts else []
                        )
                        if value.criterion_id == criterion_id
                    ),
                    None,
                )
                if item.criterion == "company_size":
                    fact_output = {
                        "employee_counts": [
                            value.model_dump(mode="json")
                            for value in (
                                facts_entry.facts.employee_counts
                                if facts_entry.facts
                                else []
                            )
                        ]
                    }
                else:
                    fact_output = fact.model_dump(mode="json") if fact else None
                criterion_provenance = facts_entry.provenance_by_criterion.get(
                    criterion_id
                )
                self._observability.event(
                    "research_criterion_evaluated",
                    criterion=item.criterion,
                    subject=item.subject,
                    criterion_id=criterion_id,
                    result=item.status.value,
                    reason=item.reason[:300],
                    evidence_ids=[str(value) for value in item.evidence_ids],
                    evaluation_evidence_ids=(
                        (criterion_provenance or {}).get("input_evidence_ids", [])
                    ),
                    qualification_fact=fact_output,
                    extraction_provenance=criterion_provenance,
                    model=(criterion_provenance or {}).get("model"),
                    prompt_name=EXTRACT_QUALIFICATION_FACTS_PROMPT.name,
                    prompt_version=EXTRACT_QUALIFICATION_FACTS_PROMPT.version,
                )
            self._observability.event(
                "research_company_qualification_finalized",
                **metadata,
                matched_criteria=[
                    self._criterion_label(item)
                    for item in result.criteria
                    if item.status is QualificationStatus.MATCH
                ],
                mismatched_criteria=[
                    self._criterion_label(item)
                    for item in result.criteria
                    if item.status is QualificationStatus.MISMATCH
                ],
                unknown_criteria=[
                    self._criterion_label(item)
                    for item in result.criteria
                    if item.status is QualificationStatus.UNKNOWN
                ],
            )
            self._observability.event("company_qualified", **metadata)

    @staticmethod
    def _criterion_label(criterion: Any) -> str:
        return (
            f"{criterion.criterion}:{criterion.subject}"
            if criterion.subject
            else criterion.criterion
        )
