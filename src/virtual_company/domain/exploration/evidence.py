"""Validated Evidence supporting one Exploration obligation for a company."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExplorationEvidence(BaseModel):
    """A factual claim and its source support, with application-owned provenance."""

    model_config = ConfigDict(extra="forbid")

    exploration_run_id: UUID
    exploration_company_id: UUID
    company_id: UUID
    exploration_obligation_id: UUID
    claim: str = Field(min_length=1, max_length=2_000)
    supporting_excerpt: str = Field(min_length=1)
    query: str = Field(min_length=1)
    search_result_url: str = Field(min_length=1)
    search_result_title: str
    search_result_snippet: str | None = None
    source_url: str = Field(min_length=1)
    final_url: str | None = None
    source_title: str | None = None
