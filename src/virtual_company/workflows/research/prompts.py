"""Prompts used by the campaign research workflow."""

from __future__ import annotations

import json

from virtual_company.research.models import SearchResult
from virtual_company.workflows.research.models import CampaignCriteria


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
