"""Application-level LLM workload roles."""

from enum import StrEnum


class LLMRole(StrEnum):
    """Select an explicitly configured LLM workload."""

    RESEARCH = "research"
    EXTRACTION = "extraction"
    OBLIGATION_GENERATION = "obligation_generation"
    EXPLORATION_QUERY_GENERATION = "exploration_query_generation"
    EXPLORATION_EVIDENCE_EXTRACTION = "exploration_evidence_extraction"
    EXPLORATION_FACT_EXTRACTION = "exploration_fact_extraction"
