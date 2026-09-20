"""Safe, bounded direct-HTTP implementation of the web fetch contract."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx
from trafilatura import extract
from trafilatura.metadata import extract_metadata

from virtual_company.research.models import WebPage
from virtual_company.tools.web_fetch import (
    WebFetchEmptyContentError,
    WebFetchError,
    WebFetchHttpError,
    WebFetchInvalidUrlError,
    WebFetchResponseTooLargeError,
    WebFetchSsrfError,
    WebFetchTimeoutError,
    WebFetchUnsupportedContentError,
)

Resolver = Callable[[str], Awaitable[list[str]]]
_MAX_REDIRECTS = 5
_USER_AGENT = "virtual-company-research/0.1 (+https://github.com/anthony-au1/virtual_company)"
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class HttpxWebFetchTool:
    """Fetch public HTML/text pages without allowing unbounded downloads."""

    provider = "httpx"

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        max_content_chars: int,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self._max_response_bytes = max_response_bytes
        self._max_content_chars = max_content_chars
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._resolver = resolver or self._resolve_host

    async def fetch(self, url: str) -> WebPage:
        """Fetch one safe public page and extract bounded readable text."""
        if self._client is not None:
            return await self._fetch_with_client(url, self._client)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout_seconds),
            follow_redirects=False,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            return await self._fetch_with_client(url, client)

    async def _fetch_with_client(self, url: str, client: httpx.AsyncClient) -> WebPage:
        """Fetch with one client, retaining redirect state for this request."""
        requested_url = url
        current_url = url
        for redirect_count in range(_MAX_REDIRECTS + 1):
            await self._validate_public_url(current_url)
            try:
                async with client.stream(
                    "GET", current_url, follow_redirects=False
                ) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise WebFetchHttpError(response.status_code)
                        if redirect_count == _MAX_REDIRECTS:
                            raise WebFetchHttpError(response.status_code)
                        current_url = urljoin(current_url, location)
                        continue
                    if not 200 <= response.status_code < 300:
                        raise WebFetchHttpError(response.status_code)
                    content_type = self._content_type(response)
                    if content_type not in {"text/html", "text/plain"}:
                        raise WebFetchUnsupportedContentError(
                            f"Unsupported content type: {content_type or 'missing'}"
                        )
                    body = await self._read_bounded_body(response)
            except httpx.TimeoutException as error:
                raise WebFetchTimeoutError("Web page request timed out") from error
            except httpx.HTTPError as error:
                raise WebFetchError("Web page request failed") from error

            content, title = self._extract_content(body, content_type, response.encoding)
            if not content:
                raise WebFetchEmptyContentError("No readable page content was extracted")
            truncated = len(content) > self._max_content_chars
            return WebPage(
                url=requested_url,
                final_url=str(response.url),
                title=title,
                content=content[: self._max_content_chars],
                content_type=content_type,
                truncated=truncated,
            )
        raise WebFetchError("Web page redirect handling failed")

    async def _validate_public_url(self, value: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise WebFetchInvalidUrlError("Only absolute HTTP(S) URLs may be fetched")
        try:
            addresses = await self._resolver(parsed.hostname.rstrip("."))
        except OSError as error:
            raise WebFetchInvalidUrlError("URL hostname could not be resolved") from error
        if not addresses:
            raise WebFetchInvalidUrlError("URL hostname did not resolve to an address")
        try:
            if any(not ipaddress.ip_address(address).is_global for address in addresses):
                raise WebFetchSsrfError("URL resolves to a non-public network address")
        except ValueError as error:
            raise WebFetchInvalidUrlError("URL hostname resolved to an invalid address") from error

    async def _read_bounded_body(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_response_bytes:
                    raise WebFetchResponseTooLargeError("Response exceeds configured byte limit")
            except ValueError:
                pass
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_response_bytes:
                raise WebFetchResponseTooLargeError("Response exceeds configured byte limit")
            chunks.append(chunk)
        return b"".join(chunks)

    def _extract_content(
        self, body: bytes, content_type: str, encoding: str | None
    ) -> tuple[str, str | None]:
        text = body.decode(encoding or "utf-8", errors="replace")
        if content_type == "text/plain":
            return "\n".join(line.strip() for line in text.splitlines() if line.strip()), None
        metadata = extract_metadata(text)
        title = metadata.title if metadata is not None else None
        content = extract(
            text,
            output_format="txt",
            include_comments=False,
            include_tables=True,
        )
        return (content or "").strip(), title

    @staticmethod
    def _content_type(response: httpx.Response) -> str:
        return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    @staticmethod
    async def _resolve_host(hostname: str) -> list[str]:
        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(hostname, None, type=0)
        return list({record[4][0] for record in records})
