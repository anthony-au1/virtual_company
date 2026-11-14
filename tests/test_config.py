"""Tests for environment-backed application settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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


def test_exploration_fact_extraction_limits_have_independent_defaults() -> None:
    settings = Settings()

    assert settings.exploration_fact_extraction_concurrency == 3
    assert settings.exploration_fact_extraction_timeout_seconds == 60
    assert settings.exploration_fact_extraction_max_evidence_per_chunk == 20
    assert settings.exploration_fact_extraction_max_chars_per_chunk == 30_000


def test_taskiq_settings_have_safe_defaults_and_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TASKIQ_REDIS_URL", raising=False)
    monkeypatch.delenv("TASKIQ_IDLE_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("TASKIQ_WORKER_CONCURRENCY", raising=False)

    defaults = Settings()
    assert defaults.taskiq_redis_url == "redis://localhost:6379/0"
    assert defaults.taskiq_stream_name == "virtual-company-tasks"
    assert defaults.taskiq_consumer_group == "virtual-company-workers"
    assert defaults.taskiq_idle_timeout_ms == 86_400_000
    assert defaults.taskiq_reclaim_lock_timeout_seconds == 30
    assert defaults.taskiq_worker_concurrency == 1
    assert defaults.taskiq_worker_shutdown_grace_seconds == 3600
    assert defaults.taskiq_heartbeat_interval_seconds == 30
    assert defaults.taskiq_running_stale_after_seconds == 3600
    assert defaults.taskiq_queued_stale_after_seconds == 86400
    assert defaults.taskiq_reconciliation_interval_seconds == 30
    assert defaults.taskiq_reconciliation_enabled is True

    monkeypatch.setenv("TASKIQ_REDIS_URL", "redis://example:6379/2")
    monkeypatch.setenv("TASKIQ_IDLE_TIMEOUT_MS", "120000")
    monkeypatch.setenv("TASKIQ_WORKER_CONCURRENCY", "3")
    configured = Settings()
    assert configured.taskiq_redis_url == "redis://example:6379/2"
    assert configured.taskiq_idle_timeout_ms == 120_000
    assert configured.taskiq_worker_concurrency == 3


@pytest.mark.parametrize(
    "settings",
    [
        {"taskiq_heartbeat_interval_seconds": 1201},
        {"taskiq_queued_stale_after_seconds": 20},
    ],
)
def test_inconsistent_taskiq_lifecycle_settings_are_rejected(settings) -> None:
    with pytest.raises(ValidationError):
        Settings(**settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("taskiq_idle_timeout_ms", 0),
        ("taskiq_reclaim_lock_timeout_seconds", 0),
        ("taskiq_worker_concurrency", 0),
        ("taskiq_worker_concurrency", 101),
        ("taskiq_worker_shutdown_grace_seconds", 0),
    ],
)
def test_invalid_taskiq_settings_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_exploration_hypothesis_maximum_default_and_environment_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXPLORATION_HYPOTHESIS_MAX_HYPOTHESES", raising=False)
    assert Settings().exploration_hypothesis_max_hypotheses == 10

    monkeypatch.setenv("EXPLORATION_HYPOTHESIS_MAX_HYPOTHESES", "15")
    assert Settings().exploration_hypothesis_max_hypotheses == 15


@pytest.mark.parametrize("value", [0, 21, -1, True, 1.5, "bad"])
def test_invalid_exploration_hypothesis_maximum_fails_settings_validation(value) -> None:
    with pytest.raises(ValidationError):
        Settings(exploration_hypothesis_max_hypotheses=value)
