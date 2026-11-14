"""Mocked tests for the bounded direct-HTTP web fetch implementation."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from pathlib import Path

import httpx
import pytest

from virtual_company.tools.httpx_web_fetch import HttpxWebFetchTool
from virtual_company.tools.web_fetch import (
    WebFetchHttpError,
    WebFetchInvalidUrlError,
    WebFetchNetworkError,
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
    options: dict[str, object] = {
        "timeout_seconds": 1,
        "max_response_bytes": 1_000,
        "max_content_chars": 500,
        "transport_factory": lambda: httpx.MockTransport(handler),
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
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"Useful text"
        )

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
        return httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=b"pdf"
        )

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
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"abcdef"
        )

    page = await make_tool(handler, max_content_chars=4).fetch(
        "https://example.com/page"
    )

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
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"ignored"
        )

    private_tool = HttpxWebFetchTool(
        timeout_seconds=1,
        max_response_bytes=1000,
        max_content_chars=500,
        transport_factory=lambda: httpx.MockTransport(handler),
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
        return httpx.Response(
            302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
        )

    async def resolver(hostname: str) -> list[str]:
        return (
            ["169.254.169.254"] if hostname == "169.254.169.254" else ["93.184.216.34"]
        )

    redirect_tool = HttpxWebFetchTool(
        timeout_seconds=1,
        max_response_bytes=1000,
        max_content_chars=500,
        transport_factory=lambda: httpx.MockTransport(redirect_handler),
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


@pytest.mark.asyncio
async def test_fetch_maps_transport_failures_for_bounded_retry_classification() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset")

    with pytest.raises(WebFetchNetworkError):
        await make_tool(handler).fetch("https://example.com/page")


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "255.255.255.255",
        "240.0.0.1",
        "::1",
        "::",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "::ffff:127.0.0.1",
    ],
)
@pytest.mark.asyncio
async def test_fetch_rejects_special_use_destinations(address: str) -> None:
    async def resolver(_: str) -> list[str]:
        return [address]

    async def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("A prohibited address must not reach the HTTP transport")

    with pytest.raises(WebFetchSsrfError):
        await make_tool(handler, resolver=resolver).fetch("https://example.com/page")


@pytest.mark.parametrize("address", ["93.184.216.34", "2606:4700:4700::1111"])
@pytest.mark.asyncio
async def test_fetch_accepts_and_pins_public_ipv4_and_ipv6(address: str) -> None:
    requests: list[httpx.Request] = []

    async def resolver(_: str) -> list[str]:
        return [address]

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"public address"
        )

    page = await make_tool(handler, resolver=resolver).fetch(
        "https://example.com:8443/page"
    )

    assert page.content == "public address"
    assert len(requests) == 1
    assert requests[0].url.host == address
    assert requests[0].headers["host"] == "example.com:8443"
    assert requests[0].extensions["sni_hostname"] == "example.com"


@pytest.mark.asyncio
async def test_fetch_falls_back_only_to_another_validated_address() -> None:
    attempted_addresses: list[str] = []

    async def resolver(_: str) -> list[str]:
        return ["93.184.216.34", "1.1.1.1"]

    async def handler(request: httpx.Request) -> httpx.Response:
        attempted_addresses.append(request.url.host)
        if request.url.host == "93.184.216.34":
            raise httpx.ConnectError("first approved address is unavailable")
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"second address"
        )

    page = await make_tool(handler, resolver=resolver).fetch("https://example.com/page")

    assert page.content == "second address"
    assert attempted_addresses == ["93.184.216.34", "1.1.1.1"]


@pytest.mark.asyncio
async def test_fetch_preserves_idn_host_as_ascii_authority_and_sni() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"IDN website"
        )

    page = await make_tool(handler).fetch("https://bücher.example/page")

    assert page.content == "IDN website"
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "xn--bcher-kva.example"
    assert requests[0].extensions["sni_hostname"] == "xn--bcher-kva.example"


@pytest.mark.asyncio
async def test_fetch_rejects_mixed_public_and_private_answers() -> None:
    async def resolver(_: str) -> list[str]:
        return ["93.184.216.34", "10.0.0.4"]

    async def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("Mixed public/private answers must be rejected before transport")

    with pytest.raises(WebFetchSsrfError):
        await make_tool(handler, resolver=resolver).fetch("https://example.com/page")


@pytest.mark.asyncio
async def test_fetch_fails_closed_for_empty_invalid_and_failed_resolution() -> None:
    async def empty_resolver(_: str) -> list[str]:
        return []

    async def invalid_resolver(_: str) -> list[str]:
        return ["not-an-ip-address"]

    async def failed_resolver(_: str) -> list[str]:
        raise socket.gaierror("scripted DNS failure")

    async def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid DNS results must not reach the HTTP transport")

    for resolver in (empty_resolver, invalid_resolver, failed_resolver):
        with pytest.raises(WebFetchInvalidUrlError):
            await make_tool(handler, resolver=resolver).fetch(
                "https://example.com/page"
            )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "/relative/path",
        "https:///missing-host",
        "https://user:password@example.com/private",
        "https://user@example.com/private",
        "https://[not-ipv6]/",
        "https://example.com:99999/",
    ],
)
@pytest.mark.asyncio
async def test_fetch_rejects_unsupported_malformed_and_credential_urls(
    url: str,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("An invalid URL must not reach the HTTP transport")

    with pytest.raises(WebFetchInvalidUrlError):
        await make_tool(handler).fetch(url)


@pytest.mark.asyncio
async def test_fetch_connects_to_validated_ip_not_rebound_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_headers: list[tuple[str, str]] = []
    connected_hostnames: list[str] = []

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.readline()
        while line := await reader.readline():
            if line in {b"\r\n", b"\n"}:
                break
            name, value = line.decode("ascii").split(":", 1)
            request_headers.append((name.lower(), value.strip()))
        body = b"Pinned to the checked address"
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    loop = asyncio.get_running_loop()
    original_create_connection = loop.create_connection

    async def mapped_create_connection(
        protocol_factory, host=None, requested_port=None, **kwargs
    ):
        hostname = host.decode() if isinstance(host, bytes) else str(host)
        connected_hostnames.append(hostname)
        if hostname in {"rebind.example", "93.184.216.34"}:
            # Map both the rebinding hostname and approved address to this
            # local endpoint; assert the HTTP stack uses only the approved IP.
            host = "127.0.0.1"
        return await original_create_connection(
            protocol_factory, host, requested_port, **kwargs
        )

    monkeypatch.setattr(loop, "create_connection", mapped_create_connection)
    resolution_calls = 0

    async def resolver(_: str) -> list[str]:
        nonlocal resolution_calls
        resolution_calls += 1
        return ["93.184.216.34"] if resolution_calls == 1 else ["10.0.0.8"]

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        tool = HttpxWebFetchTool(
            timeout_seconds=2,
            max_response_bytes=1_000,
            max_content_chars=500,
            resolver=resolver,
        )
        page = await tool.fetch(f"http://rebind.example:{port}/checked?x=1")
    finally:
        server.close()
        await server.wait_closed()

    assert page.content == "Pinned to the checked address"
    assert page.final_url == f"http://rebind.example:{port}/checked?x=1"
    assert resolution_calls == 1
    assert connected_hostnames == ["93.184.216.34"]
    assert ("host", f"rebind.example:{port}") in request_headers


@pytest.mark.asyncio
async def test_each_redirect_is_resolved_and_connected_to_its_approved_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str]] = []
    connected_hosts: list[str] = []

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        request_line = (await reader.readline()).decode("ascii").strip()
        host_header = ""
        while line := await reader.readline():
            if line in {b"\r\n", b"\n"}:
                break
            if line.lower().startswith(b"host:"):
                host_header = line.decode("ascii").split(":", 1)[1].strip()
        requests.append((request_line, host_header))
        if "first.example" in host_header:
            body = b""
            writer.write(
                b"HTTP/1.1 302 Found\r\n"
                + f"Location: http://second.example:{port}/final\r\n".encode()
                + b"Content-Length: 0\r\nConnection: close\r\n\r\n"
            )
        else:
            body = b"Redirect destination pinned"
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                + f"Content-Length: {len(body)}\r\n".encode()
                + b"Connection: close\r\n\r\n"
                + body
            )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    loop = asyncio.get_running_loop()
    original_create_connection = loop.create_connection

    async def mapped_create_connection(
        protocol_factory, host=None, requested_port=None, **kwargs
    ):
        hostname = host.decode() if isinstance(host, bytes) else str(host)
        connected_hosts.append(hostname)
        if hostname in {"93.184.216.34", "1.1.1.1"}:
            host = "127.0.0.1"
        else:
            pytest.fail(f"HTTP transport used an unpinned hostname: {hostname}")
        return await original_create_connection(
            protocol_factory, host, requested_port, **kwargs
        )

    monkeypatch.setattr(loop, "create_connection", mapped_create_connection)

    async def resolver(hostname: str) -> list[str]:
        return {
            "first.example": ["93.184.216.34"],
            "second.example": ["1.1.1.1"],
        }[hostname]

    try:
        tool = HttpxWebFetchTool(
            timeout_seconds=2,
            max_response_bytes=1_000,
            max_content_chars=500,
            resolver=resolver,
        )
        page = await tool.fetch(f"http://first.example:{port}/start")
    finally:
        server.close()
        await server.wait_closed()

    assert page.content == "Redirect destination pinned"
    assert page.final_url == f"http://second.example:{port}/final"
    assert [item[1] for item in requests] == [
        f"first.example:{port}",
        f"second.example:{port}",
    ]
    assert connected_hosts == ["93.184.216.34", "1.1.1.1"]


@pytest.mark.parametrize(
    "redirect_url",
    [
        "http://127.0.0.1/admin",
        "http://10.0.0.7/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://224.0.0.1/admin",
    ],
)
@pytest.mark.asyncio
async def test_fetch_rejects_prohibited_redirect_destinations(
    redirect_url: str,
) -> None:
    request_count = 0

    async def resolver(hostname: str) -> list[str]:
        try:
            return [str(ipaddress.ip_address(hostname))]
        except ValueError:
            return ["93.184.216.34"]

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(302, headers={"location": redirect_url})

    with pytest.raises(WebFetchSsrfError):
        await make_tool(handler, resolver=resolver).fetch("https://example.com/start")
    assert request_count == 1


def _map_vetted_ip_to_local_server(
    monkeypatch: pytest.MonkeyPatch,
    ip_mapping: dict[str, str],
    seen_hosts: list[str],
) -> None:
    loop = asyncio.get_running_loop()
    original_create_connection = loop.create_connection

    async def mapped_create_connection(
        protocol_factory, host=None, port=None, **kwargs
    ):
        hostname = host.decode() if isinstance(host, bytes) else str(host)
        seen_hosts.append(hostname)
        mapped_host = ip_mapping.get(hostname)
        if mapped_host is None:
            # Unknown hostnames are mapped locally too, so a regression cannot
            # trigger an external DNS lookup from this test.
            mapped_host = "127.0.0.1"
        return await original_create_connection(
            protocol_factory, mapped_host, port, **kwargs
        )

    monkeypatch.setattr(loop, "create_connection", mapped_create_connection)


@pytest.mark.asyncio
async def test_https_preserves_host_sni_and_certificate_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "httpx_web_fetch"
    certificate = fixture_dir / "server-test-only.crt"
    key = fixture_dir / "server-test-only.key"
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate, key)
    received_sni: list[str | None] = []
    server_context.set_servername_callback(
        lambda _ssl_socket, server_name, _context: received_sni.append(server_name)
    )
    request_headers: list[str] = []

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.readline()
        while line := await reader.readline():
            if line in {b"\r\n", b"\n"}:
                break
            if line.lower().startswith(b"host:"):
                request_headers.append(line.decode("ascii").split(":", 1)[1].strip())
        body = b"Verified original hostname"
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(
        handle_client, "127.0.0.1", 0, ssl=server_context
    )
    port = server.sockets[0].getsockname()[1]
    connected_hosts: list[str] = []
    _map_vetted_ip_to_local_server(
        monkeypatch, {"93.184.216.34": "127.0.0.1"}, connected_hosts
    )
    client_context = ssl.create_default_context(cafile=str(certificate))
    assert client_context.check_hostname is True

    try:
        tool = HttpxWebFetchTool(
            timeout_seconds=2,
            max_response_bytes=1_000,
            max_content_chars=500,
            resolver=public_resolver,
            transport_factory=lambda: httpx.AsyncHTTPTransport(
                verify=client_context, trust_env=False
            ),
        )
        page = await tool.fetch(f"https://webfetch.test:{port}/secure")
    finally:
        server.close()
        await server.wait_closed()

    assert page.content == "Verified original hostname"
    assert request_headers == [f"webfetch.test:{port}"]
    assert received_sni == ["webfetch.test"]
    assert connected_hosts == ["93.184.216.34"]


@pytest.mark.parametrize(
    ("hostname", "trust_test_certificate"),
    [("wrong-host.test", True), ("webfetch.test", False)],
)
@pytest.mark.asyncio
async def test_https_rejects_invalid_or_wrong_hostname_certificate(
    hostname: str,
    trust_test_certificate: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "httpx_web_fetch"
    certificate = fixture_dir / "server-test-only.crt"
    key = fixture_dir / "server-test-only.key"
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate, key)
    received_sni: list[str | None] = []
    server_context.set_servername_callback(
        lambda _ssl_socket, server_name, _context: received_sni.append(server_name)
    )

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.read()

    server = await asyncio.start_server(
        handle_client, "127.0.0.1", 0, ssl=server_context
    )
    port = server.sockets[0].getsockname()[1]
    connected_hosts: list[str] = []
    _map_vetted_ip_to_local_server(
        monkeypatch, {"93.184.216.34": "127.0.0.1"}, connected_hosts
    )
    client_context = (
        ssl.create_default_context(cafile=str(certificate))
        if trust_test_certificate
        else None
    )

    try:
        tool = HttpxWebFetchTool(
            timeout_seconds=2,
            max_response_bytes=1_000,
            max_content_chars=500,
            resolver=public_resolver,
            transport_factory=lambda: httpx.AsyncHTTPTransport(
                verify=client_context or True, trust_env=False
            ),
        )
        with pytest.raises(WebFetchNetworkError):
            await tool.fetch(f"https://{hostname}:{port}/secure")
    finally:
        server.close()
        await server.wait_closed()

    assert connected_hosts == ["93.184.216.34"]
    assert received_sni == [hostname]
