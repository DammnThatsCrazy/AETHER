"""Outbound destination checks for server-side requests to tenant-configured URLs.

Every request to a destination a tenant can configure (webhook targets,
ticketing/CRM base URLs, RPC endpoints) must only reach globally routable
addresses: every resolved address is checked, IPv4-mapped and NAT64 IPv6 forms
are unwrapped, the connection is pinned to the validated address, and each
redirect hop is re-validated.
"""

from __future__ import annotations

import asyncio
import http.server
import socket
import threading
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from actions.delivery.adapters.base import SSRFBlockedError
from actions.delivery.adapters.webhook import _check_ssrf
from actions.delivery.security import validate_webhook_url
from shared.security.ssrf import (
    DestinationResolutionError,
    UnsafeDestinationError,
    is_public_address,
    resolve_public_addresses,
    resolve_public_addresses_async,
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
    "2002:a9fe:a9fe::1",  # 6to4 of 169.254.169.254
    "2002:7f00:1::1",  # 6to4 of 127.0.0.1
    "2001:0:4136:e378:8000:63bf:80ff:fffe",  # Teredo client 127.0.0.1
    "2001:0:4136:e378:8000:63bf:f5ff:fffa",  # Teredo client 10.0.0.5
    "2001:0:a00:5:8000:63bf:f7f7:f7f7",  # Teredo server 10.0.0.5
]

PUBLIC = [
    "93.184.216.34",
    "8.8.8.8",
    "2001:4860:4860::8888",
    "::ffff:8.8.8.8",
    "64:ff9b::808:808",
    "2002:808:808::1",  # 6to4 of 8.8.8.8
    "2001:0:4136:e378:8000:63bf:f7f7:f7f7",  # Teredo server 65.54.227.120, client 8.8.8.8
]

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://10.0.0.5/hooks/SECRETTOKEN?key=SECRETKEY",
        "https://internal.example/hooks/SECRETTOKEN?key=SECRETKEY",
        "ftp://ok.example/SECRETTOKEN?key=SECRETKEY",
        "https://a.example/redirect/SECRETTOKEN?key=SECRETKEY",
    ],
)
async def test_rejection_message_omits_url_path_and_query(url):
    rec = _Recorder([httpx.Response(302, headers={"location": "/again/SECRETTOKEN?key=SECRETKEY"}) for _ in range(4)])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        with pytest.raises(UnsafeDestinationError) as excinfo:
            await send_public_request("GET", url, transport=httpx.MockTransport(rec))
    assert "SECRETTOKEN" not in str(excinfo.value)
    assert "SECRETKEY" not in str(excinfo.value)


# ─── Resolution failure vs non-public destination ───────────────────────────


@pytest.mark.parametrize(
    "resolver",
    [
        _resolver({}),
        lambda *a, **k: (_ for _ in ()).throw(socket.gaierror(socket.EAI_AGAIN, "temporary failure")),
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("resolver timed out")),
        lambda *a, **k: [],
    ],
)
def test_resolution_failure_is_distinct_from_non_public(resolver):
    with patch("socket.getaddrinfo", side_effect=resolver):
        with pytest.raises(DestinationResolutionError):
            resolve_public_addresses("https://flaky.example/")


@pytest.mark.parametrize("url", ["https://internal.example/", "https://10.0.0.5/", "ftp://a.example/"])
def test_non_public_destination_is_not_a_resolution_failure(url):
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        with pytest.raises(UnsafeDestinationError) as excinfo:
            resolve_public_addresses(url)
    assert not isinstance(excinfo.value, DestinationResolutionError)


@pytest.mark.asyncio
async def test_async_resolution_uses_the_event_loop_resolver():
    with patch("socket.getaddrinfo", side_effect=AssertionError("blocking resolver used")):
        with patch.object(
            asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=_addrinfo("93.184.216.34"))
        ) as loop_resolver:
            assert await resolve_public_addresses_async("https://a.example/") == ["93.184.216.34"]
    loop_resolver.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_resolution_failure_is_distinct_from_non_public():
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        with pytest.raises(DestinationResolutionError):
            await resolve_public_addresses_async("https://missing.example/")
        with pytest.raises(UnsafeDestinationError) as excinfo:
            await resolve_public_addresses_async("https://internal.example/")
    assert not isinstance(excinfo.value, DestinationResolutionError)


@pytest.mark.asyncio
async def test_send_resolves_without_blocking_the_event_loop():
    rec = _Recorder([httpx.Response(200)])
    with patch("socket.getaddrinfo", side_effect=AssertionError("blocking resolver used")):
        with patch.object(
            asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=_addrinfo("93.184.216.34"))
        ):
            resp = await send_public_request("GET", "https://a.example/", transport=httpx.MockTransport(rec))
    assert resp.status_code == 200


# ─── Address fallback ───────────────────────────────────────────────────────

