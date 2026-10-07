"""Tests for Research Workflow event selection and usage reporting."""

from __future__ import annotations

import json

import pytest

from virtual_company.observability import research_report


def event(name: str, run_id: str, **fields: object) -> dict[str, object]:
    return {
        "timestamp": "2026-10-07T01:00:00+00:00",
        "event": name,
        "campaign_id": "campaign-1",
        "research_run_id": run_id,
        **fields,
    }


def test_latest_completed_run_selection_does_not_mix_correlated_events() -> None:
    events = [
        event("web_search_started", "old-run", search_phase="discovery"),
        event("research_run_completed", "old-run", campaign_name="Old"),
        event("web_search_started", "new-run", search_phase="discovery"),
        event("research_run_completed", "new-run", campaign_name="New"),
    ]
    events[-1]["timestamp"] = "2026-10-07T02:00:00+00:00"

    run_id, campaign_id, selected = research_report.select_run_events(events)

    assert run_id == "new-run"
    assert campaign_id == "campaign-1"
    assert {item["research_run_id"] for item in selected} == {"new-run"}


def test_aggregation_uses_actual_usage_and_computes_run_metrics() -> None:
    events = [
        event("search_queries_generated", "run-1", query_count=2),
        event(
            "web_search_started", "run-1", provider="tavily", search_phase="discovery"
        ),
        event(
            "web_search_completed", "run-1", result_count=4, search_phase="discovery"
        ),
        event(
            "web_search_usage_reported",
            "run-1",
            provider="tavily",
            search_phase="discovery",
            usage_amount=2,
            usage_unit="credits",
            usage_is_actual=True,
        ),
        event(
            "company_research_queries_generated",
            "run-1",
            company_id="co-1",
            query_count=3,
        ),
        event(
            "followup_company_queries_generated",
            "run-1",
            company_id="co-1",
            query_count=1,
        ),
        event(
            "web_search_started",
            "run-1",
            provider="tavily",
            search_phase="investigation",
        ),
        event(
            "web_search_completed",
            "run-1",
            result_count=3,
            search_phase="investigation",
        ),
        event(
            "web_search_usage_reported",
            "run-1",
            provider="tavily",
            search_phase="investigation",
            usage_amount=5,
            usage_unit="credits",
            usage_is_actual=True,
        ),
        event(
            "company_sources_selected",
            "run-1",
            company_id="co-1",
            selected_source_count=2,
        ),
        event("web_fetch_started", "run-1", fetch_attempt=1, fetch_retry=False),
        event("web_fetch_completed", "run-1"),
        event("web_fetch_started", "run-1", fetch_attempt=2, fetch_retry=True),
        event("web_fetch_failed", "run-1"),
        event("company_source_fetch_failed", "run-1", retry_remaining=True),
        event("qualification_facts_extracted", "run-1", company_id="co-1"),
        event("qualification_fact_extraction_retry", "run-1", attempt_number=2),
        event(
            "qualification_fact_extraction_failed",
            "run-1",
            company_id="co-2",
            retry_remaining=True,
        ),
        event(
            "company_qualified",
            "run-1",
            company_id="co-1",
            qualification_status="QUALIFIED",
        ),
        event(
            "company_qualified",
            "run-1",
            company_id="co-1",
            qualification_status="QUALIFIED",
        ),
        event(
            "company_qualified",
            "run-1",
            company_id="co-2",
            qualification_status="INSUFFICIENT_EVIDENCE",
        ),
        event("company_candidates_ranked", "run-1", ranked_candidate_count=8),
        event(
            "research_run_completed",
            "run-1",
            campaign_name="Fintech",
            target_count=1,
            target_reached=True,
            stop_reason="TARGET_REACHED",
        ),
    ]

    usage = research_report.aggregate_run(events, "campaign-1", "run-1")

    assert usage.discovery_queries == 2
    assert usage.initial_queries == 3
    assert usage.followup_queries == 1
    assert usage.search_calls == 2
    assert usage.search_results == 7
    assert usage.actual_search_credits == 7
    assert usage.credits_by_phase == {"discovery": 2, "investigation": 5}
    assert usage.researched_companies == 1
    assert usage.sources_selected == 2
    assert (
        usage.fetch_attempts,
        usage.fetch_successes,
        usage.fetch_failures,
        usage.fetch_retries,
    ) == (2, 1, 1, 1)
    assert (
        usage.qualification_extraction_calls,
        usage.qualification_extraction_failures,
        usage.qualification_extraction_retries,
    ) == (2, 1, 1)
    assert (usage.qualified_companies, usage.insufficient_evidence_companies) == (1, 1)
    assert usage.search_credits_per_researched == 7
    assert usage.search_credits_per_qualified == 7
    assert usage.target_reached is True


