"""Campaign criterion configuration and shared subject normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

_TECHNOLOGY_FORMAT_VARIANTS = {
    "springboot": "spring boot",
    "spring-boot": "spring boot",
    "spring_boot": "spring boot",
}


def normalize_subject(criterion: str, value: str | None) -> str:
    key = " ".join((value or "").casefold().split())
    if criterion == "technology":
        return _TECHNOLOGY_FORMAT_VARIANTS.get(key, key)
    if criterion == "industry" and key == "fin tech":
        return "fintech"
    return key


class CompanySizeCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int | None = Field(default=None, ge=0, strict=True)
    max: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_bounds(cls, value: object) -> object:
        """Read previously persisted one-field bounds while emitting flat values."""
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for bound_name in ("min", "max"):
            bound = normalized.get(bound_name)
            if isinstance(bound, dict) and set(bound) == {"value"}:
                normalized[bound_name] = bound["value"]
        return normalized

    @model_validator(mode="after")
    def validate_bounds(self) -> CompanySizeCriteria:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("company_size.min cannot exceed company_size.max")
        return self


class CampaignForQualification(Protocol):
    target_market: str | None
    industry: str | None
    technologies: list[str]
    company_size: CompanySizeCriteria | None


@dataclass(frozen=True)
class CampaignCriterion:
    criterion: str
    subject: str | None
    size_bound: Literal["min", "max"] | None = None
    size_value: int | None = None


def campaign_criteria(campaign: CampaignForQualification) -> list[CampaignCriterion]:
    criteria: list[CampaignCriterion] = []
    if campaign.target_market:
        criteria.append(CampaignCriterion("target_market", campaign.target_market))
    if campaign.industry:
        criteria.append(CampaignCriterion("industry", campaign.industry))
    criteria.extend(
        CampaignCriterion("technology", label) for label in campaign.technologies
    )
    if campaign.company_size:
        for bound_name, operator in (("min", ">="), ("max", "<=")):
            bound = getattr(campaign.company_size, bound_name)
            if bound is not None:
                criteria.append(
                    CampaignCriterion(
                        "company_size",
                        f"employees {operator} {bound}",
                        bound_name,
                        bound,
                    )
                )
    return criteria