MULTI = {"multi.example": ["93.184.216.34", "8.8.8.8", "2001:4860:4860::8888"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ConnectError("refused"), httpx.ConnectTimeout("timed out")])
async def test_tries_next_validated_address_on_connect_failure(failure):
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "93.184.216.34":
            raise failure
        return httpx.Response(200)

    with patch("socket.getaddrinfo", side_effect=_resolver(MULTI)):
        resp = await send_public_request(
            "POST", "https://multi.example/", content=b"x", transport=httpx.MockTransport(handler)
        )
    assert resp.status_code == 200
    assert seen == ["93.184.216.34", "8.8.8.8"]


@pytest.mark.asyncio
async def test_raises_last_connect_failure_when_every_address_fails():
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.host)
        raise httpx.ConnectError(f"refused {request.url.host}")

    with patch("socket.getaddrinfo", side_effect=_resolver(MULTI)):
        with pytest.raises(httpx.ConnectError, match="2001:4860:4860::8888"):
            await send_public_request("GET", "https://multi.example/", transport=httpx.MockTransport(handler))
    assert seen == ["93.184.216.34", "8.8.8.8", "2001:4860:4860::8888"]


@pytest.mark.asyncio
async def test_does_not_resend_after_the_request_may_have_been_delivered():
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.host)
        raise httpx.ReadTimeout("no response")

    with patch("socket.getaddrinfo", side_effect=_resolver(MULTI)):
        with pytest.raises(httpx.ReadTimeout):
            await send_public_request("POST", "https://multi.example/", content=b"x", transport=httpx.MockTransport(handler))
    assert seen == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_never_falls_back_to_an_unvalidated_address():
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.host)
        raise httpx.ConnectError("refused")

    with patch("socket.getaddrinfo", side_effect=_resolver({"mixed.example": ["93.184.216.34", "10.0.0.5"]})):
        with pytest.raises(UnsafeDestinationError):
            await send_public_request("GET", "https://mixed.example/", transport=httpx.MockTransport(handler))
    assert seen == []


# ─── Credential stripping on scheme downgrade ───────────────────────────────


@pytest.mark.asyncio
async def test_drops_credentials_on_same_host_scheme_downgrade():
    rec = _Recorder([
        httpx.Response(307, headers={"location": "http://a.example/next"}),
        httpx.Response(200),
    ])
    with patch("socket.getaddrinfo", side_effect=_resolver(DNS)):
        await send_public_request(
            "GET",
            "https://a.example/start",
            headers={"Authorization": "Bearer secret", "Proxy-Authorization": "p", "Cookie": "c=1", "X-Trace": "t"},
            transport=httpx.MockTransport(rec),
        )
    second = rec.requests[1]
    assert second.url.scheme == "http"
    assert "authorization" not in second.headers
    assert "proxy-authorization" not in second.headers
    assert "cookie" not in second.headers
    assert second.headers["x-trace"] == "t"


# ─── Delivery adapters: retry a resolution failure, never a refusal ─────────


async def _dispatch_webhook():
    from actions.delivery.adapters.webhook import WebhookAdapter

    await WebhookAdapter().dispatch({"a": 1}, {"url": "https://hooks.example/in"})


async def _dispatch_jira():
    from actions.delivery.adapters.jira import JiraAdapter

    await JiraAdapter().dispatch(
        {"title": "T"}, {"base_url": "https://site.example", "project_key": "P"}, credential="u@example.com:t"
    )


async def _dispatch_push():
    from actions.delivery.adapters._notification_base import _public_transport

    await _public_transport("POST", "https://push.example/send", {}, b"{}")


async def _dispatch_discord():
    from actions.delivery.adapters.discord import DiscordAdapter

    await DiscordAdapter().dispatch({"title": "T"}, {"webhook_url": "https://discord.com/api/webhooks/1/x"})


_DISPATCHERS = [_dispatch_webhook, _dispatch_jira, _dispatch_push, _dispatch_discord]


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch", _DISPATCHERS)
async def test_adapter_retries_destination_that_does_not_resolve(dispatch):
    from actions.delivery.adapters.base import RetryableProviderError

    send = AsyncMock(side_effect=AssertionError("connection attempted"))
    with patch("socket.getaddrinfo", side_effect=socket.gaierror(socket.EAI_AGAIN, "temporary failure")), \
         patch.object(httpx.AsyncClient, "send", send), \
         patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(RetryableProviderError):
            await dispatch()
    send.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch", _DISPATCHERS)
async def test_adapter_does_not_retry_non_public_destination(dispatch):
    resolver = Mock(return_value=_addrinfo("10.0.0.5"))
    send = AsyncMock(side_effect=AssertionError("connection attempted"))
    with patch("socket.getaddrinfo", resolver), \
         patch.object(httpx.AsyncClient, "send", send), \
         patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(SSRFBlockedError):
            await dispatch()
    send.assert_not_called()
    assert resolver.call_count == 1
