"""Tests for research workflow data-transfer models."""

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from virtual_company.domain.research.criteria import EvidenceCriterion
from virtual_company.domain.research.discovery import DiscoveredCompany
from virtual_company.tools.web_fetch import WebPage
from virtual_company.tools.web_search import SearchResult
from virtual_company.workflows.research.models import (
    MAX_COMPANY_SEARCH_QUERY_CHARS,
    ExtractedEvidence,
    GeneratedCompanySearchQueries,
)


def test_research_models_accept_expected_data() -> None:
    search_result = SearchResult(title="Example", url="https://example.com")
    web_page = WebPage(url="https://example.com", content="Example content")
    company = DiscoveredCompany(
        name="Example Inc.",
        discovery_reason="A credible directory identifies the company.",
        supporting_urls=["https://example.com"],
    )
    evidence = ExtractedEvidence(
        criterion=EvidenceCriterion.KEYWORD,
        subject="Python",
        claim="Example claim",
        evidence_text="Supporting text",
    )

    assert search_result.snippet is None
    assert web_page.title is None
    assert company.website is None
    assert company.discovery_reason == "A credible directory identifies the company."
    assert evidence.subject == "Python"


def test_discovered_company_limits_supporting_urls() -> None:
    with pytest.raises(ValidationError):
        DiscoveredCompany(
            name="Example Inc.",
            discovery_reason="A credible source identifies the company.",
            supporting_urls=[f"https://example.com/{index}" for index in range(4)],
        )


def test_generated_company_queries_enforce_per_query_character_limit() -> None:
    exact_limit_query = "q" * MAX_COMPANY_SEARCH_QUERY_CHARS
    result = GeneratedCompanySearchQueries(queries=[exact_limit_query])

    assert result.queries == [exact_limit_query]
    with pytest.raises(ValidationError, match="at most 256 characters"):
        GeneratedCompanySearchQueries(queries=[exact_limit_query + "q"])
    with pytest.raises(ValidationError):
        GeneratedCompanySearchQueries(queries=[])
    with pytest.raises(ValidationError):
        GeneratedCompanySearchQueries(queries=["valid"] * 7)
    with pytest.raises(ValidationError):
        GeneratedCompanySearchQueries(queries=[""])


def test_openai_strict_query_schema_supports_max_length() -> None:
    schema = to_strict_json_schema(GeneratedCompanySearchQueries)
    query_schema = schema["properties"]["queries"]["items"]

    assert query_schema["type"] == "string"
    assert query_schema["minLength"] == 1
    assert query_schema["maxLength"] == MAX_COMPANY_SEARCH_QUERY_CHARS
    assert schema["properties"]["queries"]["minItems"] == 1
    assert schema["properties"]["queries"]["maxItems"] == 6
