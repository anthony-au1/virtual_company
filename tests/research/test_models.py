"""Tests for research workflow data-transfer models."""

import pytest
from pydantic import ValidationError

from virtual_company.research.models import (
    DiscoveredCompany,
    EvidenceCriterion,
    ExtractedEvidence,
    SearchResult,
    WebPage,
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
        criterion=EvidenceCriterion.TECHNOLOGY,
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
