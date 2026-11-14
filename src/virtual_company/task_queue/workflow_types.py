"""Registered business workflow identifiers carried by Taskiq messages."""

from enum import StrEnum


class WorkflowType(StrEnum):
    RESEARCH = "research"
    EXPLORATION = "exploration"
