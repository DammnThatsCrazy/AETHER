"""Web Bot Auth (RFC 9421 HTTP Message Signatures) verification.

Interop vectors were signed by Cloudflare's reference ``web-bot-auth`` library;
edge cases are signed here with a throwaway key and a hand-written signature base.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from journeys.traffic import web_bot_auth as wba

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "web_bot_auth_reference_vectors.json").read_text()
)
REF_SIGNER = FIXTURE["signature_agent"]
REF_KID = FIXTURE["keyid"]
NOW = FIXTURE["now"]


def _pub(x: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(x + "=" * (-len(x) % 4)))


TEST_PRIV = Ed25519PrivateKey.generate()
TEST_KID = "test-kid-1"
TEST_SIGNER = "https://agent.example"


@pytest.fixture(autouse=True)
def _directory(monkeypatch: pytest.MonkeyPatch):
    signers = {
        REF_SIGNER: wba._Signer(REF_SIGNER, "testprov", "testprod", "agent"),
        TEST_SIGNER: wba._Signer(TEST_SIGNER, "exampleai", "browser", "agent"),
    }
    keys = {
        REF_KID: wba._Key(REF_SIGNER, REF_KID, _pub(FIXTURE["public_key_x"]), None, None),
        TEST_KID: wba._Key(TEST_SIGNER, TEST_KID, TEST_PRIV.public_key(), None, None),
    }
    monkeypatch.setattr(wba, "_load_directories", lambda: (signers, keys))
    wba._reset_replay_cache_for_tests()
    yield
    wba._reset_replay_cache_for_tests()


def _ref_request(name: str, authority: str = FIXTURE["authority"]) -> wba.SignedRequest:
    return wba.SignedRequest(
        method=FIXTURE["method"], authority=authority, path=FIXTURE["path"],
        headers=FIXTURE["vectors"][name],
    )


@pytest.mark.parametrize("name", ["dict", "string", "none"])
def test_reference_library_signatures_verify(name: str) -> None:
    result = wba.verify_web_bot_auth(_ref_request(name), now=NOW)
    assert result["verification"] == wba.VERIFIED
    assert result["signature_agent"] == REF_SIGNER
    assert result["provider"] == "testprov"


@pytest.mark.parametrize("name", ["dict", "string", "none"])
def test_signature_is_bound_to_the_authority(name: str) -> None:
    result = wba.verify_web_bot_auth(_ref_request(name, authority="other.example"), now=NOW)
    assert result["verification"] == wba.INVALID


def test_tampered_signature_agent_header_fails() -> None:
    headers = dict(FIXTURE["vectors"]["string"])
    headers["Signature-Agent"] = '"https://attacker.example"'
    req = wba.SignedRequest(method="POST", authority=FIXTURE["authority"], path="/v1/batch", headers=headers)
    assert wba.verify_web_bot_auth(req, now=NOW)["verification"] in (wba.UNKNOWN_SIGNER, wba.INVALID)


def test_expired_signature() -> None:
    assert wba.verify_web_bot_auth(_ref_request("string"), now=NOW + 3600)["verification"] == wba.EXPIRED


def test_replayed_nonce_is_flagged() -> None:
    assert wba.verify_web_bot_auth(_ref_request("string"), now=NOW)["verification"] == wba.VERIFIED
    assert wba.verify_web_bot_auth(_ref_request("string"), now=NOW)["verification"] == wba.REPLAY


def test_no_signature_headers_returns_none() -> None:
    req = wba.SignedRequest(method="GET", authority="a.example", path="/", headers={"User-Agent": "x"})
    assert wba.verify_web_bot_auth(req, now=NOW) is None


def test_plain_http_signature_without_web_bot_auth_tag_is_ignored() -> None:
    headers = {
        "Signature-Input": 'sig1=("@authority");created=1;keyid="k";tag="other"',
        "Signature": "sig1=:AAAA:",
    }
    req = wba.SignedRequest(method="GET", authority="a.example", path="/", headers=headers)
    assert wba.verify_web_bot_auth(req, now=NOW) is None


# ── Hand-built signatures (independent signature base) ──────────────────────


def _sign(params: str, base_lines: list[str], extra_headers: dict | None = None) -> dict:
    base = "\n".join(base_lines + [f'"@signature-params": {params}'])
    sig = base64.b64encode(TEST_PRIV.sign(base.encode())).decode()
    return {"Signature-Input": f"sig1={params}", "Signature": f"sig1=:{sig}:", **(extra_headers or {})}


def _params(components: str, created: int = NOW - 10, expires: int = NOW + 290, kid: str = TEST_KID) -> str:
    return f'({components});created={created};keyid="{kid}";alg="ed25519";expires={expires};nonce="n-{created}-{kid}";tag="web-bot-auth"'


def test_hand_built_signature_with_method_and_path_verifies() -> None:
    params = _params('"@authority" "@method" "@path" "signature-agent"')
    headers = _sign(
        params,
        ['"@authority": ingest.aether.test', '"@method": POST', '"@path": /v1/batch',
         '"signature-agent": "https://agent.example"'],
        {"Signature-Agent": '"https://agent.example"'},
    )
    req = wba.SignedRequest(method="post", authority="INGEST.aether.test:443", path="/v1/batch", headers=headers)
    result = wba.verify_web_bot_auth(req, now=NOW)
    assert result["verification"] == wba.VERIFIED
    assert result["provider"] == "exampleai"


def test_authority_must_be_covered() -> None:
    params = _params('"@method"')
    headers = _sign(params, ['"@method": POST'])
    req = wba.SignedRequest(method="POST", authority="ingest.aether.test", path="/", headers=headers)
    assert wba.verify_web_bot_auth(req, now=NOW)["reason"] == "authority_not_covered"


def test_signature_agent_header_must_be_covered_when_present() -> None:
    params = _params('"@authority"')
    headers = _sign(params, ['"@authority": ingest.aether.test'], {"Signature-Agent": '"https://agent.example"'})
    req = wba.SignedRequest(method="POST", authority="ingest.aether.test", path="/", headers=headers)
    assert wba.verify_web_bot_auth(req, now=NOW)["reason"] == "signature_agent_not_covered"


def test_validity_window_over_24h_is_rejected() -> None:
    params = _params('"@authority"', created=NOW - 10, expires=NOW + 2 * 86400)
    headers = _sign(params, ['"@authority": ingest.aether.test'])
    req = wba.SignedRequest(method="POST", authority="ingest.aether.test", path="/", headers=headers)
    assert wba.verify_web_bot_auth(req, now=NOW)["reason"] == "bad_validity_window"


def test_unknown_key_is_unknown_signer_not_verified() -> None:
    params = _params('"@authority"', kid="not-in-snapshot")
    headers = _sign(params, ['"@authority": ingest.aether.test'])
    req = wba.SignedRequest(method="POST", authority="ingest.aether.test", path="/", headers=headers)
    assert wba.verify_web_bot_auth(req, now=NOW)["verification"] == wba.UNKNOWN_SIGNER


def test_key_from_one_signer_cannot_vouch_for_another() -> None:
    params = _params('"@authority" "signature-agent"')
    headers = _sign(
        params,
        ['"@authority": ingest.aether.test', '"signature-agent": "https://signature-agent.test"'],
        {"Signature-Agent": '"https://signature-agent.test"'},
    )
    req = wba.SignedRequest(method="POST", authority="ingest.aether.test", path="/", headers=headers)
    assert wba.verify_web_bot_auth(req, now=NOW)["verification"] == wba.UNKNOWN_SIGNER


def test_malformed_headers_are_invalid_not_errors() -> None:
    req = wba.SignedRequest(
        method="POST", authority="a", path="/",
        headers={"Signature-Input": "sig1=(\"@authority\";tag=", "Signature": "sig1=:!!:"},
    )
    assert wba.verify_web_bot_auth(req, now=NOW)["verification"] == wba.INVALID


def test_result_contains_no_signature_material() -> None:
    result = wba.verify_web_bot_auth(_ref_request("string"), now=NOW)
    dumped = json.dumps(result)
    sig = FIXTURE["vectors"]["string"]["Signature"].split(":")[1]
    assert sig not in dumped


def test_snapshot_file_keys_match_their_thumbprints() -> None:
    import hashlib

    data = json.loads(wba.DIRECTORIES_PATH.read_text())
    assert data["signers"], "snapshot must list at least one signer"
    for origin, entry in data["signers"].items():
        assert wba.normalize_origin(origin) == origin
        assert entry["actor_type"] in ("agent", "machine")
        for key in entry["keys"]:
            canonical = json.dumps({"crv": "Ed25519", "kty": "OKP", "x": key["x"]}, separators=(",", ":"), sort_keys=True)
            thumb = base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()
            assert key["kid"] == thumb


# ── End to end: request -> batch server_context -> touchpoint row ───────────


class _URL:
    def __init__(self, netloc: str, path: str) -> None:
        self.scheme, self.netloc, self.path, self.query = "https", netloc, path, ""


class _Client:
    def __init__(self, host: str) -> None:
        self.host = host


class _Request:
    def __init__(self, headers: dict, host: str = "192.0.2.1") -> None:
        self.headers = {"Host": FIXTURE["authority"], **headers}
        self.client = _Client(host)
        self.method = "POST"
        self.url = _URL(FIXTURE["authority"], "/v1/batch")


def test_batch_server_context_carries_verified_web_bot_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    from ingestion.ingestion import batch

    monkeypatch.setattr(wba.time, "time", lambda: NOW)
    ctx = batch._build_server_context(_Request(FIXTURE["vectors"]["dict"]), "tenant_1")
    assert ctx["web_bot_auth"]["verification"] == wba.VERIFIED


def test_untrusted_peer_cannot_choose_the_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    from ingestion.ingestion import batch

    monkeypatch.setattr(wba.time, "time", lambda: NOW)
    headers = {**FIXTURE["vectors"]["dict"], "Host": "other.example", "X-Forwarded-Host": FIXTURE["authority"]}
    ctx = batch._build_server_context(_Request(headers), "tenant_1")
    assert ctx["web_bot_auth"]["verification"] == wba.INVALID


def _project(server_context: dict, context: dict | None = None) -> dict:
    from ingestion.silver.projectors.touchpoint_projector import TouchpointProjector

    result = TouchpointProjector().project({
        "type": "page", "messageId": "evt-wba-1", "timestamp": "2026-11-19T12:00:00Z",
        "context": {"tenantId": "tenant-a", "userAgent": "Mozilla/5.0 Chrome/131.0", **(context or {})},
        "properties": {}, "server_context": server_context,
    })
    return result.rows[0]


def test_verified_signature_makes_a_normal_chrome_ua_a_verified_agent() -> None:
    row = _project({"web_bot_auth": {
        "verification": wba.VERIFIED, "signature_agent": "https://chatgpt.com",
        "provider": "openai", "product": "chatgpt", "actor_type": "agent",
    }})
    assert row["actor_type"] == "agent"
    assert row["proof_level"] == "platform_verified"
    assert row["verification_level"] == "web_bot_auth"
    assert row["ai_provider"] == "openai"


def test_unknown_signer_is_declared_automation() -> None:
    row = _project({"web_bot_auth": {"verification": wba.UNKNOWN_SIGNER, "signature_agent": "https://x.example"}})
    assert row["actor_type"] == "machine"
    assert row["proof_level"] != "platform_verified"
    assert "actor:web_bot_auth_unknown_signer" in row["provenance"]["source_evidence_signals"]


@pytest.mark.parametrize("state", [wba.INVALID, wba.EXPIRED, wba.REPLAY])
def test_failed_signatures_prove_nothing(state: str) -> None:
    row = _project({"web_bot_auth": {"verification": state}})
    assert row["actor_type"] == "unknown"
    assert f"actor:{state}" in row["provenance"]["source_evidence_signals"]


# ── Verified-link redirects ─────────────────────────────────────────────────


def test_redirect_verified_agent_keeps_handoff() -> None:
    from journeys.traffic.referral_links import _apply_web_bot_auth

    ev = {"verification": wba.VERIFIED, "actor_type": "agent"}
    assert _apply_web_bot_auth("browser", False, ev) == ("web_bot_auth_agent", False)


def test_redirect_verified_crawler_is_machine() -> None:
    from journeys.traffic.referral_links import _apply_web_bot_auth

    ev = {"verification": wba.VERIFIED, "actor_type": "machine"}
    assert _apply_web_bot_auth("browser", False, ev) == ("web_bot_auth_machine", True)


@pytest.mark.parametrize("state", [wba.INVALID, wba.EXPIRED, wba.REPLAY, None])
def test_redirect_unverified_signature_changes_nothing(state) -> None:
    from journeys.traffic.referral_links import _apply_web_bot_auth

    ev = {"verification": state} if state else None
    assert _apply_web_bot_auth("crawler_discovery", True, ev) == ("crawler_discovery", True)
