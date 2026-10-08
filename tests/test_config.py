"""Tests for environment-backed application settings."""

from __future__ import annotations

import pytest

from virtual_company.config import Settings


def test_json_logging_is_default_for_machine_readable_research_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOG_FORMAT", raising=False)

    assert Settings().log_format == "json"


def test_research_limit_is_not_an_environment_setting() -> None:
    assert "research_max_candidate_pool_size" not in Settings.model_fields
