"""Pydantic data-transfer models for the research workflow."""

from enum import StrEnum

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """One result returned by a web search provider."""

    title: str
    url: str
    snippet: str | None = None


class WebPage(BaseModel):
    """Downloaded web-page content for later analysis."""

    url: str
    final_url: str | None = None
    title: str | None = None
    content: str
    content_type: str | None = None
    truncated: bool = False


class DiscoveredCompany(BaseModel):
    """A company found during research before persistence."""

    name: str
    website: str | None = None
    domain: str | None = None
    discovery_reason: str = Field(min_length=1)
    supporting_urls: list[str] = Field(max_length=3)


class EvidenceCriterion(StrEnum):
    """Campaign criteria which can be supported by extracted evidence."""

    TARGET_MARKET = "target_market"
    INDUSTRY = "industry"
    TECHNOLOGY = "technology"
    COMPANY_SIZE = "company_size"


class ExtractedEvidence(BaseModel):
    """LLM-provided evidence content, without authoritative source identity."""

    criterion: EvidenceCriterion
    subject: str | None = None
    claim: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)


class ExtractedEvidenceItems(BaseModel):
    """Structured output from one page-scoped evidence extraction call."""

    evidence: list[ExtractedEvidence] = Field(default_factory=list)
