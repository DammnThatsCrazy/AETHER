"""Apple AdAttributionKit / SKAdNetwork postback ingestion: version-tolerant
parsing, idempotency, malformed rejection, and REAL P-256 attribution-signature
verification.

These rows are campaign-level platform evidence (proof_level
'platform_verified') and are explicitly separate from user-level deterministic
acquisition evidence — no touchpoints are created here.

Signature verification is exercised with genuine ECDSA P-256 / SHA-256
cryptography: a test keypair is generated, the postback is signed over the
module's reconstructed signed-parameter string, and the test public key is
injected through the ``_apple_public_key`` seam.  The production path is never
weakened — it always loads Apple's configured key.
"""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key
from fastapi import HTTPException

from services.attribution import apple_postbacks as module
from services.attribution.apple_postbacks import (
    APPLE_SKADNETWORK_PUBLIC_KEY_B64,
    ApplePostbackRequest,
    MalformedPostbackError,
    ingest_apple_postback,
    reduce_postback,
)
from shared.auth.auth import Role, TenantContext


@pytest.fixture(autouse=True)
def _local_repository(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(module, "_pool", no_pool)
    module.reset_apple_postbacks_for_tests()
    yield
    module.reset_apple_postbacks_for_tests()


@pytest.fixture
def signing_key() -> ec.EllipticCurvePrivateKey:
    """Per-test P-256 keypair standing in for Apple's verification key."""

    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(autouse=True)
def _inject_test_verifier(
    monkeypatch: pytest.MonkeyPatch, signing_key: ec.EllipticCurvePrivateKey
):
    """Route verification at the test public key without touching prod config."""

    monkeypatch.setattr(module, "_apple_public_key", lambda: signing_key.public_key())
    yield


def _sign(payload: dict, key: ec.EllipticCurvePrivateKey) -> dict:
    """Return a copy of ``payload`` with a real attribution-signature attached."""

    message = module._build_signed_message(payload, payload.get("version"))
    assert message is not None, "test payload must be a known, fully-populated version"
    signature = key.sign(message.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    signed = dict(payload)
    signed["attribution-signature"] = base64.b64encode(signature).decode("ascii")
    return signed


# ── Fixtures: unsigned / signed / tampered / unknown / malformed ─────────────

@pytest.fixture
def v4_unsigned() -> dict:
    """AdAttributionKit / SKAdNetwork 4.0 postback WITHOUT a signature."""

    return {
        "version": "4.0",
        "postback-id": "pb-0001",
        "transaction-id": "txn-0001",
        "ad-network-id": "example123.adattributionkit",
        "source-identifier": "3120",
        "app-id": 123456789,
        "source-app-id": 987654321,
        "fidelity-type": 1,
        "did-win": True,
        "redownload": False,
        "coarse-conversion-value": "high",
        "fine-conversion-value": 42,
        "postback-sequence-index": 0,
        "postback-environment": "sandbox",
    }


@pytest.fixture
def signed_postback(v4_unsigned: dict, signing_key: ec.EllipticCurvePrivateKey) -> dict:
    return _sign(v4_unsigned, signing_key)


@pytest.fixture
def tampered_postback(signed_postback: dict) -> dict:
    """A validly-signed postback whose signed field was altered after signing."""

    forged = dict(signed_postback)
    forged["source-identifier"] = "9999"  # was covered by the signature
    return forged


@pytest.fixture
def unknown_version_postback(signed_postback: dict) -> dict:
    """Present signature, but a version whose signed-field order we don't know."""

    unknown = dict(signed_postback)
    unknown["version"] = "9.9"
    return unknown


@pytest.fixture
def malformed_postback() -> dict:
    """No postback/transaction id and no campaign identity."""

    return {"version": "4.0", "conversion-value": 7}


TENANT = TenantContext(tenant_id="tenant-a", role=Role.SERVICE)


# ── Parsing ──────────────────────────────────────────────────────────────────

def test_reduce_is_version_tolerant_across_spellings():
    kebab = reduce_postback(
        {
            "version": "3.0",
            "transaction-id": "txn-9",
            "ad-network-id": "net.example",
            "campaign-id": 42,
            "conversion-value": "12",
            "environment": "production",
        }
    )
    camel = reduce_postback(
        {
            "version": "4.0",
            "transactionId": "txn-9",
            "adNetworkId": "net.example",
            "sourceIdentifier": "42",
            "coarseConversionValue": "medium",
            "fineConversionValue": 12,
        }
    )
    assert kebab["idempotency_key"] == camel["idempotency_key"] == "txn-9"
    assert kebab["reduced_payload"]["source_identifier"] == "42"
    assert camel["reduced_payload"]["source_identifier"] == "42"
    assert kebab["fine_conversion_value"] == 12
    assert camel["coarse_conversion_value"] == "medium"
    assert kebab["proof_level"] == "platform_verified"
    # No signature on either → honestly "missing", never "verified".
    assert kebab["signature_status"] == "missing"
    assert camel["signature_status"] == "missing"


def test_reduce_rejects_malformed_payloads(malformed_postback: dict):
    with pytest.raises(MalformedPostbackError):
        reduce_postback(malformed_postback)
    with pytest.raises(MalformedPostbackError):
        reduce_postback({})
    with pytest.raises(MalformedPostbackError):
        reduce_postback({"postback-id": "pb-1"})  # id but no campaign identity


# ── Signature verification (real ECDSA P-256 / SHA-256) ──────────────────────

def test_shipped_apple_key_is_structurally_valid_p256():
    """The embedded Apple key must decode to a real SECP256R1 public key."""

    key = load_der_public_key(base64.b64decode(APPLE_SKADNETWORK_PUBLIC_KEY_B64))
    assert isinstance(key, ec.EllipticCurvePublicKey)
    assert key.curve.name == "secp256r1"


def test_valid_signature_is_verified(signed_postback: dict):
    reduced = reduce_postback(signed_postback)
    assert reduced["signature_status"] == "verified"
    assert reduced["proof_level"] == "platform_verified"


def test_tampered_signature_is_invalid(tampered_postback: dict):
    reduced = reduce_postback(tampered_postback)
    assert reduced["signature_status"] == "invalid"


def test_signature_from_wrong_key_is_invalid(v4_unsigned: dict):
    """A signature made with a DIFFERENT key must not verify (real crypto)."""

    attacker_key = ec.generate_private_key(ec.SECP256R1())
    forged = _sign(v4_unsigned, attacker_key)  # signs, but not with the trusted key
    assert reduce_postback(forged)["signature_status"] == "invalid"


def test_unknown_version_signature_is_unverified_not_verified(
    unknown_version_postback: dict,
):
    reduced = reduce_postback(unknown_version_postback)
    # We cannot reconstruct the signed string for an unknown version, so we are
    # honest: low-trust "unverified", never "verified", never "invalid".
    assert reduced["signature_status"] == "unverified"


def test_missing_signature_is_missing(v4_unsigned: dict):
    assert reduce_postback(v4_unsigned)["signature_status"] == "missing"


def test_v3_round_trip_verify(signing_key: ec.EllipticCurvePrivateKey):
    v3 = _sign(
        {
            "version": "3.0",
            "transaction-id": "txn-3",
            "ad-network-id": "net.example",
            "campaign-id": 55,
            "app-id": 111,
            "source-app-id": 222,
            "fidelity-type": 1,
            "did-win": True,
            "redownload": False,
        },
        signing_key,
    )
    assert reduce_postback(v3)["signature_status"] == "verified"


# ── Route behaviour ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_stores_verified_once_and_acknowledges_duplicates(
    signed_postback: dict,
):
    first = await ingest_apple_postback(
        ApplePostbackRequest(postback=signed_postback), TENANT
    )
    second = await ingest_apple_postback(
        ApplePostbackRequest(postback=dict(signed_postback)), TENANT
    )

    assert first["postback"]["duplicate"] is False
    assert second["postback"]["duplicate"] is True
    assert first["postback"]["apple_postback_id"] == second["postback"]["apple_postback_id"]
    assert len(module._LOCAL_APPLE_POSTBACKS) == 1

    stored = first["postback"]
    assert stored["environment"] == "sandbox"
    assert stored["coarse_conversion_value"] == "high"
    assert stored["fine_conversion_value"] == 42
    assert stored["proof_level"] == "platform_verified"
    assert stored["signature_status"] == "verified"


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_signature_and_stores_nothing(
    tampered_postback: dict,
):
    with pytest.raises(HTTPException) as exc:
        await ingest_apple_postback(
            ApplePostbackRequest(postback=tampered_postback), TENANT
        )
    assert exc.value.status_code == 422
    assert module._LOCAL_APPLE_POSTBACKS == {}


@pytest.mark.asyncio
async def test_ingest_stores_unknown_version_as_low_trust(
    unknown_version_postback: dict,
):
    result = await ingest_apple_postback(
        ApplePostbackRequest(postback=unknown_version_postback), TENANT
    )
    assert result["postback"]["signature_status"] == "unverified"
    assert result["postback"]["proof_level"] == "platform_verified"
    assert len(module._LOCAL_APPLE_POSTBACKS) == 1


@pytest.mark.asyncio
async def test_idempotency_is_tenant_scoped(signed_postback: dict):
    tenant_b = TenantContext(tenant_id="tenant-b", role=Role.SERVICE)
    a = await ingest_apple_postback(
        ApplePostbackRequest(postback=signed_postback), TENANT
    )
    b = await ingest_apple_postback(
        ApplePostbackRequest(postback=dict(signed_postback)), tenant_b
    )
    assert a["postback"]["duplicate"] is False
    assert b["postback"]["duplicate"] is False


@pytest.mark.asyncio
async def test_ingest_rejects_malformed_with_422(malformed_postback: dict):
    with pytest.raises(HTTPException) as exc:
        await ingest_apple_postback(
            ApplePostbackRequest(postback=malformed_postback), TENANT
        )
    assert exc.value.status_code == 422
    assert module._LOCAL_APPLE_POSTBACKS == {}


@pytest.mark.asyncio
async def test_rbac_requires_write_capable_credential():
    viewer = TenantContext(tenant_id="tenant-a", role=Role.VIEWER, permissions=[])
    with pytest.raises(HTTPException) as exc:
        await module._require_apple_postback_write(viewer)
    assert exc.value.status_code == 403

    permitted = TenantContext(
        tenant_id="tenant-a", role=Role.VIEWER, permissions=["apple_postbacks:write"]
    )
    assert await module._require_apple_postback_write(permitted) is permitted


def test_main_registers_apple_postbacks_router() -> None:
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[2]
    main_source = (backend_root / "main.py").read_text(encoding="utf-8")
    assert (
        "from services.attribution.apple_postbacks import router as apple_postbacks_router"
        in main_source
    )
    assert "app.include_router(apple_postbacks_router)" in main_source


def test_router_exposes_the_contract_path() -> None:
    route_methods = {
        (route.path, method)
        for route in module.router.routes
        for method in (route.methods or set())
    }
    assert ("/v1/attribution/apple-postbacks", "POST") in route_methods
