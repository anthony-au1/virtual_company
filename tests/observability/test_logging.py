"""Tests for safe structured logging helpers."""

from __future__ import annotations

import json
import logging

from virtual_company.observability.logging import JsonFormatter


def test_json_formatter_keeps_correlation_context_and_redacts_secrets() -> None:
    record = logging.LogRecord(
        "virtual_company", logging.INFO, __file__, 1, "workflow_node_completed", (), None
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