def test_estimated_or_missing_usage_is_not_reported_as_actual_and_zero_is_safe() -> (
    None
):
    events = [
        event(
            "company_qualified",
            "run-2",
            company_id="co-1",
            qualification_status="INSUFFICIENT_EVIDENCE",
        ),
        event(
            "web_search_usage_reported",
            "run-2",
            provider="exa",
            usage_amount=3,
            usage_unit="credits",
            usage_is_actual=False,
        ),
        event(
            "research_run_completed",
            "run-2",
            campaign_name="Empty",
            target_count=5,
            target_reached=False,
        ),
    ]

    usage = research_report.aggregate_run(events, "campaign-1", "run-2")
    output = research_report.render_cost_report(usage)

    assert usage.actual_search_credits is None
    assert usage.estimated_search_credits == 3
    assert usage.search_credits_per_researched is None
    assert usage.search_credits_per_qualified is None
    assert "Actual credits" in output
    assert "N/A (provider did not report usage)" in output
    assert "Estimated credits (not actual)" in output
    assert "N/A" in research_report.render_report(usage)


def test_log_view_uses_latest_run_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    logs = "\n".join(
        json.dumps(item)
        for item in [
            event("research_run_completed", "older", campaign_name="Old"),
            event("company_qualified", "older", company_id="old-co"),
            event("company_qualified", "newer", company_id="new-co"),
            event("research_run_completed", "newer", campaign_name="New"),
        ]
    )
    monkeypatch.setattr(research_report, "read_compose_logs", lambda: logs)

    assert research_report.main(["log"]) == 0
    output = capsys.readouterr().out
    assert "new-co" in output
    assert "old-co" not in output


def test_parse_json_events_skips_compose_noise_and_preserves_event_payload() -> None:
    raw = 'app  | 2026-10-07T01:00:00Z {"event":"research_run_completed","research_run_id":"run"}\nnoise\n'

    assert research_report.parse_json_events(raw) == [
        {"event": "research_run_completed", "research_run_id": "run"}
    ]


def test_latest_completed_run_can_be_scoped_to_campaign() -> None:
    events = [
        event("research_run_completed", "campaign-a-run", campaign_name="A"),
        {
            **event("research_run_completed", "campaign-b-run", campaign_name="B"),
            "campaign_id": "campaign-2",
            "timestamp": "2026-10-08T00:00:00Z",
        },
    ]

    run_id, campaign_id, _ = research_report.select_run_events(
        events, campaign_id="campaign-1"
    )

    assert run_id == "campaign-a-run"
    assert campaign_id == "campaign-1"


