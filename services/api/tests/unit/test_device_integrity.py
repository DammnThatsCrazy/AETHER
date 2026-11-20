"""Mobile app attestation: App Attest, Play Integrity, tokens, routes, ingestion.

App Attest is exercised against a locally built certificate chain shaped like
Apple's (root -> intermediate -> credential cert with the nonce extension); the
production verifier pins Apple's real root, which this test also loads.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from ingestion.device_integrity import app_attest, play_integrity, tokens
from ingestion.device_integrity.app_attest import AppAttestError, verify_attestation

APP_ID = "ABCDE12345.com.example.app"
CHALLENGE = "c" * 43
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


# ── tiny CBOR encoder (test-only) ───────────────────────────────────────────


def _head(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([(major << 5) | n])
    for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if n < 1 << (8 * size):
            return bytes([(major << 5) | info]) + n.to_bytes(size, "big")
    raise ValueError


def cbor(value) -> bytes:
    if isinstance(value, bytes):
        return _head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return _head(3, len(raw)) + raw
    if isinstance(value, int):
        return _head(0, value) if value >= 0 else _head(1, -1 - value)
    if isinstance(value, list):
        return _head(4, len(value)) + b"".join(cbor(v) for v in value)
    if isinstance(value, dict):
        return _head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError


# ── a PKI shaped like Apple's ───────────────────────────────────────────────


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject, issuer, pub, signer, *, ca: bool, extensions=()):
    builder = (
        x509.CertificateBuilder().subject_name(_name(subject)).issuer_name(_name(issuer))
        .public_key(pub).serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=1)).not_valid_after(NOW + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    for ext in extensions:
        builder = builder.add_extension(ext, critical=False)
    return builder.sign(signer, hashes.SHA384() if ca else hashes.SHA256())


ROOT_KEY = ec.generate_private_key(ec.SECP384R1())
INT_KEY = ec.generate_private_key(ec.SECP384R1())
ROOT = _cert("Test App Attestation Root CA", "Test App Attestation Root CA", ROOT_KEY.public_key(), ROOT_KEY, ca=True)
INTERMEDIATE = _cert("Test App Attestation CA 1", "Test App Attestation Root CA", INT_KEY.public_key(), ROOT_KEY, ca=True)


def _attestation(
    *, challenge=CHALLENGE, app_id=APP_ID, counter=0, aaguid=app_attest.AAGUID_PRODUCTION,
    wrong_nonce=False, cred_id_override=None, fmt="apple-appattest",
):
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    point = leaf_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    key_id = hashlib.sha256(point).digest()
    cred_id = cred_id_override or key_id
    auth_data = (
        hashlib.sha256(app_id.encode()).digest() + b"\x40" + counter.to_bytes(4, "big")
        + aaguid + len(cred_id).to_bytes(2, "big") + cred_id
    )
    nonce = hashlib.sha256(auth_data + hashlib.sha256(challenge.encode()).digest()).digest()
    if wrong_nonce:
        nonce = hashlib.sha256(b"other").digest()
    ext = x509.UnrecognizedExtension(app_attest.NONCE_OID, bytes.fromhex("3024a1220420") + nonce)
    leaf = _cert("credential", "Test App Attestation CA 1", leaf_key.public_key(), INT_KEY, ca=False, extensions=[ext])
    obj = {
        "fmt": fmt,
        "attStmt": {"x5c": [leaf.public_bytes(serialization.Encoding.DER),
                            INTERMEDIATE.public_bytes(serialization.Encoding.DER)], "receipt": b"r"},
        "authData": auth_data,
    }
    return base64.b64encode(key_id).decode(), base64.b64encode(cbor(obj)).decode()


def _verify(key_id, obj, **kw):
    return verify_attestation(key_id_b64=key_id, attestation_object_b64=obj, challenge=kw.pop("challenge", CHALLENGE),
                              app_ids=kw.pop("app_ids", [APP_ID]), root=ROOT, now=NOW, **kw)


def test_pinned_apple_root_loads_and_matches_its_fingerprint():
    root = app_attest.pinned_root()
    assert "Apple App Attestation Root CA" in root.subject.rfc4514_string()


def test_valid_attestation_verifies():
    key_id, obj = _attestation()
    result = _verify(key_id, obj)
    assert result.app_id == APP_ID and result.key_id == key_id


def test_development_environment_uses_its_aaguid():
    key_id, obj = _attestation(aaguid=app_attest.AAGUID_DEVELOPMENT)
    assert _verify(key_id, obj, environment="development").environment == "development"
    with pytest.raises(AppAttestError, match="environment_mismatch"):
        _verify(key_id, obj, environment="production")


@pytest.mark.parametrize(
    ("kwargs", "verify_kwargs", "reason"),
    [
        ({"wrong_nonce": True}, {}, "nonce_mismatch"),
        ({}, {"challenge": "a-different-challenge-value"}, "nonce_mismatch"),
        ({"app_id": "ZZZZZ.com.evil"}, {}, "app_id_not_allowed"),
        ({"counter": 1}, {}, "counter_not_zero"),
        ({"cred_id_override": b"x" * 32}, {}, "credential_id_mismatch"),
        ({"fmt": "packed"}, {}, "wrong_format"),
    ],
)
def test_invalid_attestations_are_rejected(kwargs, verify_kwargs, reason):
    key_id, obj = _attestation(**kwargs)
    with pytest.raises(AppAttestError, match=reason):
        _verify(key_id, obj, **verify_kwargs)


def test_key_id_must_match_the_credential_key():
    _key_id, obj = _attestation()
    other = base64.b64encode(hashlib.sha256(b"x").digest()).decode()
    with pytest.raises(AppAttestError, match="key_id_mismatch"):
        _verify(other, obj)


def test_chain_must_lead_to_the_trusted_root():
    key_id, obj = _attestation()
    with pytest.raises(AppAttestError, match="certificate_chain_invalid"):
        verify_attestation(key_id_b64=key_id, attestation_object_b64=obj, challenge=CHALLENGE,
                           app_ids=[APP_ID], root=app_attest.pinned_root(), now=NOW)


def test_expired_chain_is_rejected():
    key_id, obj = _attestation()
    with pytest.raises(AppAttestError, match="certificate_not_valid_now"):
        verify_attestation(key_id_b64=key_id, attestation_object_b64=obj, challenge=CHALLENGE,
                           app_ids=[APP_ID], root=ROOT, now=NOW + timedelta(days=400))


@pytest.mark.parametrize("junk", ["", "!!!", base64.b64encode(b"\xff\xff").decode()])
def test_garbage_is_rejected_not_crashing(junk):
    with pytest.raises(AppAttestError):
        _verify(base64.b64encode(b"k").decode(), junk)


# ── Play Integrity ──────────────────────────────────────────────────────────


RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SERVICE_ACCOUNT = json.dumps({
    "client_email": "verifier@project.iam.gserviceaccount.com",
    "private_key": RSA_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()).decode(),
    "private_key_id": "kid-1",
    "token_uri": "https://oauth2.googleapis.com/token",
})


def _payload(*, nonce=CHALLENGE, package="com.example.app", app_verdict="PLAY_RECOGNIZED",
             device=("MEETS_DEVICE_INTEGRITY",), ts=1_000_000, digests=("abc",)):
    return {
        "requestDetails": {"requestPackageName": package, "nonce": nonce, "timestampMillis": str(ts)},
        "appIntegrity": {"appRecognitionVerdict": app_verdict, "packageName": package,
                         "certificateSha256Digest": list(digests)},
        "deviceIntegrity": {"deviceRecognitionVerdict": list(device)},
    }


def _evaluate(payload, **kw):
    return play_integrity.evaluate_payload(
        payload, challenge=kw.pop("challenge", CHALLENGE), allowed_packages=["com.example.app"],
        certificate_digests=kw.pop("digests", ["abc"]), issued_at_ms=1_000_000, max_age_ms=300_000, **kw)


@pytest.mark.parametrize(
    ("device", "verdict"),
    [
        (("MEETS_STRONG_INTEGRITY", "MEETS_DEVICE_INTEGRITY"), "verified"),
        (("MEETS_DEVICE_INTEGRITY",), "verified"),
        (("MEETS_VIRTUAL_INTEGRITY",), "virtual"),
        (("MEETS_BASIC_INTEGRITY",), "basic"),
        ((), "failed"),
    ],
)
def test_device_verdicts(device, verdict):
    assert _evaluate(_payload(device=device)).verdict == verdict


def test_unrecognized_app_fails_even_on_a_good_device():
    assert _evaluate(_payload(app_verdict="UNRECOGNIZED_VERSION")).verdict == "failed"


def test_signing_certificate_digest_must_match_when_configured():
    result = _evaluate(_payload(digests=("other",)))
    assert result.verdict == "failed" and "certificate_digest_mismatch" in result.reasons


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (_payload(nonce="nope"), "nonce_mismatch"),
        (_payload(package="com.evil"), "package_not_allowed"),
        (_payload(ts=10_000_000), "timestamp_out_of_window"),
    ],
)
def test_request_mismatches_raise(payload, reason):
    with pytest.raises(play_integrity.PlayIntegrityError, match=reason):
        _evaluate(payload)


def test_service_account_assertion_is_a_valid_rs256_jwt():
    from cryptography.hazmat.primitives.asymmetric import padding

    token = play_integrity.service_account_assertion(json.loads(SERVICE_ACCOUNT), now=1_700_000_000)
    head, claims, sig = token.split(".")
    pad = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))  # noqa: E731
    assert json.loads(pad(head)) == {"alg": "RS256", "typ": "JWT", "kid": "kid-1"}
    body = json.loads(pad(claims))
    assert body["scope"] == play_integrity.SCOPE and body["exp"] - body["iat"] == 3600
    RSA_KEY.public_key().verify(pad(sig), f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())


@pytest.mark.asyncio
async def test_decode_token_uses_google_endpoints_via_transport():
    calls = []

    async def transport(method, url, headers, payload, is_form):
        calls.append((url, headers, payload, is_form))
        if "oauth2" in url:
            return 200, {"access_token": "at-1"}
        return 200, {"tokenPayloadExternal": _payload()}

    payload = await play_integrity.decode_token("itok", "com.example.app", SERVICE_ACCOUNT, transport)
    assert payload["requestDetails"]["nonce"] == CHALLENGE
    assert calls[0][3] is True and calls[0][2]["grant_type"].endswith("jwt-bearer")
    assert calls[1][0].endswith("/com.example.app:decodeIntegrityToken")
    assert calls[1][1]["Authorization"] == "Bearer at-1" and calls[1][2] == {"integrity_token": "itok"}


@pytest.mark.asyncio
async def test_google_auth_failure_is_reported():
    async def transport(*a):
        return 401, {}

    with pytest.raises(play_integrity.PlayIntegrityError, match="google_auth_failed"):
        await play_integrity.decode_token("itok", "com.example.app", SERVICE_ACCOUNT, transport)


# ── tokens ──────────────────────────────────────────────────────────────────


KEY = b"k" * 32


def test_token_round_trip_and_bindings():
    token, exp = tokens.issue_token(KEY, tenant_id="t1", anonymous_id="anon-1", platform="ios",
                                    verdict="verified", ttl_seconds=3600, now=1000)
    assert exp == 4600
    assert tokens.verify_token(KEY, token, tenant_id="t1", anonymous_id="anon-1", now=2000) == {
        "verdict": "verified", "platform": "ios"}
    assert tokens.verify_token(KEY, token, tenant_id="t2", anonymous_id="anon-1", now=2000) is None
    assert tokens.verify_token(KEY, token, tenant_id="t1", anonymous_id="anon-2", now=2000) is None
    assert tokens.verify_token(KEY, token, tenant_id="t1", anonymous_id="anon-1", now=5000) is None
    assert tokens.verify_token(b"x" * 32, token, tenant_id="t1", anonymous_id="anon-1", now=2000) is None
    body, sig = token.split(".")
    assert tokens.verify_token(KEY, body + "." + sig[:-2] + "AA", tenant_id="t1", anonymous_id="anon-1", now=2000) is None


# ── routes ──────────────────────────────────────────────────────────────────


class _Cache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl=0):
        self.store[key] = value

    async def set_nx(self, key, value, ttl=0):
        if key in self.store:
            return False
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace

    from config.settings import settings
    from dependencies.providers import get_cache
    from ingestion.device_integrity import routes

    monkeypatch.setattr(settings, "device_integrity", dataclasses.replace(
        settings.device_integrity, enabled=True, apple_app_ids=[APP_ID], token_secret="s3cret",
        play_package_names=["com.example.app"], play_service_account_json=SERVICE_ACCOUNT,
        play_certificate_digests=["abc"]))
    cache = _Cache()
    app = FastAPI()

    @app.middleware("http")
    async def tenant(request, call_next):
        request.state.tenant = SimpleNamespace(tenant_id="tenant-1")
        return await call_next(request)

    app.include_router(routes.router)
    app.dependency_overrides[get_cache] = lambda: cache
    return TestClient(app), monkeypatch


def _challenge(c, platform="ios", anon="anon-1"):
    r = c.post("/sdk/device-integrity/challenge", json={"platform": platform, "anonymousId": anon})
    assert r.status_code == 200, r.text
    return r.json()["challenge"]


def test_ios_flow_issues_a_verified_token_and_challenges_are_single_use(client):
    c, monkeypatch = client
    challenge = _challenge(c)
    key_id, obj = _attestation(challenge=challenge)
    monkeypatch.setattr(app_attest, "pinned_root", lambda: ROOT)
    monkeypatch.setattr(app_attest, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    body = {"platform": "ios", "anonymousId": "anon-1", "challenge": challenge, "keyId": key_id, "attestationObject": obj}
    r = c.post("/sdk/device-integrity/verify", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["verdict"] == "verified"
    key = tokens.token_key("s3cret", allow_ephemeral=False)
    assert tokens.verify_token(key, data["integrityToken"], tenant_id="tenant-1", anonymous_id="anon-1")["verdict"] == "verified"
    replay = c.post("/sdk/device-integrity/verify", json=body)
    assert replay.status_code == 400 and replay.json()["error"] == "challenge_unknown_or_used"


def test_forged_ios_attestation_yields_failed_verdict(client):
    c, monkeypatch = client
    challenge = _challenge(c)
    key_id, obj = _attestation(challenge=challenge)  # chain not under the pinned Apple root
    r = c.post("/sdk/device-integrity/verify", json={
        "platform": "ios", "anonymousId": "anon-1", "challenge": challenge, "keyId": key_id, "attestationObject": obj})
    assert r.json()["verdict"] == "failed"


def test_challenge_is_bound_to_install_and_platform(client):
    c, _ = client
    challenge = _challenge(c, anon="anon-1")
    r = c.post("/sdk/device-integrity/verify", json={
        "platform": "ios", "anonymousId": "anon-OTHER", "challenge": challenge, "keyId": "a", "attestationObject": "b"})
    assert r.json()["error"] == "challenge_mismatch"


def test_android_flow_with_stubbed_google(client):
    c, monkeypatch = client
    challenge = _challenge(c, platform="android")

    async def fake_decode(token, package, account, transport=None):
        import time as _t
        return _payload(nonce=challenge, ts=int(_t.time() * 1000), device=("MEETS_VIRTUAL_INTEGRITY",))

    monkeypatch.setattr(play_integrity, "decode_token", fake_decode)
    r = c.post("/sdk/device-integrity/verify", json={
        "platform": "android", "anonymousId": "anon-1", "challenge": challenge, "integrityToken": "itok"})
    assert r.status_code == 200, r.text
    assert r.json()["verdict"] == "virtual"


def test_disabled_and_unconfigured(client):
    c, monkeypatch = client
    from config.settings import settings

    monkeypatch.setattr(settings, "device_integrity", dataclasses.replace(settings.device_integrity, apple_app_ids=[]))
    challenge = _challenge(c)
    r = c.post("/sdk/device-integrity/verify", json={
        "platform": "ios", "anonymousId": "anon-1", "challenge": challenge, "keyId": "a", "attestationObject": "b"})
    assert r.status_code == 503 and r.json()["error"] == "app_attest_not_configured"
    monkeypatch.setattr(settings, "device_integrity", dataclasses.replace(settings.device_integrity, enabled=False))
    assert c.post("/sdk/device-integrity/challenge", json={"platform": "ios", "anonymousId": "a"}).status_code == 404


# ── ingestion and classification ───────────────────────────────────────────


def test_ingestion_verifies_and_strips_the_token(monkeypatch):
    from config.settings import settings
    from ingestion.ingestion.batch import _apply_device_integrity

    monkeypatch.setattr(settings, "device_integrity", dataclasses.replace(settings.device_integrity, token_secret="s3cret"))
    key = tokens.token_key("s3cret", allow_ephemeral=False)
    token, _ = tokens.issue_token(key, tenant_id="tenant-1", anonymous_id="anon-1", platform="android",
                                  verdict="failed", ttl_seconds=3600)
    normalized = {"anonymous_id": "anon-1", "context": {"device": {"model": "x", "integrity": {"token": token}}}}
    _apply_device_integrity(normalized, "tenant-1")
    assert "integrity" not in normalized["context"]["device"]
    assert normalized["server_context"]["device_integrity"] == {"verdict": "failed", "platform": "android"}
    assert token not in json.dumps(normalized)

    stolen = {"anonymous_id": "anon-2", "context": {"device": {"integrity": {"token": token}}}}
    _apply_device_integrity(stolen, "tenant-1")
    assert stolen["server_context"]["device_integrity"] == {"verdict": "invalid_token"}


def _project(server_context):
    from ingestion.silver.projectors.touchpoint_projector import TouchpointProjector

    return TouchpointProjector().project({
        "type": "page", "messageId": "evt-di-1", "timestamp": "2026-11-19T12:00:00Z",
        "context": {"tenantId": "tenant-a"}, "properties": {}, "server_context": server_context,
    }).rows[0]


def test_failed_attestation_is_automation():
    row = _project({"device_integrity": {"verdict": "failed", "platform": "ios"}})
    assert row["actor_type"] == "machine"
    assert "device_integrity:failed" in row["provenance"]["source_evidence_signals"]


@pytest.mark.parametrize("verdict", ["verified", "basic", "virtual", "invalid_token"])
def test_other_verdicts_are_evidence_only_never_human(verdict):
    row = _project({"device_integrity": {"verdict": verdict}})
    assert row["actor_type"] == "unknown"
    assert f"device_integrity:{verdict}" in row["provenance"]["source_evidence_signals"]
