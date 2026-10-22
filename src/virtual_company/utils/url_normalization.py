"""Generic URL canonicalization helpers."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_QUERY_PARAMETER_PATTERN = re.compile(
    r"^(?:utm_[a-z0-9_]+|gclid|dclid|fbclid|msclkid)$", re.IGNORECASE
)


def normalize_domain(value: str | None) -> str | None:
    """Return a lowercase hostname without a leading ``www.``."""
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
    """Return a stable canonical key for a URL, preserving its query string."""
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


def normalize_fetch_url(value: str) -> str:
    """Return a conservative deduplication key for fetchable source URLs."""
    parsed = urlsplit(value.strip())
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    scheme = parsed.scheme.lower()
    if not hostname:
        return value.strip()
    port = parsed.port
    netloc = hostname
    if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
        netloc = f"{hostname}:{port}"
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not _TRACKING_QUERY_PARAMETER_PATTERN.fullmatch(key)
        ],
        doseq=True,
    )
    return urlunsplit((scheme, netloc, parsed.path.rstrip("/"), query, ""))


def sanitize_observability_url(value: str) -> str:
    """Return a bounded URL without user information, query values, or fragments."""
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname
        if hostname is None:
            return value.split("?", 1)[0].split("#", 1)[0][:500]
        host = f"[{hostname}]" if ":" in hostname else hostname
        port = parsed.port
        if port is not None and (parsed.scheme.lower(), port) not in {
            ("http", 80),
            ("https", 443),
        }:
            host = f"{host}:{port}"
        return urlunsplit((parsed.scheme.lower(), host, parsed.path, "", ""))[:500]
    except ValueError:
        return value.split("?", 1)[0].split("#", 1)[0][:500]
