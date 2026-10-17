from __future__ import annotations

from uuid import uuid4

from virtual_company.workflows.research.models import (
    CompanyInvestigationState,
    CompanySearchQueryTrace,
    CompanySearchResultTrace,
)
from virtual_company.workflows.research.observability.search_provenance import (
    SearchProvenanceRecorder,
)


def _query(
    *,
    query: str,
    round_number: int,
    phase: str,
    url: str,
    rank: int,
) -> CompanySearchQueryTrace:
    return CompanySearchQueryTrace(
        query_id=uuid4(),
        query=query,
        provider="exa",
        search_phase=phase,  # type: ignore[arg-type]
        investigation_round=round_number,
        success=True,
        result_count=1,
        results=[
            CompanySearchResultTrace(
                result_id=uuid4(),
                rank=rank,
                url=url,
            )
        ],
    )


def test_same_url_occurrences_in_queries_keep_independent_merge_and_selection() -> None:
    url = "https://jobs.example/acme"
    query_a = _query(
        query="Acme Java",
        round_number=1,
        phase="initial",
        url=url,
        rank=2,
    )
    query_b = _query(
        query="Acme Spring",
        round_number=1,
        phase="initial",
        url=url,
        rank=5,
    )
    merged = SearchProvenanceRecorder.record_merge_outcomes(
        [query_a, query_b],
        included_origins=[(0, 2)],
        seen_urls=set(),
        included_urls={"https://jobs.example/acme"},
    )
    included, duplicate = merged[0].results[0], merged[1].results[0]
    assert included.result_id != duplicate.result_id
    assert merged[0].query_id != merged[1].query_id
    assert included.merge_outcome == "included"
    assert duplicate.merge_outcome == "duplicate_url"

    investigation = CompanyInvestigationState(
        company_id=uuid4(), round=1, search_queries=merged
    )
    selected = SearchProvenanceRecorder.record_selection(
        investigation,
        investigation_round=1,
        decisions_by_result_id={
            included.result_id: {
                "preferred": True,
                "candidate_position": 1,
                "preferred_position": 1,
            }
        },
    )
    assert selected.search_queries[0].results[0].selection_outcome == "selected"
    assert selected.search_queries[1].results[0].selection_outcome is None


def test_later_round_fetch_and_evidence_do_not_mutate_prior_occurrence() -> None:
    url = "https://jobs.example/acme"
    evidence_id = uuid4()
    first = _query(
        query="Acme Java jobs",
        round_number=1,
        phase="initial",
        url=url,
        rank=2,
    ).model_copy(
        update={
            "results": [
                CompanySearchResultTrace(
                    result_id=uuid4(),
                    rank=2,
                    url=url,
                    merge_outcome="included",
                    selection_outcome="selected",
                    fetch_outcome="ATTEMPTED_SUCCESS",
                    fetch_attempt=1,
                    evidence_ids=[evidence_id],
                )
            ]
        }
    )
    second = _query(
        query="Acme Java engineering",
        round_number=2,
        phase="followup",
        url=url,
        rank=4,
    ).model_copy(
        update={
            "results": [
                CompanySearchResultTrace(
                    result_id=uuid4(),
                    rank=4,
                    url=url,
                    merge_outcome="already_processed",
                )
            ]
        }
    )
    investigation = CompanyInvestigationState(
        company_id=uuid4(), round=2, search_queries=[first, second]
    )
    second_result_id = second.results[0].result_id
    updated = SearchProvenanceRecorder.record_fetch_outcomes(
        investigation,
        investigation_round=2,
        outcomes_by_result_id={
            second_result_id: {"outcome": "ATTEMPTED_FAILED", "fetch_attempt": 1}
        },
    )
    first_result_id = first.results[0].result_id
    later_evidence_id = uuid4()
    updated, linked = SearchProvenanceRecorder.link_evidence(
        updated,
        result_id=first_result_id,
        evidence_id=later_evidence_id,
        investigation_round=1,
    )
    assert linked is not None
    first_result = updated.search_queries[0].results[0]
    second_result = updated.search_queries[1].results[0]
    assert first_result.selection_outcome == "selected"
    assert first_result.fetch_outcome == "ATTEMPTED_SUCCESS"
    assert first_result.evidence_ids == [evidence_id, later_evidence_id]
    assert second_result.merge_outcome == "already_processed"
    assert second_result.fetch_outcome is None
    assert second_result.evidence_ids == []


def test_snapshot_keeps_search_provenance_shape_and_sanitizes_urls() -> None:
    query = _query(
        query="Acme Java jobs",
        round_number=2,
        phase="followup",
        url="https://user:password@jobs.example/role?token=secret#details",
        rank=3,
    )
    snapshot = SearchProvenanceRecorder.snapshot(
        CompanyInvestigationState(company_id=uuid4(), search_queries=[query])
    )
    assert set(snapshot) == {"queries"}
    result = snapshot["queries"][0]["results"][0]  # type: ignore[index]
    assert result["rank"] == 3
    assert result["url"] == "https://jobs.example/role"
    assert "password" not in repr(snapshot)
    assert "secret" not in repr(snapshot)
