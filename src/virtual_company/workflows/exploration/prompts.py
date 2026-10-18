"""Versioned prompt contract for Exploration obligation generation."""

from __future__ import annotations

import json

from virtual_company.llm.prompts import PromptIdentity

GENERATE_EXPLORATION_OBLIGATIONS_PROMPT = PromptIdentity(
    "generate_exploration_obligations", "v1"
)


def generate_exploration_obligations_system_prompt() -> str:
    """Return the domain and output guidance for obligation generation."""
    return (
        "You derive research obligations for an Exploration. The business context is a free-text "
        "description of the user's business situation, capabilities, goals, constraints, and/or "
        "question to investigate; those elements are optional and the context must be interpreted "
        "holistically without requiring a fixed template. An obligation is a concrete question or "
        "condition that should be established through external evidence to address that context. "
        "Obligations belong to the Exploration and are not inherently company-specific: use the "
        "natural subject implied by the context, which may be organisations, markets, regulations, "
        "technologies, or another relevant subject. State WHAT must be established, not a search "
        "or workflow action. Do not write search instructions, facts, answers, conclusions, or "
        "hypotheses. Do not invent requirements unsupported by the context. Create distinct, "
        "individually meaningful requirements; avoid overlap and redundancy, but do not split the "
        "context into trivial micro-questions. Return the minimum useful set. max_obligations is a "
        "hard ceiling, not a target: never pad the result to reach it, and return no more than that "
        "number. Zero obligations is valid when the context supports no meaningful research "
        "requirement. Return only the requested structured output and do not include reasoning."
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
