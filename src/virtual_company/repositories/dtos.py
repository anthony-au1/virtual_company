"""Typed inputs accepted by persistence repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(slots=True)
class CampaignCreate:
    name: str
    target_count: int
    status: str
    description: str | None = None
    target_market: str | None = None
    industry: str | None = None
    technologies: dict[str, Any] | list[Any] | None = None
    company_size_min: int | None = None
    company_size_max: int | None = None


@dataclass(slots=True)
class CampaignUpdate:
    name: str | None = None
    description: str | None = None
    target_market: str | None = None
    industry: str | None = None
    technologies: dict[str, Any] | list[Any] | None = None
    company_size_min: int | None = None
    company_size_max: int | None = None
    target_count: int | None = None
    status: str | None = None


@dataclass(slots=True)
class CompanyCreate:
    name: str
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    employee_number: int | None = None


@dataclass(slots=True)
class CompanyUpdate:
    name: str | None = None
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    employee_number: int | None = None


@dataclass(slots=True)
class CampaignTargetCreate:
    campaign_id: UUID
    company_id: UUID
    score: Decimal | None = None
    status: str | None = None


@dataclass(slots=True)
class CampaignTargetUpdate:
    score: Decimal | None = None
    status: str | None = None


@dataclass(slots=True)
class EvidenceCreate:
    company_id: UUID
    claim: str
    evidence_text: str
    source_url: str
    source_title: str | None = None
    source_type: str | None = None
    confidence: Decimal | None = None
    observed_at: datetime | None = None


@dataclass(slots=True)
class EvidenceUpdate:
    claim: str | None = None
    evidence_text: str | None = None
    source_url: str | None = None
    source_title: str | None = None
    source_type: str | None = None
    confidence: Decimal | None = None
    observed_at: datetime | None = None


@dataclass(slots=True)
class ResearchRunCreate:
    campaign_id: UUID
    status: str
    companies_found: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


@dataclass(slots=True)
class ResearchRunUpdate:
    status: str | None = None
    completed_at: datetime | None = None
    error: str | None = None
    companies_found: int | None = None
