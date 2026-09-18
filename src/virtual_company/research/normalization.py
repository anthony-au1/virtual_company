"""Normalization helpers shared by research persistence and workflows."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_LEGAL_SUFFIX_PATTERN = re.compile(
    r"(?:,?\s+)(?:pty\.?\s+ltd\.?|proprietary\s+limited|limited|ltd\.?)$",
    re.IGNORECASE,
)


def normalize_domain(value: str | None) -> str | None:
    """Return a comparable lowercase domain without a leading ``www.``."""
    if not value:
        return None

    candidate = value.strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    hostname = parsed.hostname
    if hostname is None:
        return None
    return hostname.lower().removeprefix("www.")


def normalize_url(value: str) -> str:
    """Return a stable comparison key for search-result URLs."""
    parsed = urlsplit(value.strip())
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    scheme = parsed.scheme.lower()
    if not hostname:
        return value.strip()
    port = parsed.port
    netloc = hostname
    if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
        netloc = f"{hostname}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def normalize_company_name(value: str) -> str:
    """Return a conservative comparison key for obvious company-name variants."""
    normalized = " ".join(value.strip().casefold().split())
    return _LEGAL_SUFFIX_PATTERN.sub("", normalized).strip()
