"""Server-side verification of declared AI agents against published IP ranges."""

from __future__ import annotations

import ipaddress
import json

import pytest

from journeys.traffic import agent_verification as av


def _first_host(signature: str) -> str:
    data = json.loads(av.RANGES_PATH.read_text(encoding="utf-8"))
    prefix = data["signatures"][signature]["prefixes"][0]
    return str(next(ipaddress.ip_network(prefix).hosts(), ipaddress.ip_network(prefix).network_address))


def test_range_file_is_well_formed() -> None:
    data = json.loads(av.RANGES_PATH.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    for signature, entry in data["signatures"].items():
        assert entry["provider"] and entry["source_url"].startswith("https://")
        assert entry["prefixes"], signature
        for prefix in entry["prefixes"]:
            ipaddress.ip_network(prefix)


def test_no_agent_declared_returns_none() -> None:
    assert av.server_agent_evidence("Mozilla/5.0 Safari/605.1", "8.8.8.8") is None


def test_ip_inside_published_range_is_verified() -> None:
    ip = _first_host("chatgpt-user")
    evidence = av.server_agent_evidence("Mozilla/5.0 ChatGPT-User/1.0", ip)
    assert evidence == {"ua_signature": "chatgpt-user", "verification": "provider_ip_range"}


def test_ip_outside_published_range_is_a_mismatch() -> None:
    evidence = av.server_agent_evidence("Mozilla/5.0 ChatGPT-User/1.0", "192.0.2.10")
    assert evidence["verification"] == "ip_mismatch"


def test_provider_without_published_ranges_stays_unverified() -> None:
    evidence = av.server_agent_evidence("Claude-User/1.0", "192.0.2.10")
    assert evidence == {"ua_signature": "claude-user", "verification": "unverified"}


def test_missing_client_ip() -> None:
    assert av.server_agent_evidence("GPTBot/1.2", None)["verification"] == "no_client_ip"


@pytest.mark.parametrize("bad", ["", "not-an-ip", "999.1.1.1"])
def test_malformed_ip_never_verifies(bad: str) -> None:
    assert av.ip_in_provider_range("gptbot", bad) is False


def test_evidence_never_contains_the_ip() -> None:
    ip = _first_host("gptbot")
    evidence = av.server_agent_evidence("GPTBot/1.2", ip)
    assert ip not in json.dumps(evidence)


class _Client:
    def __init__(self, host: str) -> None:
        self.host = host


class _Request:
    def __init__(self, headers: dict, host: str) -> None:
        self.headers = headers
        self.client = _Client(host)


def test_batch_server_context_carries_agent_verification_without_ip() -> None:
    from ingestion.ingestion.batch import _build_server_context

    ip = _first_host("gptbot")
    ctx = _build_server_context(_Request({"User-Agent": "GPTBot/1.2"}, ip), "tenant_1")
    assert ctx["agent_verification"] == {"ua_signature": "gptbot", "verification": "provider_ip_range"}
    assert ip not in json.dumps(ctx)


def test_batch_server_context_unchanged_for_ordinary_browsers() -> None:
    from ingestion.ingestion.batch import _build_server_context

    ctx = _build_server_context(_Request({"User-Agent": "Mozilla/5.0 Safari"}, "192.0.2.1"), "tenant_1")
    assert ctx is None or "agent_verification" not in ctx


def test_spoofed_forwarded_for_from_untrusted_peer_cannot_verify() -> None:
    from ingestion.ingestion.batch import _build_server_context

    ip = _first_host("gptbot")
    req = _Request({"User-Agent": "GPTBot/1.2", "X-Forwarded-For": ip}, "192.0.2.1")
    assert _build_server_context(req, "tenant_1")["agent_verification"]["verification"] == "ip_mismatch"
