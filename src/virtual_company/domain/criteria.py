"""Campaign criterion configuration and shared subject normalization."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CriterionRequirement(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"


TECHNOLOGY_IMPLICATIONS = {"spring boot": frozenset({"spring"})}
_TECHNOLOGY_ALIASES = {
    "springboot": "spring boot",
    "spring-boot": "spring boot",
    "spring_boot": "spring boot",
    "apache kafka": "kafka",
}


def normalize_subject(criterion: str, value: str | None) -> str:
    key = " ".join((value or "").casefold().split())
    if criterion == "technology":
        return _TECHNOLOGY_ALIASES.get(key, key)
    if criterion == "industry" and key == "fin tech":
        return "fintech"
    return key


def technology_subjects(value: str | None) -> set[str]:
    """Expand positive technology support, preserving implication direction."""
    key = normalize_subject("technology", value)
    return {key, *TECHNOLOGY_IMPLICATIONS.get(key, ())}


class TechnologyCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_labels(self) -> TechnologyCriteria:
        seen: dict[str, str] = {}
        for requirement in ("required", "preferred"):
            unique: list[str] = []
            for label in getattr(self, requirement):
                key = normalize_subject("technology", label)
                if not key:
                    raise ValueError("Technology labels cannot be blank")
                if key in seen and seen[key] != requirement:
                    raise ValueError(
                        f"Technology {label!r} duplicates a {seen[key]} technology"
                    )
                if key in seen:
                    continue
                seen[key] = requirement
                unique.append(label)
            setattr(self, requirement, unique)
        return self


class CompanySizeBound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int = Field(ge=0, strict=True)
    requirement: CriterionRequirement


class CompanySizeCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: CompanySizeBound | None = None
    max: CompanySizeBound | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> CompanySizeCriteria:
        if self.min and self.max and self.min.value > self.max.value:
            raise ValueError(
                "company_size.min.value cannot exceed company_size.max.value"
            )
        return self


class CampaignForQualification(Protocol):
    target_market: str | None
    industry: str | None
    technologies: TechnologyCriteria
    company_size: CompanySizeCriteria | None


@dataclass(frozen=True)
class CampaignCriterion:
    criterion: str
    subject: str | None
    requirement: CriterionRequirement
    size_bound: Literal["min", "max"] | None = None
    size_value: int | None = None


def campaign_criteria(campaign: CampaignForQualification) -> list[CampaignCriterion]:
    criteria: list[CampaignCriterion] = []
    if campaign.target_market:
        criteria.append(
            CampaignCriterion(
                "target_market", campaign.target_market, CriterionRequirement.REQUIRED
            )
        )
    if campaign.industry:
        criteria.append(
            CampaignCriterion(
                "industry", campaign.industry, CriterionRequirement.REQUIRED
            )
        )
    for requirement in (CriterionRequirement.REQUIRED, CriterionRequirement.PREFERRED):
        for label in getattr(campaign.technologies, requirement.value):
            criteria.append(CampaignCriterion("technology", label, requirement))
    if campaign.company_size:
        for bound_name, operator in (("min", ">="), ("max", "<=")):
            bound = getattr(campaign.company_size, bound_name)
            if bound is not None:
                criteria.append(
                    CampaignCriterion(
                        "company_size",
                        f"employees {operator} {bound.value}",
                        bound.requirement,
                        bound_name,
                        bound.value,
                    )
                )
    return criteria
