"""ExplorationRun creation DTO validation."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from virtual_company.repositories.dtos import ExplorationRunCreate


def test_exploration_run_create_requires_research_run_id() -> None:
    with pytest.raises(ValidationError, match="research_run_id"):
        ExplorationRunCreate(exploration_id=uuid4(), status="RUNNING")


def test_exploration_run_create_accepts_research_run_id() -> None:
    exploration_id = uuid4()
    research_run_id = uuid4()

    run = ExplorationRunCreate(
        exploration_id=exploration_id,
        research_run_id=research_run_id,
        status="RUNNING",
    )

    assert run.exploration_id == exploration_id
    assert run.research_run_id == research_run_id
