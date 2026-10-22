"""Create contracts for immutable Exploration reasoning artifacts."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from virtual_company.repositories.dtos import (
    ExplorationEvidenceCreate,
    ExplorationFactCreate,
    ExplorationHypothesisCreate,
)
from virtual_company.repositories.exploration_evidence import (
    ExplorationEvidenceRepository,
)
from virtual_company.repositories.exploration_fact import ExplorationFactRepository
from virtual_company.repositories.exploration_hypothesis import (
    ExplorationHypothesisRepository,
)


def test_evidence_create_requires_nonblank_claim_excerpt_and_source() -> None:
    required = {
        "exploration_company_id": uuid4(),
        "exploration_obligation_id": uuid4(),
        "claim": "A claim.",
        "supporting_excerpt": "An exact excerpt.",
        "source_url": "https://example.com/page",
    }
    evidence = ExplorationEvidenceCreate(**required)

    assert evidence.requested_url is None
    assert evidence.source_title is None
    assert evidence.claim == "A claim."

    for field in ("claim", "supporting_excerpt", "source_url"):
        with pytest.raises(ValidationError):
            ExplorationEvidenceCreate(**{**required, field: "  "})


def test_evidence_requested_url_and_title_are_normalized() -> None:
    evidence = ExplorationEvidenceCreate(
        exploration_company_id=uuid4(),
        exploration_obligation_id=uuid4(),
        claim=" Claim ",
        supporting_excerpt=" Excerpt ",
        source_url=" https://example.com/page ",
        requested_url="https://example.com/page",
        source_title="  Page title  ",
    )

    assert evidence.claim == "Claim"
    assert evidence.supporting_excerpt == "Excerpt"
    assert evidence.source_url == "https://example.com/page"
    assert evidence.requested_url is None
    assert evidence.source_title == "Page title"

    with pytest.raises(ValidationError, match="requested_url"):
        ExplorationEvidenceCreate(
            exploration_company_id=uuid4(),
            exploration_obligation_id=uuid4(),
            claim="Claim",
            supporting_excerpt="Excerpt",
            source_url="https://example.com/page",
            requested_url="  ",
        )


def test_fact_and_hypothesis_create_require_nonblank_statements_and_links() -> None:
    company_id = uuid4()
    evidence_id = uuid4()
    fact_id = uuid4()

    fact = ExplorationFactCreate(
        exploration_company_id=company_id,
        statement=" A factual statement ",
        evidence_ids=[evidence_id],
    )
    hypothesis = ExplorationHypothesisCreate(
        exploration_company_id=company_id,
        statement=" An interpretation ",
        fact_ids=[fact_id],
    )

    assert fact.statement == "A factual statement"
    assert hypothesis.statement == "An interpretation"

    with pytest.raises(ValidationError):
        ExplorationFactCreate(
            exploration_company_id=company_id,
            statement=" ",
            evidence_ids=[evidence_id],
        )
    with pytest.raises(ValidationError):
        ExplorationFactCreate(
            exploration_company_id=company_id,
            statement="Statement",
            evidence_ids=[],
        )
    with pytest.raises(ValidationError):
        ExplorationHypothesisCreate(
            exploration_company_id=company_id,
            statement=" ",
            fact_ids=[fact_id],
        )
    with pytest.raises(ValidationError):
        ExplorationHypothesisCreate(
            exploration_company_id=company_id,
            statement="Statement",
            fact_ids=[],
        )


def test_reasoning_repositories_have_no_update_methods() -> None:
    assert not hasattr(ExplorationEvidenceRepository, "update")
    assert not hasattr(ExplorationFactRepository, "update")
    assert not hasattr(ExplorationHypothesisRepository, "update")
