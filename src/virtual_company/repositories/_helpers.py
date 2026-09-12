"""Shared utilities for repository implementations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def create_values(data: BaseModel) -> dict[str, Any]:
    """Convert a create DTO to model keyword arguments, omitting unset defaults."""
    return data.model_dump(exclude_none=True)


def apply_updates(model: object, data: BaseModel) -> None:
    """Apply explicitly supplied update DTO values to a mapped model."""
    for field_name in data.model_fields_set:
        setattr(model, field_name, getattr(data, field_name))
