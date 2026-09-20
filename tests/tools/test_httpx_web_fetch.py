"""Mocked tests for the bounded direct-HTTP web fetch implementation."""

from __future__ import annotations

import httpx
import pytest

from virtual_company.tools.httpx_web_fetch import HttpxWebFetchTool
from virtual_company.tools.web_fetch import (
    WebFetchHttpError,
    WebFetchInvalidUrlError,
    WebFetchResponseTooLargeError,
    WebFetchSsrfError,
    WebFetchTimeoutError,
    WebFetchUnsupportedContentError,
)


async def public_resolver(_: str) -> list[str]:
    return ["93.184.216.34"]


def make_tool(
    handler: httpx.AsyncByteStream | object, **kwargs: object
) -> HttpxWebFetchTool:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    options: dict[str, object] = {
        "timeout_seconds": 1,
        "max_response_bytes": 1_000,
        "max_content_chars": 500,
        "client": client,
        "resolver": public_resolver,
    }
    options.update(kwargs)
    return HttpxWebFetchTool(
        **options,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_fetch_extracts_readable_html_content() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"""
                <html><head><title>Senior Backend Engineer</title></head>
                <body><nav>Home Careers</nav><main><h1>Senior Backend Engineer</h1>
                <p>We build backend services using Java and Spring Boot.</p></main>
                <footer>Cookie preferences</footer></body></html>
            """,
        )

    page = await make_tool(handler).fetch("https://example.com/careers/backend")

    assert page.url == "https://example.com/careers/backend"
    assert page.final_url == "https://example.com/careers/backend"
    assert page.title == "Senior Backend Engineer"
    assert "Java and Spring Boot" in page.content
    assert "<main>" not in page.content
    assert page.content_type == "text/html"


@pytest.mark.asyncio
async def test_fetch_follows_safe_redirect_and_preserves_requested_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"Useful text")

    page = await make_tool(handler).fetch("https://example.com/start")

    assert page.url == "https://example.com/start"
    assert page.final_url == "https://example.com/final"
    assert page.content == "Useful text"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404, 429, 500])
async def test_fetch_maps_non_successful_statuses(status: int) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"content-type": "text/html"})

    with pytest.raises(WebFetchHttpError) as error:
        await make_tool(handler).fetch("https://example.com/page")
    assert error.value.status_code == status


@pytest.mark.asyncio
async def test_fetch_rejects_unsupported_and_oversized_responses() -> None:
    async def pdf_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"pdf")

    with pytest.raises(WebFetchUnsupportedContentError):
        await make_tool(pdf_handler).fetch("https://example.com/report")

    async def large_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain", "content-length": "1001"},
            content=b"x" * 1001,
        )

    with pytest.raises(WebFetchResponseTooLargeError):
        await make_tool(large_handler).fetch("https://example.com/large")


@pytest.mark.asyncio
async def test_fetch_truncates_extracted_content() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"abcdef")

    page = await make_tool(handler, max_content_chars=4).fetch("https://example.com/page")

    assert page.content == "abcd"
    assert page.truncated is True


@pytest.mark.asyncio
async def test_fetch_rejects_private_initial_and_redirect_targets() -> None:
    async def private_resolver(hostname: str) -> list[str]:
        addresses = {
            "localhost": "127.0.0.1",
            "127.0.0.1": "127.0.0.1",
            "10.0.0.1": "10.0.0.1",
            "192.168.1.1": "192.168.1.1",
        }
        return [addresses[hostname]]

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ignored")

    private_tool = HttpxWebFetchTool(
        timeout_seconds=1,
        max_response_bytes=1000,
        max_content_chars=500,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        resolver=private_resolver,
    )
    for url in (
        "http://localhost/admin",
        "http://127.0.0.1:8000",
        "http://10.0.0.1",
        "http://192.168.1.1",
    ):
        with pytest.raises(WebFetchSsrfError):
            await private_tool.fetch(url)
    with pytest.raises(WebFetchInvalidUrlError):
        await private_tool.fetch("file:///etc/passwd")

    async def redirect_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    async def resolver(hostname: str) -> list[str]:
        return ["169.254.169.254"] if hostname == "169.254.169.254" else ["93.184.216.34"]

    redirect_tool = HttpxWebFetchTool(
        timeout_seconds=1,
        max_response_bytes=1000,
        max_content_chars=500,
        client=httpx.AsyncClient(transport=httpx.MockTransport(redirect_handler)),
        resolver=resolver,
    )
    with pytest.raises(WebFetchSsrfError):
        await redirect_tool.fetch("https://example.com/start")


@pytest.mark.asyncio
async def test_fetch_maps_timeouts() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(WebFetchTimeoutError):
        await make_tool(handler).fetch("https://example.com/page")