def test_legacy_campaign_events_are_correlated_to_unique_run_boundaries() -> None:
    events = [
        {
            "timestamp": "2026-10-06T23:59:56+00:00",
            "event": "research_workflow_started",
            "campaign_id": "campaign-1",
        },
        {
            "timestamp": "2026-10-06T23:59:57+00:00",
            "event": "web_search_usage_reported",
            "campaign_id": "campaign-1",
            "usage_amount": 99,
            "usage_unit": "credits",
            "usage_is_actual": True,
        },
        {
            "timestamp": "2026-10-06T23:59:58+00:00",
            "event": "research_run_completed",
            "campaign_id": "campaign-1",
            "research_run_id": "previous-run",
        },
        {
            "timestamp": "2026-10-07T00:00:00+00:00",
            "event": "research_workflow_started",
            "campaign_id": "campaign-1",
        },
        {
            "timestamp": "2026-10-07T00:00:01+00:00",
            "event": "web_search_started",
            "campaign_id": "campaign-1",
            "search_phase": "discovery",
            "provider": "tavily",
        },
        {
            "timestamp": "2026-10-07T00:00:02+00:00",
            "event": "web_search_completed",
            "campaign_id": "campaign-1",
            "search_phase": "discovery",
            "result_count": 4,
        },
        {
            "timestamp": "2026-10-07T00:00:02+00:00",
            "event": "web_search_usage_reported",
            "campaign_id": "campaign-1",
            "search_phase": "discovery",
            "usage_amount": 2,
            "usage_unit": "credits",
            "usage_is_actual": True,
        },
        {
            "timestamp": "2026-10-07T00:00:03+00:00",
            "event": "company_sources_selected",
            "campaign_id": "campaign-1",
            "company_id": "company-a",
            "selected_source_count": 1,
        },
        {
            "timestamp": "2026-10-07T00:00:04+00:00",
            "event": "web_fetch_started",
            "campaign_id": "campaign-1",
            "fetch_retry": False,
        },
        {
            "timestamp": "2026-10-07T00:00:05+00:00",
            "event": "web_fetch_completed",
            "campaign_id": "campaign-1",
        },
        {
            "timestamp": "2026-10-07T00:00:06+00:00",
            "event": "company_qualified",
            "campaign_id": "campaign-1",
            "company_id": "company-a",
            "qualification_status": "QUALIFIED",
        },
        {
            "timestamp": "2026-10-07T00:00:06+00:00",
            "event": "research_run_completed",
            "campaign_id": "campaign-1",
            "research_run_id": "run-1",
            "campaign_name": "Fintech",
            "qualified_count": 1,
            "target_count": 1,
            "target_reached": True,
        },
        event("web_search_started", "other-run", search_phase="discovery"),
        event(
            "web_search_usage_reported",
            "other-run",
            usage_amount=99,
            usage_unit="credits",
            usage_is_actual=True,
        ),
    ]
    events[-2]["timestamp"] = "2026-10-07T01:00:00+00:00"
    events[-2]["campaign_id"] = "campaign-2"
    events[-1]["timestamp"] = "2026-10-07T01:00:00+00:00"
    events[-1]["campaign_id"] = "campaign-2"

    run_id, campaign_id, selected = research_report.select_run_events(
        events, run_id="run-1"
    )
    usage = research_report.aggregate_run(selected, campaign_id, run_id)

    assert run_id == "run-1"
    assert campaign_id == "campaign-1"
    assert len(selected) == 9
    assert usage.search_calls == 1
    assert usage.fetch_attempts == 1
    assert usage.qualified_companies == 1
    assert usage.actual_search_credits == 2
    assert usage.search_credits_per_qualified == 2


def test_missing_historical_event_families_render_as_unavailable() -> None:
    events = [
        {
            "timestamp": "2026-10-07T00:00:00+00:00",
            "event": "research_workflow_started",
            "campaign_id": "campaign-1",
        },
        {
            "timestamp": "2026-10-07T00:00:01+00:00",
            "event": "research_run_completed",
            "campaign_id": "campaign-1",
            "research_run_id": "legacy-run",
            "campaign_name": "Legacy",
        },
    ]

    _, campaign_id, selected = research_report.select_run_events(events)
    usage = research_report.aggregate_run(selected, campaign_id, "legacy-run")
    output = research_report.render_report(usage)

    assert usage.search_calls is None
    assert usage.qualification_extraction_calls is None
    assert usage.actual_search_credits is None
    assert usage.qualified_companies is None
    assert "Search calls" in output and "N/A" in output
    assert "Fact extraction calls" in output and "N/A" in output


def test_ambiguous_legacy_boundaries_do_not_mix_campaign_events() -> None:
    events = [
        {
            "timestamp": "2026-10-07T00:00:00+00:00",
            "event": "research_workflow_started",
            "campaign_id": "campaign-1",
        },
        {
            "timestamp": "2026-10-07T00:00:01+00:00",
            "event": "research_workflow_started",
            "campaign_id": "campaign-1",
        },
        {
            "timestamp": "2026-10-07T00:00:02+00:00",
            "event": "web_search_started",
            "campaign_id": "campaign-1",
        },
        {
            "timestamp": "2026-10-07T00:00:03+00:00",
            "event": "research_run_completed",
            "campaign_id": "campaign-1",
            "research_run_id": "legacy-run",
        },
    ]

    _, _, selected = research_report.select_run_events(events, run_id="legacy-run")

    assert selected == [events[-1]]


def test_no_completed_run_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="No completed"):
        research_report.select_run_events([])
