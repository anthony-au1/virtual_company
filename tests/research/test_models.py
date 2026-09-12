"""Tests for research workflow data-transfer models."""

import pytest
from pydantic import ValidationError

from virtual_company.research.models import (
    DiscoveredCompany,
    ExtractedEvidence,
    SearchResult,
    WebPage,
)


def test_research_models_accept_expected_data() -> None:
    search_result = SearchResult(title="Example", url="https://example.com")
    web_page = WebPage(url="https://example.com", content="Example content")
    company = DiscoveredCompany(name="Example Inc.")
    evidence = ExtractedEvidence(
        claim="Example claim",
        evidence_text="Supporting text",
        source_url="https://example.com",
        confidence=0.5,
    )

    assert search_result.snippet is None
    assert web_page.title is None
    assert company.website is None
    assert evidence.source_title is None


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_evidence_confidence_accepts_inclusive_boundaries(confidence: float) -> None:
    evidence = ExtractedEvidence(
        claim="Claim",
        evidence_text="Evidence",
        source_url="https://example.com",
        confidence=confidence,
    )

    assert evidence.confidence == confidence


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_evidence_confidence_rejects_values_outside_unit_interval(
    confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        ExtractedEvidence(
            claim="Claim",
            evidence_text="Evidence",
            source_url="https://example.com",
            confidence=confidence,
        )
