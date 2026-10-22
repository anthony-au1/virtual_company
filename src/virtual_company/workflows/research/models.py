"""Workflow-only data models for campaign research."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from virtual_company.domain.research.criteria import (
    CompanySizeCriteria,
    EvidenceCriterion,
)
from virtual_company.domain.research.discovery import DiscoveredCompany
from virtual_company.domain.research.facts import QualificationFacts
from virtual_company.tools.web_search import SearchResult

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ExtractedEvidence(BaseModel):
    """Research page-scoped extraction output before source validation."""

    criterion: EvidenceCriterion
    subject: str | None = None
    claim: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)


class ExtractedEvidenceItems(BaseModel):
    """Structured output from one Research page-scoped extraction call."""

    evidence: list[ExtractedEvidence] = Field(default_factory=list)


class QualificationFactsCacheStatus(StrEnum):
    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_EXHAUSTED = "failed_exhausted"


class QualificationFactsCacheEntry(BaseModel):
    """Research workflow cache state and the latest Evidence set used."""

    model_config = ConfigDict(extra="forbid")

    evidence_ids: list[UUID]
    facts: QualificationFacts | None
    status: QualificationFactsCacheStatus = QualificationFactsCacheStatus.SUCCESS
    attempt_count: int = Field(default=1, ge=0, le=2)
    provenance_by_criterion: dict[str, dict[str, object]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_status(self) -> QualificationFactsCacheEntry:
        if self.status is QualificationFactsCacheStatus.SUCCESS and self.facts is None:
            raise ValueError("Successful fact extraction requires facts")
        if (
            self.status is QualificationFactsCacheStatus.FAILED_RETRYABLE
            and self.attempt_count != 1
        ):
            raise ValueError("Retryable extraction failures require one attempt")
        if (
            self.status is QualificationFactsCacheStatus.FAILED_EXHAUSTED
            and self.attempt_count != 2
        ):
            raise ValueError("Exhausted extraction failures require two attempts")
        if (
            self.status is QualificationFactsCacheStatus.SUCCESS
            and self.evidence_ids
            and self.attempt_count == 0
        ):
            raise ValueError("Successful extraction of Evidence requires an attempt")
        return self


class CampaignCriteria(BaseModel):
    """The campaign fields needed by research prompts and persistence limits."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    target_market: str | None
    industry: str | None
    keywords: list[str]
    company_size: CompanySizeCriteria | None
    target_count: int
    max_companies_to_research: int


class GeneratedSearchQueries(BaseModel):
    """Structured LLM output used to search for candidate companies."""

    queries: list[NonEmptyString] = Field(min_length=1, max_length=5)


class ExtractedCompanyIdentity(BaseModel):
    """Identity fields the extraction model may identify from one search result."""

    name: NonEmptyString
    website: str | None = None
    domain: str | None = None


class ExtractedCompanyIdentities(BaseModel):
    """Structured LLM output for recall-oriented per-result extraction."""

    companies: list[ExtractedCompanyIdentity] = Field(default_factory=list)


class ExtractedCompanyCandidate(ExtractedCompanyIdentity):
    """One extracted company mention with application-assigned source provenance."""

    source_url: str
    source_title: str | None = None
    source_snippet: str | None = None


class AggregatedCompanyCandidate(BaseModel):
    """One conservatively merged candidate and its transient discovery support."""

    name: NonEmptyString
    website: str | None = None
    domain: str | None = None
    mention_count: int = Field(ge=1)
    supporting_urls: list[str] = Field(default_factory=list)
    supporting_results: list[SearchResult] = Field(default_factory=list)


class DiscoveredCompanies(BaseModel):
    """Structured ranking output of campaign-relevant companies."""

    companies: list[DiscoveredCompany] = Field(default_factory=list)


