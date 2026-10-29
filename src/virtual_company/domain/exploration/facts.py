"""Validated company facts derived from Exploration Evidence."""

from __future__ import annotations

import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExplorationFact(BaseModel):
    """A company-centered factual proposition with Evidence support."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exploration_company_id: UUID
    statement: str = Field(min_length=1, max_length=2_000)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("statement")
    @classmethod
    def normalize_statement(cls, value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized:
            raise ValueError("statement must not be blank")
        return normalized

    @field_validator("evidence_ids")
    @classmethod
    def keep_unique_evidence_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(dict.fromkeys(value))
