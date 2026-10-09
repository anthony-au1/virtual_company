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


def test_fetch_success_targets_are_configurable_and_keep_existing_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COMPANY_RESEARCH_MAX_FETCHES_PER_COMPANY", raising=False)
    monkeypatch.delenv(
        "COMPANY_RESEARCH_FOLLOWUP_MAX_FETCHES_PER_COMPANY", raising=False
    )
    defaults = Settings()
    assert defaults.company_research_successful_fetch_target_per_company == 5
    assert defaults.company_research_followup_successful_fetch_target_per_company == 3

    monkeypatch.setenv("COMPANY_RESEARCH_SUCCESSFUL_FETCH_TARGET_PER_COMPANY", "7")
    monkeypatch.setenv(
        "COMPANY_RESEARCH_FOLLOWUP_SUCCESSFUL_FETCH_TARGET_PER_COMPANY", "4"
    )
    configured = Settings()
    assert configured.company_research_successful_fetch_target_per_company == 7
    assert configured.company_research_followup_successful_fetch_target_per_company == 4
