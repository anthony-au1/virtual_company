"""Shared metadata for locally managed, versioned prompts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptIdentity:
    """Stable name and version recorded for a prompt invocation."""

    name: str
    version: str
