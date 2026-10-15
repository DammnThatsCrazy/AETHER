"""Outbound destination checks for server-side requests to tenant-configured URLs.

Every request to a destination a tenant can configure (webhook targets,
ticketing/CRM base URLs, RPC endpoints) must only reach globally routable
addresses: every resolved address is checked, IPv4-mapped and NAT64 IPv6 forms
are unwrapped, the connection is pinned to the validated address, and each
redirect hop is re-validated.
"""

from __future__ import annotations

import http.server
import socket
import threading
from unittest.mock import patch

import httpx
import pytest

from actions.delivery.adapters.base import SSRFBlockedError
from actions.delivery.adapters.webhook import _check_ssrf
from actions.delivery.security import validate_webhook_url
from shared.security.ssrf import (
    UnsafeDestinationError,
    is_public_address,
    resolve_public_addresses,
    send_public_request,
)
from value.x402.rpc_resolver import RpcUnavailableError, _validate_rpc_url

NON_PUBLIC = [
    "127.0.0.1",
    "::1",
    "::ffff:127.0.0.1",
    "::ffff:169.254.169.254",
    "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
    "64:ff9b::7f00:1",  # NAT64 of 127.0.0.1
    "169.254.169.254",
    "fe80::1",
    "10.0.0.5",
    "172.16.0.1",
    "192.168.1.1",
    "fc00::1",
    "100.64.0.1",  # carrier-grade NAT
    "100.100.100.200",
    "0.0.0.0",
    "::",
    "224.0.0.1",
    "255.255.255.255",
]

PUBLIC = ["93.184.216.34", "8.8.8.8", "2001:4860:4860::8888", "::ffff:8.8.8.8", "64:ff9b::808:808"]

LITERAL_URLS = [
    "https://127.0.0.1/",
    "https://[::ffff:127.0.0.1]/",
    "https://[::ffff:169.254.169.254]/",
    "https://[::ffff:a9fe:a9fe]/",
    "https://100.100.100.200/",
    "https://[64:ff9b::a9fe:a9fe]/",
]


def _addrinfo(*ips: str):
    return [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
        for ip in ips
    ]


def _resolver(table: dict[str, list[str]]):
    def fake(host, *args, **kwargs):
        if host not in table:
            raise socket.gaierror(f"unknown host {host}")
        return _addrinfo(*table[host])

    return fake


@pytest.mark.parametrize("ip", NON_PUBLIC)
def test_rejects_non_public_address(ip):
    assert is_public_address(ip) is False


@pytest.mark.parametrize("ip", PUBLIC)
def test_accepts_public_address(ip):
    assert is_public_address(ip) is True


def test_rejects_unparseable_address():
    assert is_public_address("not-an-ip") is False


@pytest.mark.parametrize("url", LITERAL_URLS)
def test_rejects_non_public_literal_destination(url):
    with patch("socket.getaddrinfo", side_effect=AssertionError("literal must not be resolved")):
        with pytest.raises(UnsafeDestinationError):
            resolve_public_addresses(url)


@pytest.mark.parametrize("url", LITERAL_URLS)
def test_every_guard_rejects_non_public_destination(url, monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "staging")
    with pytest.raises(SSRFBlockedError):
        _check_ssrf(url)
    with pytest.raises(SSRFBlockedError):
        validate_webhook_url(url)
    with pytest.raises(RpcUnavailableError):
        _validate_rpc_url(url)


def test_rejects_when_any_resolved_address_is_non_public():
    with patch("socket.getaddrinfo", side_effect=_resolver({"mixed.example": ["93.184.216.34", "10.0.0.5"]})):
        with pytest.raises(UnsafeDestinationError, match="SSRF"):
            resolve_public_addresses("https://mixed.example/hook")


def test_rejects_resolution_to_mapped_metadata_address():
    with patch("socket.getaddrinfo", side_effect=_resolver({"m.example": ["::ffff:169.254.169.254"]})):
        with pytest.raises(UnsafeDestinationError):
            resolve_public_addresses("https://m.example/")


def test_returns_all_resolved_public_addresses():
    with patch("socket.getaddrinfo", side_effect=_resolver({"ok.example": ["93.184.216.34", "2001:4860:4860::8888"]})):
        assert resolve_public_addresses("https://ok.example/") == ["93.184.216.34", "2001:4860:4860::8888"]


def test_rejects_unresolvable_host():
    with patch("socket.getaddrinfo", side_effect=_resolver({})):
        with pytest.raises(UnsafeDestinationError):
            resolve_public_addresses("https://missing.example/")


@pytest.mark.parametrize("url", ["not-a-url", "ftp://ok.example/", "file:///etc/passwd"])
def test_rejects_malformed_or_non_http_url(url):
    with pytest.raises(UnsafeDestinationError):
        resolve_public_addresses(url)


# ─── Pinned request + redirects ─────────────────────────────────────────────


class _Recorder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)


DNS = {
    "a.example": ["93.184.216.34"],
    "b.example": ["8.8.8.8"],
    "v6.example": ["2001:4860:4860::8888"],
    "internal.example": ["10.0.0.5"],
}


