"""Versioned prompt contract for Exploration obligation generation."""

from __future__ import annotations

import json

from virtual_company.llm.prompts import PromptIdentity

GENERATE_EXPLORATION_OBLIGATIONS_PROMPT = PromptIdentity(
    "generate_exploration_obligations", "v2"
)


def generate_exploration_obligations_system_prompt() -> str:
    """Return the domain and output guidance for obligation generation."""
    return (
        "You derive research obligations for an Exploration. Research has already discovered and "
        "qualified the companies; Exploration investigates companies selected from those Research "
        "results. The specific selected companies are intentionally not provided during obligation "
        "generation. The business context is free-text describing the user's business purpose, "
        "situation, capabilities, goals, constraints, and what they want to learn; interpret it "
        "holistically without requiring a fixed template. Generate shared questions or conditions "
        "that can later be evaluated for each selected company. Each obligation must establish "
        "something about a selected company in order to address the Business Context, and must be "
        "reusable across the selected company set without assuming facts about named companies. "
        "Exploration does not discover, identify, shortlist, rank, or select companies. Do not "
        "generate obligations whose purpose is to find companies, identify organisations, decide "
        "which companies qualify, or discover prospects. Market, regulatory, industry, or "
        "technology information may appear only when relevant to establishing something about a "
        "selected company. State WHAT must be established, not HOW to search. Do not write search "
        "instructions or workflow actions, facts, answers, conclusions, or hypotheses. Do not "
        "invent requirements unsupported by the context. Create distinct meaningful obligations; "
        "avoid unnecessary overlap and trivial micro-questions. Return the minimum useful set. "
        "max_obligations is a hard ceiling, not a target: do not pad and return no more than that "
        "number. Zero obligations is valid when the context supports no meaningful company-"
        "applicable requirement. Return only the requested structured output and no reasoning."
    )


def generate_exploration_obligations_user_prompt(
    business_context: str, max_obligations: int
) -> str:
    """Serialize both generator inputs without interpreting the business context."""
    return json.dumps(
        {
            "business_context": business_context,
            "max_obligations": max_obligations,
        },
        ensure_ascii=False,
    )
