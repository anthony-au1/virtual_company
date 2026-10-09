"""Aggregate and display Research Workflow events from Docker Compose logs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ResearchUsage:
    """Run-level usage values that can be derived reliably from events."""

    campaign_id: str
    campaign_name: str
    run_id: str
    run_timestamp: str
    target_count: int | None
    max_companies_to_research: int | None
    target_reached: bool | None
    stop_reason: str | None
    discovered_candidates: int | None
    researched_companies: int | None
    qualified_companies: int | None
    insufficient_evidence_companies: int | None
    initial_queries: int | None
    followup_queries: int | None
    discovery_queries: int | None
    search_calls: int | None
    search_results: int | None
    search_results_by_phase: dict[str, int]
    sources_selected: int | None
    fetch_attempts: int | None
    fetch_successes: int | None
    fetch_failures: int | None
    fetch_retries: int | None
    fetch_batches: int | None
    fetch_target_reached_batches: int | None
    fetch_target_reached_rate: float | None
    fetch_candidate_exhaustions: int | None
    fetch_additional_candidate_attempts: int | None
    fetch_attempts_per_success: float | None
    qualification_extraction_calls: int | None
    qualification_extraction_failures: int | None
    qualification_extraction_retries: int | None
    llm_calls: int | None
    llm_failures: int | None
    llm_retries: int | None
    input_tokens: int | None
    output_tokens: int | None
    search_provider: str
    search_modes: str
    actual_search_credits: float | None
    estimated_search_credits: float | None
    credits_by_phase: dict[str, float]
    estimated_credits_by_phase: dict[str, float]
    calls_by_phase: dict[str, int]

    @property
    def search_credits_per_researched(self) -> float | None:
        return _ratio(self.actual_search_credits, self.researched_companies)

    @property
    def search_credits_per_qualified(self) -> float | None:
        return _ratio(self.actual_search_credits, self.qualified_companies)

    @property
    def search_calls_per_researched(self) -> float | None:
        if self.search_calls is None:
            return None
        return _ratio(float(self.search_calls), self.researched_companies)

    @property
    def qualified_per_researched(self) -> float | None:
        if self.qualified_companies is None:
            return None
        return _ratio(float(self.qualified_companies), self.researched_companies)


def _ratio(numerator: float | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def parse_json_events(output: str) -> list[dict[str, Any]]:
    """Parse JSON objects embedded in Compose-prefixed log lines."""
    events: list[dict[str, Any]] = []
    for line in output.splitlines():
        start = line.find("{")
        if start < 0:
            continue
        try:
            event = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and isinstance(event.get("event"), str):
            events.append(event)
    return events


def select_run_events(
    events: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    campaign_id: str | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Select an explicit run or the latest completed run, optionally by campaign."""
    completions = [
        event
        for event in events
        if event.get("event") == "research_run_completed"
        and event.get("research_run_id")
        and (campaign_id is None or event.get("campaign_id") == campaign_id)
    ]
    if run_id is None:
        if not completions:
            raise ValueError(
                "No completed Research Workflow run found in Docker logs. "
                "Check LOG_FORMAT=json and that the app container retains the run logs."
            )
        completion = max(
            enumerate(completions),
            key=lambda indexed: (str(indexed[1].get("timestamp", "")), indexed[0]),
        )[1]
        run_id = str(completion["research_run_id"])
        campaign_id = str(completion.get("campaign_id", ""))
    matching = [
        event
        for event in events
        if event.get("research_run_id") == run_id
        and (campaign_id is None or event.get("campaign_id") == campaign_id)
    ]
    if not matching:
        raise ValueError(f"No events found for Research Workflow run {run_id}")
    resolved_campaign_id = campaign_id or str(matching[0].get("campaign_id", ""))
    # Older workflow events had campaign correlation only. Attribute those
    # events only when lifecycle timestamps uniquely identify the selected run.
    correlated_operations = [
        event
        for event in matching
        if event.get("event") not in {"research_run_completed", "research_run_started"}
    ]
    if not correlated_operations:
        completion = next(
            (
                event
                for event in matching
                if event.get("event") == "research_run_completed"
            ),
            None,
        )
        if completion is not None:
            legacy_events = _legacy_campaign_run_events(
                events, resolved_campaign_id, completion
            )
            if legacy_events is not None:
                matching = legacy_events
    return run_id, resolved_campaign_id, matching


