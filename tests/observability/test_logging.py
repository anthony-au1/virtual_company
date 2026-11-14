"""Tests for safe structured logging helpers."""

from __future__ import annotations

import json
import logging

import pytest

from virtual_company.observability.logging import ConsoleFormatter, JsonFormatter
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


def test_console_formatter_without_context_keeps_standard_fields() -> None:
    record = logging.LogRecord(
        "virtual_company.worker", logging.WARNING, __file__, 1, "worker_stopped", (), None
    )

    rendered = ConsoleFormatter("%(asctime)s %(levelname)s %(name)s %(message)s").format(
        record
    )

    assert "WARNING virtual_company.worker worker_stopped" in rendered
    assert "context=" not in rendered


def test_console_formatter_includes_sorted_redacted_correlation_context() -> None:
    record = logging.LogRecord(
        "virtual_company.worker", logging.INFO, __file__, 1, "workflow_started", (), None
    )
    record.context = {
        "workflow_type": "research",
        "run_id": "run-1",
        "execution_id": "execution-1",
        "task_id": "task-1",
        "credentials": {"api_key": "never-log"},
    }

    rendered = ConsoleFormatter("%(asctime)s %(levelname)s %(name)s %(message)s").format(
        record
    )

    assert 'context={"credentials": {"api_key": "[REDACTED]"}' in rendered
    assert '"execution_id": "execution-1"' in rendered
    assert '"run_id": "run-1"' in rendered
    assert '"task_id": "task-1"' in rendered
    assert "never-log" not in rendered


def test_formatters_include_exception_information() -> None:
    try:
        raise RuntimeError("safe exception detail")
    except RuntimeError:
        record = logging.LogRecord(
            "virtual_company.worker",
            logging.ERROR,
            __file__,
            1,
            "workflow_failed",
            (),
            __import__("sys").exc_info(),
        )

    assert "RuntimeError: safe exception detail" in ConsoleFormatter(
        "%(levelname)s %(name)s %(message)s"
    ).format(record)
    payload = json.loads(JsonFormatter().format(record))
    assert "RuntimeError: safe exception detail" in payload["exception"]


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
