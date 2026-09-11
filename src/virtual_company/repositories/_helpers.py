"""Shared utilities for repository implementations."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any


def create_values(data: object) -> dict[str, Any]:
    """Convert a create DTO to model keyword arguments, omitting unset defaults."""
    return {name: value for name, value in asdict(data).items() if value is not None}


def apply_updates(model: object, data: object) -> None:
    """Apply explicitly supplied update DTO values to a mapped model."""
    for name, value in asdict(data).items():
        if value is not None:
            setattr(model, name, value)
