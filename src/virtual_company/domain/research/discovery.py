"""Research company discovery domain contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiscoveredCompany(BaseModel):
    """A company found by Research before persistence."""

    name: str
    website: str | None = None
    domain: str | None = None
    discovery_reason: str = Field(min_length=1)
    supporting_urls: list[str] = Field(max_length=3)
