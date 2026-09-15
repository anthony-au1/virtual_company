"""Prompts used by the campaign research workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass

from virtual_company.research.models import SearchResult
from virtual_company.workflows.research.models import CampaignCriteria, ResearchCompany


@dataclass(frozen=True)
class PromptIdentity:
    """Stable metadata for a locally managed prompt."""

    name: str
    version: str


SEARCH_QUERY_PROMPT = PromptIdentity("generate_search_queries", "v2")
COMPANY_DISCOVERY_PROMPT = PromptIdentity("discover_companies", "v1")
COMPANY_QUERY_PROMPT = PromptIdentity("generate_company_queries", "v1")


def search_query_system_prompt() -> str:
    """Return instructions for bounded company-discovery query generation."""
    return (
        "Your goal is COMPANY DISCOVERY: generate 3 to 5 complementary web-search "
        "queries that identify plausible companies matching the campaign's broad business "
        "profile. This stage finds candidate companies; it is not technology verification, "
        "job search, or evidence collection. Focus primarily on target geography or market, "
        "industry, company or business type, relevant industry segments, and approximate "
        "company size when useful. Technology criteria such as programming languages, "
        "frameworks, cloud platforms, databases, and messaging systems are downstream "
        "investigation criteria: do not use them as primary discovery search constraints. "
        "Avoid queries primarily intended to find jobs, vacancies, careers, hiring, software "
        "engineer positions, or developer positions. Do not intentionally target LinkedIn "
        "Jobs, SEEK, Indeed, Glassdoor, or generic job aggregators. Prefer queries likely "
        "to surface company websites, company directories, industry associations, industry "
        "company lists, startup or scale-up lists, accelerator or portfolio pages, "
        "reputable market reports, funding or company databases, and articles profiling "
        "relevant companies. Use distinct, complementary search strategies rather than "
        "paraphrases. Return search queries only; do not answer the campaign or invent companies."
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


def company_query_system_prompt() -> str:
    """Return instructions for source-discovery queries about one known company."""
    return (
        "Generate 4 to 6 web-search queries to find candidate sources of evidence about "
        "whether this company matches the campaign. You are generating research queries, "
        "not asserting facts: queries may investigate and disprove hypotheses. When a company "
        "domain is supplied, include some official-domain site: queries and some relevant "
        "third-party queries. Favor engineering, careers, job advertisements, technical blogs, "
        "conference material, architecture articles, migrations, and credible news where relevant."
    )


def company_query_user_prompt(campaign: CampaignCriteria, company: ResearchCompany) -> str:
    """Serialize campaign criteria and one company for source-query generation."""
    return (
        f"Campaign criteria:\n{campaign.model_dump_json()}\n\n"
        f"Company context:\n{company.model_dump_json()}"
    )
