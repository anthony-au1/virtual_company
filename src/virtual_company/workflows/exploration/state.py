"""Typed, transient state for the Exploration LangGraph workflow."""

from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from virtual_company.domain.exploration.run import ExplorationRunStatus
from virtual_company.services.exploration_evidence_extractor import (
    ExplorationEvidenceExtractionBatchResult,
)
from virtual_company.services.exploration_fetch import ExplorationFetchBatchResult
from virtual_company.services.exploration_hypothesis_generator import (
    ExplorationHypothesisGenerationResult,
)
from virtual_company.services.exploration_query_generator import (
    ExplorationQueryGenerationResult,
)
from virtual_company.services.exploration_search import ExplorationSearchBatchResult
from virtual_company.workflows.exploration.models import (
    ExplorationFactCompanyContext,
    ExplorationFactEvidenceInput,
    ExplorationFactExtractionBatchResult,
    ExplorationHypothesisCompanyContext,
    ExplorationHypothesisFactInput,
)


class ExplorationCompanySnapshot(BaseModel):
    """Detached company identity/profile copied from Research persistence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exploration_company_id: UUID
    research_company_id: UUID
    name: str
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None


class ExplorationObligationSnapshot(BaseModel):
    """Detached Obligation used for one company investigation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    description: str


class ExplorationWorkflowState(TypedDict, total=False):
    """Values passed between Exploration graph nodes; never ORM entities."""

    exploration_run_id: UUID
    workflow_execution_id: UUID
    exploration_id: UUID
    research_run_id: UUID
    business_context: str
    companies: tuple[ExplorationCompanySnapshot, ...]
    obligations: tuple[ExplorationObligationSnapshot, ...]
    company_index: int
    obligation_index: int
    current_company: ExplorationCompanySnapshot | None
    current_obligation: ExplorationObligationSnapshot | None
    query_result: ExplorationQueryGenerationResult | None
    search_result: ExplorationSearchBatchResult | None
    fetch_result: ExplorationFetchBatchResult | None
    evidence_result: ExplorationEvidenceExtractionBatchResult | None
    company_evidence: tuple[ExplorationFactEvidenceInput, ...]
    fact_context: ExplorationFactCompanyContext | None
    fact_result: ExplorationFactExtractionBatchResult | None
    company_facts: tuple[ExplorationHypothesisFactInput, ...]
    hypothesis_context: ExplorationHypothesisCompanyContext | None
    hypothesis_result: ExplorationHypothesisGenerationResult | None
    evidence_persisted_count: int
    facts_persisted_count: int
    hypotheses_persisted_count: int
    completed_company_obligation_count: int
    recoverable_failure_count: int
    failure_categories: tuple[str, ...]
    final_status: ExplorationRunStatus | None


class ExplorationWorkflowResult(BaseModel):
    """Immutable public outcome of a completed or partially completed run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exploration_run_id: UUID
    status: ExplorationRunStatus
    selected_company_count: int
    obligation_count: int
    completed_company_obligation_count: int
    evidence_persisted_count: int
    facts_persisted_count: int
    hypotheses_persisted_count: int
    recoverable_failure_count: int
    failure_categories: tuple[str, ...]
    duration_ms: int
