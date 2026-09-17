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
COMPANY_DISCOVERY_PROMPT = PromptIdentity("discover_companies", "v3")
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
    """Return instructions for evidence-bound, recall-oriented candidate discovery."""
    return (
        "Your task is CANDIDATE DISCOVERY, not final qualification. Using only the supplied "
        "search results, identify plausible companies worth further investigation for the campaign. "
        "Favor recall over strict qualification: a company does not need every campaign criterion "
        "proven in these results. Include a company when there is reasonable evidence that it is a "
        "real, identifiable organization; operates in or is meaningfully associated with the target "
        "market; plausibly belongs to the target industry or business category; and is worth additional "
        "research. Return up to the supplied discovery candidate limit, not the campaign target count. "
        "Rank stronger candidates first using industry relevance, geographic relevance, clear company "
        "identity, source credibility, company-size compatibility when known, and multiple-source "
        "support when available. These are ranking signals, not hard gates. Company size is useful when "
        "available, but unknown size is not a reason to exclude an otherwise strong candidate. Technology "
        "information is not required during discovery; technologies, exact employee counts, architecture, "
        "and hiring signals belong to downstream investigation. Prefer official company websites, official "
        "industry associations, government or trade bodies, credible industry reports, reputable business "
        "publications, and credible company directories over generic SEO pages, social-media posts, "
        "ambiguous snippets, or unrelated mentions. Do not include clearly irrelevant entities, companies "
        "from clearly wrong countries, non-company entities, generic websites, or ambiguous names without "
        "useful context. Do not invent companies, websites, domains, or supporting URLs. Return a website "
        "or domain only when the supplied results reasonably support it as official. For every selected "
        "company, provide a concise reason it is worth investigating, including material uncertainty, and "
        "up to three supporting URLs copied from the supplied results."
    )


def company_discovery_user_prompt(
    campaign: CampaignCriteria, search_results: list[SearchResult], candidate_limit: int
) -> str:
    """Serialize campaign criteria and evidence for company discovery."""
    evidence = [result.model_dump() for result in search_results]
    return (
        f"Campaign criteria:\n{campaign.model_dump_json()}\n\n"
        f"Discovery candidate limit: {candidate_limit}\n\n"
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