def _legacy_campaign_run_events(
    events: list[dict[str, Any]], campaign_id: str, completion: dict[str, Any]
) -> list[dict[str, Any]] | None:
    """Return campaign-only events when lifecycle timestamps identify one run."""
    completed_at = _timestamp(completion.get("timestamp"))
    if completed_at is None:
        return None
    campaign_events = [
        event for event in events if str(event.get("campaign_id", "")) == campaign_id
    ]
    previous_completions = [
        parsed
        for event in campaign_events
        if event.get("event") == "research_run_completed"
        and (parsed := _timestamp(event.get("timestamp"))) is not None
        and parsed < completed_at
    ]
    lower_bound = max(previous_completions, default=None)
    starts = [
        event
        for event in campaign_events
        if event.get("event") == "research_workflow_started"
        and (started_at := _timestamp(event.get("timestamp"))) is not None
        and started_at < completed_at
        and (lower_bound is None or started_at > lower_bound)
    ]
    if len(starts) != 1:
        return None
    started_at = _timestamp(starts[0].get("timestamp"))
    if started_at is None:
        return None
    overlapping_runs = [
        event
        for event in campaign_events
        if event.get("event") == "research_run_started"
        and event.get("research_run_id") != completion.get("research_run_id")
        and (event_at := _timestamp(event.get("timestamp"))) is not None
        and started_at <= event_at <= completed_at
    ]
    if overlapping_runs:
        return None
    return [
        event
        for event in campaign_events
        if (event_at := _timestamp(event.get("timestamp"))) is not None
        and started_at <= event_at <= completed_at
    ]


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def aggregate_run(
    events: list[dict[str, Any]], campaign_id: str, run_id: str
) -> ResearchUsage:
    """Aggregate a filtered event list without estimating unavailable values."""
    completion = next(
        (
            event
            for event in reversed(events)
            if event.get("event") == "research_run_completed"
        ),
        {},
    )
    initial_queries = _sum_if_observed(
        events, "company_research_queries_generated", "query_count"
    )
    followup_queries = _sum_if_observed(
        events, "followup_company_queries_generated", "query_count"
    )

    search_events = [
        event for event in events if event.get("event") == "web_search_started"
    ]
    calls_by_phase = _count_by_phase(search_events)
    result_events = [
        event for event in events if event.get("event") == "web_search_completed"
    ]
    search_results = sum(_integer(event.get("result_count")) for event in result_events)
    search_results_by_phase: dict[str, int] = {}
    for event in result_events:
        phase = str(event.get("search_phase") or "unattributed")
        search_results_by_phase[phase] = search_results_by_phase.get(
            phase, 0
        ) + _integer(event.get("result_count"))
    actual_credits: float | None = None
    estimated_credits: float | None = None
    credits_by_phase: dict[str, float] = {}
    estimated_credits_by_phase: dict[str, float] = {}
    credit_usage_events = [
        event
        for event in events
        if event.get("event") == "web_search_usage_reported"
        and event.get("usage_unit") == "credits"
        and isinstance(event.get("usage_amount"), (int, float))
    ]
    actual_usage_events = [
        event for event in credit_usage_events if event.get("usage_is_actual") is True
    ]
    estimated_usage_events = [
        event for event in credit_usage_events if event.get("usage_is_actual") is False
    ]
    if actual_usage_events:
        actual_credits = sum(
            float(event["usage_amount"]) for event in actual_usage_events
        )
        for event in actual_usage_events:
            phase = str(event.get("search_phase") or "unattributed")
            credits_by_phase[phase] = credits_by_phase.get(phase, 0.0) + float(
                event["usage_amount"]
            )
    if estimated_usage_events:
        estimated_credits = sum(
            float(event["usage_amount"]) for event in estimated_usage_events
        )
        for event in estimated_usage_events:
            phase = str(event.get("search_phase") or "unattributed")
            estimated_credits_by_phase[phase] = estimated_credits_by_phase.get(
                phase, 0.0
            ) + float(event["usage_amount"])

    selected_events = [
        event for event in events if event.get("event") == "company_sources_selected"
    ]
    fetch_started = [
        event for event in events if event.get("event") == "web_fetch_started"
    ]
    fetch_successes = sum(
        event.get("event") == "web_fetch_completed" for event in events
    )
    fetch_failures = sum(event.get("event") == "web_fetch_failed" for event in events)
    fetch_batches = [
        event
        for event in events
        if event.get("event") == "company_sources_fetch_batch_completed"
    ]
    target_reached_batches = sum(
        event.get("target_reached") is True for event in fetch_batches
    )
    fetch_success_count = sum(
        _integer(event.get("fetch_successes")) for event in fetch_batches
    )
    fetch_attempt_count = sum(
        _integer(event.get("fetch_attempts")) for event in fetch_batches
    )
    fetch_retries = sum(
        event.get("event") == "web_fetch_started" and event.get("fetch_retry") is True
        for event in events
    )
    extraction_successes = sum(
        event.get("event") == "qualification_facts_extracted" for event in events
    )
    extraction_failures = sum(
        event.get("event") == "qualification_fact_extraction_failed" for event in events
    )
    extraction_retries = sum(
        event.get("event") == "qualification_fact_extraction_retry" for event in events
    )
    extraction_events = [
        event
        for event in events
        if event.get("event")
        in {
            "qualification_facts_extracted",
            "qualification_fact_extraction_failed",
            "qualification_fact_extraction_retry",
        }
    ]
    qualification_status_by_company = {
        str(event["company_id"]): event.get("qualification_status")
        for event in events
        if event.get("event") == "company_qualified"
        and event.get("company_id") is not None
    }
    qualified_from_events = sum(
        status == "QUALIFIED" for status in qualification_status_by_company.values()
    )
    insufficient = sum(
        status == "INSUFFICIENT_EVIDENCE"
        for status in qualification_status_by_company.values()
    )
    company_ids = {
        str(event["company_id"])
        for event in selected_events
        if event.get("company_id") is not None
    }
    providers = sorted(
        {
            str(event["provider"])
            for event in search_events
            if event.get("provider") is not None
        }
    )
    search_modes = sorted(
        {
            str(event.get("search_depth") or event.get("search_mode"))
            for event in search_events
            if event.get("search_depth") or event.get("search_mode")
        }
    )
    discovered = next(
        (
            _integer(event.get("ranked_candidate_count"))
            for event in reversed(events)
            if event.get("event") == "company_candidates_ranked"
        ),
        None,
    )
    fetch_outcome_events = any(
        event.get("event") in {"web_fetch_completed", "web_fetch_failed"}
        for event in events
    )
    llm_events_present = any(
        event.get("event") in {"llm_request_started", "llm_request_failed"}
        for event in events
    )
    qualification_events_present = bool(qualification_status_by_company)
    search_calls_value = len(search_events) if search_events else None
    search_results_value = search_results if result_events else None
    return ResearchUsage(
        campaign_id=campaign_id,
        campaign_name=str(completion.get("campaign_name") or "N/A"),
        run_id=run_id,
        run_timestamp=str(completion.get("timestamp") or "N/A"),
        target_count=_optional_integer(completion.get("target_count")),
        max_companies_to_research=_optional_integer(
            completion.get("max_companies_to_research")
        ),
        target_reached=(
            completion.get("target_reached")
            if isinstance(completion.get("target_reached"), bool)
            else None
        ),
        stop_reason=(
            str(completion["stop_reason"]) if completion.get("stop_reason") else None
        ),
        discovered_candidates=discovered,
        researched_companies=(
            _optional_integer(completion.get("companies_researched"))
            if _optional_integer(completion.get("companies_researched")) is not None
            else len(company_ids)
            if selected_events
            else None
        ),
        qualified_companies=(
            _optional_integer(completion.get("qualified_count"))
            if _optional_integer(completion.get("qualified_count")) is not None
            else qualified_from_events
            if qualification_events_present
            else None
        ),
        insufficient_evidence_companies=(
            insufficient if qualification_events_present else None
        ),
        initial_queries=initial_queries,
        followup_queries=followup_queries,
        discovery_queries=_sum_if_observed(
            events, "search_queries_generated", "query_count"
        ),
        search_calls=search_calls_value,
        search_results=search_results_value,
        search_results_by_phase=search_results_by_phase,
        sources_selected=(
            _sum(events, "company_sources_selected", "selected_source_count")
            if selected_events
            else None
        ),
        fetch_attempts=len(fetch_started) if fetch_started else None,
        fetch_successes=fetch_successes if fetch_outcome_events else None,
        fetch_failures=fetch_failures if fetch_outcome_events else None,
        fetch_retries=fetch_retries if fetch_started else None,
        fetch_batches=len(fetch_batches) if fetch_batches else None,
        fetch_target_reached_batches=(
            target_reached_batches if fetch_batches else None
        ),
        fetch_target_reached_rate=(
            target_reached_batches / len(fetch_batches) if fetch_batches else None
        ),
        fetch_candidate_exhaustions=(
            sum(event.get("candidates_exhausted") is True for event in fetch_batches)
            if fetch_batches
            else None
        ),
        fetch_additional_candidate_attempts=(
            sum(
                _integer(event.get("additional_candidate_attempts"))
                for event in fetch_batches
            )
            if fetch_batches
            else None
        ),
        fetch_attempts_per_success=(
            _ratio(float(fetch_attempt_count), fetch_success_count)
            if fetch_batches
            else None
        ),
        qualification_extraction_calls=(
            extraction_successes + extraction_failures if extraction_events else None
        ),
        qualification_extraction_failures=(
            extraction_failures if extraction_events else None
        ),
        qualification_extraction_retries=(
            extraction_retries if extraction_events else None
        ),
        llm_calls=(
            sum(event.get("event") == "llm_request_started" for event in events)
            if llm_events_present
            else None
        ),
        llm_failures=(
            sum(event.get("event") == "llm_request_failed" for event in events)
            if llm_events_present
            else None
        ),
        llm_retries=extraction_retries if extraction_events else None,
        input_tokens=None,
        output_tokens=None,
        search_provider=(", ".join(providers) if providers else "N/A"),
        search_modes=(", ".join(search_modes) if search_modes else "N/A"),
        actual_search_credits=actual_credits,
        estimated_search_credits=estimated_credits,
        credits_by_phase=credits_by_phase,
        estimated_credits_by_phase=estimated_credits_by_phase,
        calls_by_phase=calls_by_phase,
    )


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _optional_integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _sum(events: list[dict[str, Any]], name: str, field: str) -> int:
    return sum(
        _integer(event.get(field)) for event in events if event.get("event") == name
    )


