"""Research workflow identity matching helpers."""

from __future__ import annotations

import re

_LEGAL_SUFFIX_PATTERN = re.compile(
    r"(?:,?\s+)(?:pty\.?\s+ltd\.?|proprietary\s+limited|limited|ltd\.?)$",
    re.IGNORECASE,
)


def normalize_company_name(value: str) -> str:
    """Return a Research candidate identity key without a common legal suffix."""
    normalized = " ".join(value.strip().casefold().split())
    return _LEGAL_SUFFIX_PATTERN.sub("", normalized).strip()
