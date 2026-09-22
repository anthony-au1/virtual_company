"""Shared, conservative campaign criterion matching."""

from typing import Any, Protocol


class CampaignForQualification(Protocol):
    target_market: str | None
    industry: str | None
    technologies: dict[str, Any] | list[Any] | None
    company_size_min: int | None
    company_size_max: int | None


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


def campaign_technologies(campaign: CampaignForQualification) -> list[str]:
    raw = campaign.technologies
    values = raw.values() if isinstance(raw, dict) else raw or []
    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = str(value).strip()
        key = normalize_subject("technology", label)
        if key and key not in seen:
            seen.add(key)
            labels.append(label)
    return labels


def campaign_criteria(
    campaign: CampaignForQualification,
) -> list[tuple[str, str | None]]:
    criteria: list[tuple[str, str | None]] = []
    if campaign.target_market:
        criteria.append(("target_market", campaign.target_market))
    if campaign.industry:
        criteria.append(("industry", campaign.industry))
    criteria.extend(("technology", label) for label in campaign_technologies(campaign))
    if campaign.company_size_min is not None or campaign.company_size_max is not None:
        criteria.append(("company_size", None))
    return criteria