def _sum_if_observed(events: list[dict[str, Any]], name: str, field: str) -> int | None:
    if not any(event.get("event") == name for event in events):
        return None
    return _sum(events, name, field)


def _count_by_phase(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        phase = str(event.get("search_phase") or "unattributed")
        counts[phase] = counts.get(phase, 0) + 1
    return counts


def render_report(usage: ResearchUsage) -> str:
    """Render the complete human-readable run summary."""
    lines = [
        "Research Run",
        "=" * 48,
        f"Campaign: {usage.campaign_name}",
        f"Campaign ID: {usage.campaign_id}",
        f"Run ID: {usage.run_id}",
        f"Completed: {usage.run_timestamp}",
        "",
        "DISCOVERY",
        _metric("Generated queries", usage.discovery_queries),
        _metric(
            "Search calls",
            usage.calls_by_phase.get("discovery", 0)
            if usage.search_calls is not None
            else None,
        ),
        _metric("Search results", _results_by_phase(usage, "discovery")),
        _metric("Candidates discovered", usage.discovered_candidates),
        "",
        "INVESTIGATION",
        _metric("Companies researched", usage.researched_companies),
        _metric("Research limit", usage.max_companies_to_research),
        _metric("Initial queries", usage.initial_queries),
        _metric("Follow-up queries", usage.followup_queries),
        _metric(
            "Investigation search calls",
            (
                usage.calls_by_phase.get("investigation", 0)
                + usage.calls_by_phase.get("followup", 0)
                if usage.search_calls is not None
                else None
            ),
        ),
        _metric(
            "Investigation search results",
            (
                usage.search_results_by_phase.get("investigation", 0)
                + usage.search_results_by_phase.get("followup", 0)
                if usage.search_results is not None
                else None
            ),
        ),
        _metric("Sources selected", usage.sources_selected),
        _metric("Fetch attempts", usage.fetch_attempts),
        _metric("Successful fetches", usage.fetch_successes),
        _metric("Failed fetches", usage.fetch_failures),
        _metric("Fetch retries", usage.fetch_retries),
        _metric("Fetch batches", usage.fetch_batches),
        _metric("Batches reaching fetch target", usage.fetch_target_reached_batches),
        _metric(
            "Fetch target reached rate", _percentage(usage.fetch_target_reached_rate)
        ),
        _metric("Candidate exhausted batches", usage.fetch_candidate_exhaustions),
        _metric(
            "Additional candidate attempts", usage.fetch_additional_candidate_attempts
        ),
        _metric(
            "Attempts per successful fetch", _display(usage.fetch_attempts_per_success)
        ),
        "",
        "QUALIFICATION",
        _metric("Qualified", usage.qualified_companies),
        _metric("Insufficient evidence", usage.insufficient_evidence_companies),
        _metric("Fact extraction calls", usage.qualification_extraction_calls),
        _metric("Fact extraction failures", usage.qualification_extraction_failures),
        _metric("Fact extraction retries", usage.qualification_extraction_retries),
        "",
        "USAGE / COST",
        _metric("Search provider", usage.search_provider),
        _metric("Search mode / depth", usage.search_modes),
        _metric("Actual search credits", _display(usage.actual_search_credits)),
        _metric("Estimated search credits", _display(usage.estimated_search_credits)),
        _metric("LLM calls", usage.llm_calls),
        _metric("LLM failures", usage.llm_failures),
        _metric("LLM retries (fact extraction)", usage.llm_retries),
        _metric("Input tokens", _token_display(usage.input_tokens)),
        _metric("Output tokens", _token_display(usage.output_tokens)),
        "",
        "EFFICIENCY",
        _metric(
            "Credits / researched company",
            _display(usage.search_credits_per_researched),
        ),
        _metric(
            "Credits / qualified company", _display(usage.search_credits_per_qualified)
        ),
        _metric(
            "Search calls / researched company",
            _display(usage.search_calls_per_researched),
        ),
        _metric(
            "Qualified / researched ratio", _display(usage.qualified_per_researched)
        ),
        "",
        "RESULT",
        _metric(
            "Target", usage.target_count if usage.target_count is not None else "N/A"
        ),
        _metric("Research limit", usage.max_companies_to_research),
        _metric("Companies researched", usage.researched_companies),
        _metric("Qualified", usage.qualified_companies),
        _metric("Target reached", _yes_no(usage.target_reached)),
        _metric("Stop reason", usage.stop_reason or "N/A"),
    ]
    return "\n".join(lines)


def render_cost_report(usage: ResearchUsage) -> str:
    """Render search usage with phase credits only when actually reported."""
    lines = [
        "Research Cost",
        "=" * 36,
        _metric("Search provider", usage.search_provider),
        _metric("Search mode / depth", usage.search_modes),
    ]
    if usage.actual_search_credits is not None:
        for phase in ("discovery", "investigation", "followup", "unattributed"):
            amount = usage.credits_by_phase.get(phase)
            if amount is not None:
                lines.append(_metric(f"{phase.title()} credits", _display(amount)))
        lines.append("-" * 36)
        lines.append(
            _metric("Total actual credits", _display(usage.actual_search_credits))
        )
    else:
        lines.append(_metric("Actual credits", "N/A (provider did not report usage)"))
    if usage.estimated_search_credits is not None:
        lines.append(
            _metric(
                "Estimated credits (not actual)",
                _display(usage.estimated_search_credits),
            )
        )
    for phase in ("discovery", "investigation", "followup", "unattributed"):
        if phase in usage.calls_by_phase:
            lines.append(
                _metric(f"{phase.title()} search calls", usage.calls_by_phase[phase])
            )
    lines.extend(
        [
            "",
            _metric("Companies researched", usage.researched_companies),
            _metric("Companies qualified", usage.qualified_companies),
            _metric(
                "Credits / researched", _display(usage.search_credits_per_researched)
            ),
            _metric(
                "Credits / qualified", _display(usage.search_credits_per_qualified)
            ),
        ]
    )
    return "\n".join(lines)


def _results_by_phase(usage: ResearchUsage, phase: str) -> int | None:
    if usage.search_results is None:
        return None
    return usage.search_results_by_phase.get(phase, 0)


def _metric(label: str, value: object) -> str:
    return f"{label:<34}{('N/A' if value is None else value):>14}"


def _display(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def _percentage(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def _token_display(value: int | None) -> str:
    return "N/A" if value is None else str(value)


def _yes_no(value: bool | None) -> str:
    return "YES" if value is True else "NO" if value is False else "N/A"


def read_compose_logs() -> str:
    """Return app container logs, retaining JSON payloads after Compose prefixes."""
    try:
        result = subprocess.run(
            ["docker", "compose", "logs", "--no-color", "--timestamps", "app"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise RuntimeError(f"Unable to read Docker Compose logs: {error}") from error
    if result.returncode:
        detail = result.stderr.strip() or "docker compose logs failed"
        raise RuntimeError(detail)
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view", choices=("summary", "cost", "log"))
    parser.add_argument("--run-id")
    parser.add_argument("--campaign-id")
    arguments = parser.parse_args(argv)
    try:
        events = parse_json_events(read_compose_logs())
        run_id, campaign_id, run_events = select_run_events(
            events, run_id=arguments.run_id, campaign_id=arguments.campaign_id
        )
        if arguments.view == "log":
            print(
                "\n".join(
                    json.dumps(event, indent=2, sort_keys=True) for event in run_events
                )
            )
        else:
            usage = aggregate_run(run_events, campaign_id, run_id)
            print(
                render_report(usage)
                if arguments.view == "summary"
                else render_cost_report(usage)
            )
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
