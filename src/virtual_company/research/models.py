"""Pydantic data-transfer models for the research workflow."""

from typing import Annotated

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


class ExtractedEvidence(BaseModel):
    """A source-backed claim extracted from research material."""

    claim: str
    evidence_text: str
    source_url: str
    source_title: str | None = None
    source_type: str | None = None
    confidence: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
