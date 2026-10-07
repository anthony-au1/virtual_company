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


def test_research_max_candidate_pool_size_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_MAX_CANDIDATE_POOL_SIZE", "23")

    settings = Settings()

    assert settings.research_max_candidate_pool_size == 23


@pytest.mark.parametrize("value", ["0", "-1"])
def test_research_max_candidate_pool_size_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("RESEARCH_MAX_CANDIDATE_POOL_SIZE", value)

    with pytest.raises(ValidationError):
        Settings()
