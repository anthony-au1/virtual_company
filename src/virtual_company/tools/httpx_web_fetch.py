"""Safe, bounded direct-HTTP implementation of the web fetch contract."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx
from trafilatura import extract
from trafilatura.metadata import extract_metadata

from virtual_company.tools.web_fetch import (
    WebFetchEmptyContentError,
    WebFetchError,
    WebFetchHttpError,
    WebFetchInvalidUrlError,
    WebFetchNetworkError,
    WebFetchResponseTooLargeError,
    WebFetchSsrfError,
    WebFetchTimeoutError,
    WebFetchUnsupportedContentError,
    WebPage,
)

Resolver = Callable[[str], Awaitable[list[str]]]
TransportFactory = Callable[[], httpx.AsyncBaseTransport]
_MAX_REDIRECTS = 5
_USER_AGENT = (
    "virtual-company-research/0.1 (+https://github.com/anthony-au1/virtual_company)"
)
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
        transport_factory: TransportFactory | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self._max_response_bytes = max_response_bytes
        self._max_content_chars = max_content_chars
        self._transport_factory = transport_factory
        self._timeout_seconds = timeout_seconds
        self._resolver = resolver or self._resolve_host

    async def fetch(self, url: str) -> WebPage:
        """Fetch one safe public page and extract bounded readable text."""
        requested_url = url
        current_url = url
        for redirect_count in range(_MAX_REDIRECTS + 1):
            original_url, addresses = await self._validate_public_url(current_url)
            response, client = await self._send_to_approved_address(
                original_url, addresses
            )
            try:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise WebFetchHttpError(response.status_code)
                    if redirect_count == _MAX_REDIRECTS:
                        raise WebFetchHttpError(response.status_code)
                    current_url = urljoin(str(original_url), location)
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
                raise WebFetchNetworkError("Web page request failed") from error
            finally:
                await response.aclose()
                await client.aclose()

            content, title = self._extract_content(
                body, content_type, response.encoding
            )
            if not content:
                raise WebFetchEmptyContentError(
                    "No readable page content was extracted"
                )
            truncated = len(content) > self._max_content_chars
            return WebPage(
                url=requested_url,
                final_url=str(original_url),
                title=title,
                content=content[: self._max_content_chars],
                content_type=content_type,
                truncated=truncated,
            )
        raise WebFetchError("Web page redirect handling failed")

    async def _validate_public_url(
        self, value: str
    ) -> tuple[httpx.URL, list[ipaddress.IPv4Address | ipaddress.IPv6Address]]:
        try:
            parsed = urlsplit(value)
            original_url = httpx.URL(value)
            hostname = parsed.hostname
            # Accessing the port validates malformed and out-of-range port values.
            _ = parsed.port
        except (ValueError, httpx.InvalidURL) as error:
            raise WebFetchInvalidUrlError("URL is malformed") from error
        if parsed.scheme.lower() not in {"http", "https"} or not hostname:
            raise WebFetchInvalidUrlError("Only absolute HTTP(S) URLs may be fetched")
        if parsed.username is not None or parsed.password is not None:
            raise WebFetchInvalidUrlError(
                "URLs with embedded credentials may not be fetched"
            )
        try:
            resolved_addresses = await self._resolver(hostname.rstrip("."))
        except OSError as error:
            raise WebFetchInvalidUrlError(
                "URL hostname could not be resolved"
            ) from error
        if not resolved_addresses:
            raise WebFetchInvalidUrlError("URL hostname did not resolve to an address")
        try:
            addresses = list(
                dict.fromkeys(ipaddress.ip_address(item) for item in resolved_addresses)
            )
        except ValueError as error:
            raise WebFetchInvalidUrlError(
                "URL hostname resolved to an invalid address"
            ) from error
        if any(not self._is_public_destination(address) for address in addresses):
            raise WebFetchSsrfError("URL resolves to a non-public network address")
        return original_url, addresses

    @staticmethod
    def _is_public_destination(
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> bool:
        """Reject special-use addresses, including multicast marked global by Python."""
        if (
            isinstance(address, ipaddress.IPv6Address)
            and address.ipv4_mapped is not None
        ):
            address = address.ipv4_mapped
        return (
            address.is_global
            and not address.is_private
            and not address.is_loopback
            and not address.is_link_local
            and not address.is_unspecified
            and not address.is_multicast
            and not address.is_reserved
        )

    async def _send_to_approved_address(
        self,
        original_url: httpx.URL,
        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address],
    ) -> tuple[httpx.Response, httpx.AsyncClient]:
        """Connect to numeric, previously checked IPs; never resolve the URL host again."""
        last_error: httpx.ConnectError | httpx.ConnectTimeout | None = None
        for address in addresses:
            transport = (
                self._transport_factory()
                if self._transport_factory is not None
                else None
            )
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds),
                follow_redirects=False,
                headers={"User-Agent": _USER_AGENT},
                trust_env=False,
                transport=transport,
            )
            request_url = original_url.copy_with(host=str(address))
            request = client.build_request(
                "GET",
                request_url,
                headers={"Host": original_url.netloc.decode("ascii")},
                extensions={"sni_hostname": original_url.raw_host.decode("ascii")},
            )
            try:
                response = await client.send(
                    request, stream=True, follow_redirects=False
                )
                return response, client
            except httpx.ConnectTimeout as error:
                last_error = error
                await client.aclose()
            except httpx.ConnectError as error:
                last_error = error
                await client.aclose()
            except httpx.TimeoutException as error:
                await client.aclose()
                raise WebFetchTimeoutError("Web page request timed out") from error
            except httpx.HTTPError as error:
                await client.aclose()
                raise WebFetchNetworkError("Web page request failed") from error
            except BaseException:
                await client.aclose()
                raise
        if isinstance(last_error, httpx.ConnectTimeout):
            raise WebFetchTimeoutError("Web page request timed out") from last_error
        if last_error is not None:
            raise WebFetchNetworkError("Web page request failed") from last_error
        raise WebFetchNetworkError("Web page request failed")

    async def _read_bounded_body(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_response_bytes:
                    raise WebFetchResponseTooLargeError(
                        "Response exceeds configured byte limit"
                    )
            except ValueError:
                pass
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_response_bytes:
                raise WebFetchResponseTooLargeError(
                    "Response exceeds configured byte limit"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _extract_content(
        self, body: bytes, content_type: str, encoding: str | None
    ) -> tuple[str, str | None]:
        text = body.decode(encoding or "utf-8", errors="replace")
        if content_type == "text/plain":
            return "\n".join(
                line.strip() for line in text.splitlines() if line.strip()
            ), None
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
