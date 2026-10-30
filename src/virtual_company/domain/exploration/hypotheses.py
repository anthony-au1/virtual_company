"""Validated company hypotheses derived from Exploration Facts."""

from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExplorationHypothesis(BaseModel):
    """A plausible business implication supported by company Facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exploration_company_id: UUID
    statement: str = Field(min_length=1, max_length=2_000)
    fact_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("statement")
    @classmethod
    def normalize_statement(cls, value: str) -> str:
        normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()
        if not normalized:
            raise ValueError("statement must not be blank")
        return normalized

    @field_validator("fact_ids")
    @classmethod
    def keep_unique_fact_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(dict.fromkeys(value))
