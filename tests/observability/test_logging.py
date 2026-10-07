"""Tests for safe structured logging helpers."""

from __future__ import annotations

import json
import logging

import pytest

from virtual_company.observability.logging import JsonFormatter
from virtual_company.observability.runtime import Observability


def test_json_formatter_keeps_correlation_context_and_redacts_secrets() -> None:
    record = logging.LogRecord(
        "virtual_company",
        logging.INFO,
        __file__,
        1,
        "workflow_node_completed",
        (),
        None,
    )
    record.context = {
        "campaign_id": "campaign-1",
        "research_run_id": "run-1",
        "workflow_node": "discover_companies",
        "api_key": "must-not-appear",
    }

    payload = json.loads(JsonFormatter().format(record))

    assert payload["campaign_id"] == "campaign-1"
    assert payload["research_run_id"] == "run-1"
    assert payload["workflow_node"] == "discover_companies"
    assert payload["api_key"] == "[REDACTED]"


def test_clearing_context_prevents_a_previous_run_id_leaking(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observability = Observability()
    observability.bind(research_run_id="previous-run")
    observability.clear_context()
    observability.bind(campaign_id="campaign-2", workflow="company_research")

    with caplog.at_level(logging.INFO, logger="virtual_company"):
        observability.event("research_run_started")

    assert caplog.records[-1].context == {
        "campaign_id": "campaign-2",
        "workflow": "company_research",
    }
