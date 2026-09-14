"""Lightweight application observability primitives."""

from virtual_company.observability.runtime import (
    Observability,
    configure_observability,
    get_observability,
    shutdown_observability,
)

__all__ = [
    "Observability",
    "configure_observability",
    "get_observability",
    "shutdown_observability",
]
