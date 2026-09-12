"""Normalization helpers shared by research persistence and workflows."""

from __future__ import annotations

from urllib.parse import urlsplit


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
    path = parsed.path.rstrip("/")
    return f"{scheme}://{hostname}{path}" if hostname else value.strip()
