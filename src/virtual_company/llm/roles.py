"""Application-level LLM workload roles."""

from enum import StrEnum


class LLMRole(StrEnum):
    """Select an explicitly configured LLM workload."""

    RESEARCH = "research"
    EXTRACTION = "extraction"