class ResearchCompany(BaseModel):
    """Persisted company context used for transient company-specific research."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: NonEmptyString
    website: str | None = None
    domain: str | None = None


class GeneratedCompanySearchQueries(BaseModel):
    """Structured LLM output used to locate candidate evidence sources for one company."""

    queries: list[NonEmptyString] = Field(min_length=1, max_length=6)


class CompanyPageAttribution(BaseModel):
    """Structured decision that gates a fetched page before evidence extraction."""

    attributable: bool
    reason: NonEmptyString


class CoverageStatus(StrEnum):
    FOUND = "found"
    MISSING = "missing"


class CriterionCoverage(BaseModel):
    criterion: EvidenceCriterion
    subject: str | None = None
    status: CoverageStatus
    evidence_ids: list[UUID] = Field(default_factory=list)


class CoverageSummary(BaseModel):
    total: int
    found: int
    missing: int


class InvestigationStopReason(StrEnum):
    CRITERIA_RESOLVED = "criteria_resolved"
    MAX_ROUNDS = "max_rounds"
    NO_PROGRESS = "no_progress"


class CompanySearchResultTrace(BaseModel):
    """One provider result occurrence, retaining the query-specific rank."""

    result_id: UUID
    rank: int = Field(ge=1)
    url: str
    title: str | None = None
    merge_outcome: Literal[
        "included",
        "duplicate_url",
        "already_processed",
        "result_limit",
        "invalid_url",
    ] = "included"
    selection_outcome: (
        Literal[
            "selected",
            "backfill_candidate",
            "not_selected",
        ]
        | None
    ) = None
    candidate_position: int | None = None
    preferred_position: int | None = None
    fetch_outcome: (
        Literal[
            "ATTEMPTED_SUCCESS",
            "ATTEMPTED_FAILED",
            "NOT_ATTEMPTED_TARGET_REACHED",
            "NOT_ATTEMPTED_CANDIDATES_EXHAUSTED",
        ]
        | None
    ) = None
    fetch_attempt: int | None = None
    failure_category: str | None = None
    http_status: int | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)


class CompanySearchQueryTrace(BaseModel):
    """Compact search request and its provider-ordered result occurrences."""

    query_id: UUID
    query: str
    provider: str
    search_phase: Literal["initial", "followup"]
    investigation_round: int = Field(ge=1)
    success: bool
    result_count: int = Field(ge=0)
    results: list[CompanySearchResultTrace] = Field(default_factory=list)


class CompanyInvestigationState(BaseModel):
    company_id: UUID
    round: int = Field(default=0, ge=0)
    coverage: list[CriterionCoverage] = Field(default_factory=list)
    attempted_urls: set[str] = Field(default_factory=set)
    transient_fetch_failures: dict[str, int] = Field(default_factory=dict)
    attempted_queries: list[str] = Field(default_factory=list, max_length=60)
    attempted_strategy_focuses: list[str] = Field(default_factory=list, max_length=4)
    search_queries: list[CompanySearchQueryTrace] = Field(default_factory=list)
    unresolved_before: set[str] = Field(default_factory=set)
    alternative_strategy_attempted: bool = False
    new_evidence_count: int = 0
    stopped: bool = False
    stop_reason: InvestigationStopReason | None = None

    @property
    def summary(self) -> CoverageSummary:
        found = sum(item.status is CoverageStatus.FOUND for item in self.coverage)
        return CoverageSummary(
            total=len(self.coverage), found=found, missing=len(self.coverage) - found
        )


class ValidatedResearchEvidence(BaseModel):
    """Evidence ready to persist, with application-assigned provenance."""

    company_id: UUID
    research_run_id: UUID
    criterion: EvidenceCriterion
    subject: str | None = None
    claim: NonEmptyString
    evidence_text: NonEmptyString
    source_url: NonEmptyString
    source_title: str | None = None


class ResearchWorkflowResult(BaseModel):
    """Public result returned by a completed workflow execution."""

    research_run_id: UUID
    status: str
    companies_found: int