@pytest.mark.asyncio
async def test_connects_to_validated_address_with_original_host():
    rec = _Recorder([httpx.Response(200, text="ok")])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        resp = await send_public_request(
            "POST", "https://a.example:8443/hook?x=1", content=b"{}", transport=httpx.MockTransport(rec)
        )
    assert resp.status_code == 200
    (req,) = rec.requests
    assert req.url.host == "93.184.216.34"
    assert req.url.port == 8443
    assert req.url.raw_path == b"/hook?x=1"
    assert req.headers["host"] == "a.example:8443"
    assert req.extensions["sni_hostname"] == "a.example"


@pytest.mark.asyncio
async def test_connects_to_validated_ipv6_address():
    rec = _Recorder([httpx.Response(204)])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        await send_public_request("GET", "https://v6.example/", transport=httpx.MockTransport(rec))
    assert rec.requests[0].url.host == "2001:4860:4860::8888"
    assert rec.requests[0].headers["host"] == "v6.example"


@pytest.mark.asyncio
async def test_follows_redirect_revalidating_and_dropping_auth_on_host_change():
    rec = _Recorder([
        httpx.Response(302, headers={"location": "https://b.example/next"}),
        httpx.Response(200, text="done"),
    ])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        resp = await send_public_request(
            "POST",
            "https://a.example/start",
            headers={"Authorization": "Bearer secret", "Cookie": "c=1", "X-Trace": "t"},
            content=b"body",
            transport=httpx.MockTransport(rec),
        )
    assert resp.text == "done"
    first, second = rec.requests
    assert first.headers["authorization"] == "Bearer secret"
    assert second.url.host == "8.8.8.8"
    assert second.headers["host"] == "b.example"
    assert second.method == "GET"
    assert second.content == b""
    assert "authorization" not in second.headers
    assert "cookie" not in second.headers
    assert second.headers["x-trace"] == "t"


@pytest.mark.asyncio
async def test_same_host_307_keeps_method_body_and_auth():
    rec = _Recorder([
        httpx.Response(307, headers={"location": "/moved"}),
        httpx.Response(200),
    ])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        await send_public_request(
            "POST",
            "https://a.example/start",
            headers={"Authorization": "Bearer secret"},
            content=b"body",
            transport=httpx.MockTransport(rec),
        )
    second = rec.requests[1]
    assert second.method == "POST"
    assert second.content == b"body"
    assert second.headers["authorization"] == "Bearer secret"
    assert second.url.path == "/moved"


@pytest.mark.asyncio
async def test_rejects_redirect_to_non_public_destination():
    rec = _Recorder([httpx.Response(302, headers={"location": "https://internal.example/admin"})])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        with pytest.raises(UnsafeDestinationError):
            await send_public_request("GET", "https://a.example/", transport=httpx.MockTransport(rec))
    assert len(rec.requests) == 1


@pytest.mark.asyncio
async def test_rejects_redirect_to_literal_metadata_address():
    rec = _Recorder([httpx.Response(301, headers={"location": "http://[::ffff:a9fe:a9fe]/latest"})])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        with pytest.raises(UnsafeDestinationError):
            await send_public_request("GET", "https://a.example/", transport=httpx.MockTransport(rec))
    assert len(rec.requests) == 1


@pytest.mark.asyncio
async def test_stops_after_three_redirects():
    rec = _Recorder([httpx.Response(302, headers={"location": "/again"}) for _ in range(5)])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        with pytest.raises(UnsafeDestinationError, match="redirect"):
            await send_public_request("GET", "https://a.example/", transport=httpx.MockTransport(rec))
    assert len(rec.requests) == 4


@pytest.mark.asyncio
async def test_without_redirects_returns_redirect_response():
    rec = _Recorder([httpx.Response(302, headers={"location": "https://b.example/"})])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        resp = await send_public_request(
            "POST", "https://a.example/", max_redirects=0, transport=httpx.MockTransport(rec)
        )
    assert resp.status_code == 302
    assert len(rec.requests) == 1


@pytest.mark.asyncio
async def test_refuses_non_public_destination_before_connecting():
    rec = _Recorder([])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        with pytest.raises(UnsafeDestinationError):
            await send_public_request("GET", "https://internal.example/", transport=httpx.MockTransport(rec))
    assert rec.requests == []


@pytest.fixture
def local_stub():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = self.headers.get("Host", "").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_local_target_requires_explicit_allowance(local_stub):
    with pytest.raises(UnsafeDestinationError):
        await send_public_request("GET", local_stub)
    resp = await send_public_request("GET", local_stub, allow_local=True)
    assert resp.status_code == 200
    assert resp.text.startswith("127.0.0.1:")


@pytest.mark.parametrize("ip", ["64:ff9b::a9fe:a9fe", "::ffff:169.254.169.254", "100.64.0.1", "10.0.0.5"])
def test_webhook_destination_policies_reject_non_public_address(ip):
    import ipaddress

    from governance.security.policy_engine import _ip_is_unsafe
    from journeys.notification_intelligence.customer_webhook_delivery import _is_blocked

    assert _ip_is_unsafe(ipaddress.ip_address(ip)) is True
    assert _is_blocked(ip) is True
