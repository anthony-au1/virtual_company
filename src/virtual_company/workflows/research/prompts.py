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
COMPANY_DISCOVERY_PROMPT = PromptIdentity("discover_companies", "v2")
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
    """Return instructions for evidence-bound, quality-first company discovery."""
    return (
        "Identify and compare plausible companies for the campaign using only the supplied "
        "search results. Select the strongest candidates based on combined support for company "
        "identity, target geography or market, industry or business relevance, source quality, "
        "and multiple-source support where available. Prefer official company websites, official "
        "industry associations, government or trade bodies, credible industry reports, reputable "
        "business publications, and credible company directories over scraped directories, generic "
        "SEO pages, social-media posts, ambiguous snippets, or unrelated mentions. Company size is "
        "useful when available but is not required: unknown size must not disqualify an otherwise "
        "strong candidate. Do not verify technology criteria at this stage; those belong to downstream "
        "company-specific investigation. Return UP TO the campaign target count, not a quota: quality "
        "is more important than filling the count, so return fewer candidates or none when support is "
        "weak. Do not invent companies, websites, domains, or supporting URLs. Return a website or "
        "domain only when the supplied results reasonably support it as official. For every selected "
        "company, provide a discovery confidence for its suitability for further investigation, a concise "
        "reason that states material uncertainty, and up to three supporting URLs copied from the supplied "
        "results."
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
