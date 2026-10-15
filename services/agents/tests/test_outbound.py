"""Discovery fetchers only reach globally routable addresses.

Crawl and scan targets come from task payloads, so every fetch resolves the
host, checks every address (unwrapping IPv4-mapped and NAT64 forms), connects
to the validated address, and re-validates each redirect hop.
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import httpx
import pytest
from config.settings import TaskPriority, WorkerType
from models.core import AgentTask

from workers.discovery.api_scanner import ApiScannerWorker
from workers.discovery.web_crawler import WebCrawlerWorker
from workers.outbound import (
    UnsafeDestinationError,
    fetch_public,
    is_public_address,
    resolve_public_addresses,
)

DNS = {
    "a.example": ["93.184.216.34"],
    "b.example": ["8.8.8.8"],
    "internal.example": ["10.0.0.5"],
    "mixed.example": ["93.184.216.34", "100.64.0.1"],
}


def _resolver(host, *args, **kwargs):
    if host not in DNS:
        raise socket.gaierror(f"unknown host {host}")
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in DNS[host]]


@pytest.fixture(autouse=True)
def fake_dns():
    with patch("socket.getaddrinfo", side_effect=_resolver):
        yield


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1", "::1", "::ffff:127.0.0.1", "::ffff:169.254.169.254", "64:ff9b::a9fe:a9fe",
        "169.254.169.254", "fe80::1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "fc00::1",
        "100.64.0.1", "100.100.100.200", "0.0.0.0", "224.0.0.1",
        "2002:a9fe:a9fe::1", "2001:0:4136:e378:8000:63bf:80ff:fffe", "2001:0:a00:5:8000:63bf:f7f7:f7f7",
    ],
)
def test_rejects_non_public_address(ip):
    assert is_public_address(ip) is False


@pytest.mark.parametrize(
    "ip",
    ["93.184.216.34", "2001:4860:4860::8888", "64:ff9b::808:808", "2002:808:808::1",
     "2001:0:4136:e378:8000:63bf:f7f7:f7f7"],
)
def test_accepts_public_address(ip):
    assert is_public_address(ip) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://[::ffff:a9fe:a9fe]/",
        "https://[64:ff9b::a9fe:a9fe]/",
        "https://100.100.100.200/",
        "https://mixed.example/",
        "https://internal.example/",
        "file:///etc/passwd",
    ],
)
def test_rejects_non_public_destination(url):
    with pytest.raises(UnsafeDestinationError):
        resolve_public_addresses(url)


def _client(responses, seen):
    def handler(request):
        seen.append(request)
        return responses.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_pins_address_and_revalidates_redirects():
    seen: list[httpx.Request] = []
    responses = [httpx.Response(302, headers={"location": "https://b.example/x"}), httpx.Response(200, text="ok")]
    with _client(responses, seen) as client:
        resp, final_url = fetch_public(client, "https://a.example/start", headers={"Authorization": "t"})
    assert resp.text == "ok"
    assert final_url == "https://b.example/x"
    assert [r.url.host for r in seen] == ["93.184.216.34", "8.8.8.8"]
    assert [r.headers["host"] for r in seen] == ["a.example", "b.example"]
    assert seen[1].extensions["sni_hostname"] == "b.example"
    assert "authorization" not in seen[1].headers


def test_fetch_rejects_redirect_to_non_public_destination():
    seen: list[httpx.Request] = []
    responses = [httpx.Response(302, headers={"location": "https://internal.example/"})]
    with _client(responses, seen) as client, pytest.raises(UnsafeDestinationError):
        fetch_public(client, "https://a.example/")
    assert len(seen) == 1


def test_fetch_stops_after_three_redirects():
    seen: list[httpx.Request] = []
    responses = [httpx.Response(302, headers={"location": "/again"}) for _ in range(5)]
    with _client(responses, seen) as client, pytest.raises(UnsafeDestinationError):
        fetch_public(client, "https://a.example/")
    assert len(seen) == 4


def _task(worker_type, payload):
    return AgentTask(worker_type=worker_type, priority=TaskPriority.MEDIUM, payload=payload)


@pytest.fixture
def no_connection():
    with patch.object(httpx.Client, "send", side_effect=AssertionError("connection attempted")) as send, \
         patch("httpx.get", side_effect=AssertionError("connection attempted")):
        yield send


@pytest.mark.parametrize("url", ["https://internal.example/page", "http://169.254.169.254/latest/meta-data"])
def test_web_crawler_rejects_non_public_destination(no_connection, url):
    result = WebCrawlerWorker(MagicMock())._execute(_task(WorkerType.WEB_CRAWLER, {"target_url": url}))
    assert result.success is False
    assert "public" in result.error
    no_connection.assert_not_called()


@pytest.mark.parametrize("domain", ["internal.example", "127.0.0.1", "evil.example@10.0.0.5"])
def test_api_scanner_rejects_non_public_destination(no_connection, domain):
    result = ApiScannerWorker(MagicMock())._execute(_task(WorkerType.API_SCANNER, {"target_domain": domain}))
    assert result.success is False
    assert "public" in result.error
    no_connection.assert_not_called()


@pytest.mark.parametrize("domain", ["internal.example", "169.254.169.254", "evil.example@10.0.0.5"])
def test_competitor_tracker_rejects_non_public_destination(no_connection, domain):
    from workers.discovery.competitor_tracker import CompetitorTrackerWorker

    result = CompetitorTrackerWorker(MagicMock())._execute(
        _task(WorkerType.COMPETITOR_TRACKER, {"domain": domain, "watch_pages": ["/"]})
    )
    assert result.success is False
    no_connection.assert_not_called()


@pytest.mark.parametrize("website", ["https://internal.example", "http://169.254.169.254/latest", "127.0.0.1"])
def test_profile_enricher_rejects_non_public_destination(no_connection, website):
    from workers.enrichment.profile_enricher import ProfileEnricherWorker

    enriched = {"website": website}
    filled, sources = ProfileEnricherWorker(MagicMock())._enrich_company(enriched, ["description"])
    assert (filled, sources) == (0, [])
    no_connection.assert_not_called()


def test_competitor_tracker_fetches_validated_address():
    from workers.discovery.competitor_tracker import CompetitorTrackerWorker

    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text="<html><title>A</title></html>")

    real_client = httpx.Client
    with patch("httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
        result = CompetitorTrackerWorker(MagicMock())._execute(
            _task(WorkerType.COMPETITOR_TRACKER, {"domain": "a.example", "watch_pages": ["/"], "track_jobs": False})
        )
    assert result.success is True
    assert [r.url.host for r in seen] == ["93.184.216.34"]
    assert seen[0].headers["host"] == "a.example"
    assert result.data["snapshots"][0]["url"] == "https://a.example/"
