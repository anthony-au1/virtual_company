"""Prompts used by the campaign research workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass

from virtual_company.research.models import SearchResult
from virtual_company.workflows.research.models import CampaignCriteria


@dataclass(frozen=True)
class PromptIdentity:
    """Stable metadata for a locally managed prompt."""

    name: str
    version: str


SEARCH_QUERY_PROMPT = PromptIdentity("generate_search_queries", "v1")
COMPANY_DISCOVERY_PROMPT = PromptIdentity("discover_companies", "v1")


def search_query_system_prompt() -> str:
    """Return instructions for campaign-focused query generation."""
    return (
        "Generate targeted web-search queries for discovering companies that match "
        "the campaign. Return queries only; do not research or answer the campaign. "
        "Favor queries likely to surface company and official-site information."
    )


def search_query_user_prompt(campaign: CampaignCriteria) -> str:
    """Serialize campaign criteria for query generation."""
    return f"Campaign criteria:\n{campaign.model_dump_json()}"


def company_discovery_system_prompt() -> str:
    """Return instructions for evidence-bound company discovery."""
    return (
        "Identify plausible companies for the campaign using only the supplied search "
        "results. Do not invent companies, websites, or domains. Prefer an official "
        "website only when it appears in the supplied evidence. Deduplicate companies, "
        "normalize domains where practical, and return no more companies than the "
        "campaign target count."
    )


def company_discovery_user_prompt(
    campaign: CampaignCriteria, search_results: list[SearchResult]
) -> str:
    """Serialize campaign criteria and evidence for company discovery."""
    evidence = [result.model_dump() for result in search_results]
    return (
        f"Campaign criteria:\n{campaign.model_dump_json()}\n\n"
        f"Search results:\n{json.dumps(evidence)}"
    )
