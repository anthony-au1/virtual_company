"""Lifecycle status values for Exploration runs."""

from enum import StrEnum


class ExplorationRunStatus(StrEnum):
    READY = "READY"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
