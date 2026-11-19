"""Server SDK forwarded request evidence: verify at ingestion, never store raw.

See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from journeys.traffic import agent_verification as av
from journeys.traffic import web_bot_auth as wba
from journeys.traffic.forwarded_evidence import verify_forwarded_request_evidence

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "web_bot_auth_reference_vectors.json").read_text()
)


def _gptbot_ip() -> str:
    data = json.loads(av.RANGES_PATH.read_text(encoding="utf-8"))
    net = ipaddress.ip_network(data["signatures"]["chatgpt-user"]["prefixes"][0])
    return str(next(net.hosts(), net.network_address))


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _ref_directory(monkeypatch: pytest.MonkeyPatch):
    x = FIXTURE["public_key_x"]
    pub = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(x + "=" * (-len(x) % 4)))
    signer = FIXTURE["signature_agent"]
    monkeypatch.setattr(
        wba, "_load_directories",
        lambda: ({signer: wba._Signer(signer, "testprov", "testprod", "agent")},
                 {FIXTURE["keyid"]: wba._Key(signer, FIXTURE["keyid"], pub, None, None)}),
    )
    wba._reset_replay_cache_for_tests()
    yield
    wba._reset_replay_cache_for_tests()


def _signed_evidence(name: str = "string", received: float | None = None) -> dict:
    v = FIXTURE["vectors"][name]
    return {
        "receivedAt": _iso(received if received is not None else FIXTURE["now"]),
        "userAgent": "Mozilla/5.0 Chrome/131.0",
        "method": FIXTURE["method"],
        "authority": FIXTURE["authority"],
        "path": FIXTURE["path"],
        "signature": v["Signature"],
        "signatureInput": v["Signature-Input"],
        **({"signatureAgent": v["Signature-Agent"]} if "Signature-Agent" in v else {}),
    }


def test_forwarded_ip_in_published_range_is_verified_and_marked_tenant_observed() -> None:
    out = verify_forwarded_request_evidence(
        {"userAgent": "ChatGPT-User/1.0", "clientIp": _gptbot_ip()}, time.time()
    )
    assert out["observed_by"] == "tenant_server"
    assert out["agent_verification"] == {
        "ua_signature": "chatgpt-user", "verification": "provider_ip_range", "observed_by": "tenant_server",
    }


def test_forwarded_web_bot_auth_signature_verifies_at_received_time() -> None:
    out = verify_forwarded_request_evidence(_signed_evidence(), ingest_now=FIXTURE["now"] + 600)
    assert out["web_bot_auth"]["verification"] == wba.VERIFIED
    assert out["web_bot_auth"]["observed_by"] == "tenant_server"


def test_received_at_cannot_move_verification_far_into_the_past() -> None:
    out = verify_forwarded_request_evidence(_signed_evidence(), ingest_now=FIXTURE["now"] + 3 * 86400)
    assert out["web_bot_auth"]["verification"] == wba.INVALID


def test_received_at_in_the_future_is_rejected() -> None:
    ev = _signed_evidence(received=FIXTURE["now"])
    out = verify_forwarded_request_evidence(ev, ingest_now=FIXTURE["now"] - 3600)
    assert out["web_bot_auth"]["verification"] == wba.INVALID


def test_forwarded_signature_for_another_host_fails() -> None:
    ev = {**_signed_evidence(), "authority": "someone-else.example"}
    out = verify_forwarded_request_evidence(ev, ingest_now=FIXTURE["now"])
    assert out["web_bot_auth"]["verification"] == wba.INVALID


def test_ordinary_browser_request_records_nothing() -> None:
    assert verify_forwarded_request_evidence(
        {"userAgent": "Mozilla/5.0 Safari", "clientIp": "192.0.2.4", "receivedAt": _iso(time.time())},
        time.time(),
    ) is None


@pytest.mark.parametrize("raw", [None, "x", 3, [], {}])
def test_junk_is_ignored(raw) -> None:
    assert verify_forwarded_request_evidence(raw, time.time()) is None


def test_verdict_contains_no_ip_or_signature() -> None:
    ip = _gptbot_ip()
    ev = {**_signed_evidence(), "userAgent": "ChatGPT-User/1.0", "clientIp": ip}
    dumped = json.dumps(verify_forwarded_request_evidence(ev, FIXTURE["now"]))
    assert ip not in dumped
    assert FIXTURE["vectors"]["string"]["Signature"].split(":")[1] not in dumped


# ── Ingestion: the raw evidence is always removed ───────────────────────────


def test_event_context_accepts_request_evidence() -> None:
    from ingestion.ingestion.batch import EventContext

    ctx = EventContext(requestEvidence={"userAgent": "GPTBot/1.2", "receivedAt": _iso(time.time())})
    assert ctx.requestEvidence["userAgent"] == "GPTBot/1.2"


def test_ingestion_strips_raw_evidence_and_keeps_verdicts() -> None:
    from ingestion.ingestion.batch import _apply_forwarded_request_evidence

    ip = _gptbot_ip()
    normalized = {"context": {"requestEvidence": {"userAgent": "ChatGPT-User/1.0", "clientIp": ip}}}
    _apply_forwarded_request_evidence(normalized)
    assert "requestEvidence" not in normalized["context"]
    assert normalized["server_context"]["forwarded_request"]["agent_verification"]["verification"] == "provider_ip_range"
    assert ip not in json.dumps(normalized)


def test_ingestion_strips_raw_evidence_even_when_nothing_verifies() -> None:
    from ingestion.ingestion.batch import _apply_forwarded_request_evidence

    normalized = {"context": {"requestEvidence": {"userAgent": "Safari", "clientIp": "192.0.2.9"}}}
    _apply_forwarded_request_evidence(normalized)
    assert normalized == {"context": {}}


def test_ingestion_keeps_aethers_own_server_context() -> None:
    from ingestion.ingestion.batch import _apply_forwarded_request_evidence

    normalized = {
        "context": {"requestEvidence": {"userAgent": "GPTBot/1.2", "clientIp": "192.0.2.9"}},
        "server_context": {"enrichment_state": "ready"},
    }
    _apply_forwarded_request_evidence(normalized)
    assert normalized["server_context"]["enrichment_state"] == "ready"
    assert normalized["server_context"]["forwarded_request"]["agent_verification"]["verification"] == "ip_mismatch"


# ── Classification of forwarded evidence ────────────────────────────────────


def _project(server_context: dict, context: dict | None = None) -> dict:
    from ingestion.silver.projectors.touchpoint_projector import TouchpointProjector

    result = TouchpointProjector().project({
        "type": "page", "messageId": "evt-fwd-1", "timestamp": "2026-11-19T12:00:00Z",
        "context": {"tenantId": "tenant-a", **(context or {})},
        "properties": {}, "server_context": server_context,
    })
    return result.rows[0]


def test_forwarded_ip_verified_agent_is_server_observed_not_platform_verified() -> None:
    row = _project({"forwarded_request": {"observed_by": "tenant_server", "agent_verification": {
        "ua_signature": "chatgpt-user", "verification": "provider_ip_range", "observed_by": "tenant_server"}}})
    assert row["actor_type"] == "agent"
    assert row["proof_level"] == "server_observed"
    assert row["verification_level"] == "provider_ip_range_forwarded"


def test_forwarded_web_bot_auth_is_platform_verified_and_labelled_forwarded() -> None:
    row = _project({"forwarded_request": {"observed_by": "tenant_server", "web_bot_auth": {
        "verification": wba.VERIFIED, "signature_agent": "https://chatgpt.com",
        "provider": "openai", "product": "chatgpt", "actor_type": "agent", "observed_by": "tenant_server"}}})
    assert row["actor_type"] == "agent"
    assert row["proof_level"] == "platform_verified"
    assert row["verification_level"] == "web_bot_auth_forwarded"


def test_aethers_own_observation_wins_over_forwarded() -> None:
    row = _project({
        "agent_verification": {"ua_signature": "chatgpt-user", "verification": "provider_ip_range"},
        "forwarded_request": {"observed_by": "tenant_server", "agent_verification": {
            "ua_signature": "chatgpt-user", "verification": "ip_mismatch", "observed_by": "tenant_server"}},
    })
    assert row["verification_level"] == "provider_ip_range"


# ── End to end: Python SDK capture -> ingestion -> touchpoint ───────────────


def test_python_sdk_capture_round_trips_through_ingestion_and_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import sys

    sys.path.insert(
        0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "packages", "sdk", "python"))
    )
    from aether_agentic import capture_request_evidence
    from ingestion.ingestion.batch import _apply_forwarded_request_evidence

    v = FIXTURE["vectors"]["dict"]
    evidence = capture_request_evidence(
        method=FIXTURE["method"],
        url=f"https://{FIXTURE['authority']}{FIXTURE['path']}",
        headers={
            "Host": FIXTURE["authority"],
            "User-Agent": "Mozilla/5.0 Chrome/131.0",
            "Signature": v["Signature"],
            "Signature-Input": v["Signature-Input"],
            "Signature-Agent": v["Signature-Agent"],
        },
        client_ip="192.0.2.50",
        received_at=datetime.fromtimestamp(FIXTURE["now"], tz=timezone.utc),
    )
    normalized = {"context": {"tenantId": "tenant-a", "requestEvidence": evidence}}
    from ingestion.ingestion import batch

    monkeypatch.setattr(batch.time, "time", lambda: FIXTURE["now"] + 30)  # ingested shortly after receipt
    _apply_forwarded_request_evidence(normalized)
    assert "requestEvidence" not in normalized["context"]
    row = _project(normalized["server_context"])
    assert row["actor_type"] == "agent"
    assert row["proof_level"] == "platform_verified"
    assert row["verification_level"] == "web_bot_auth_forwarded"
