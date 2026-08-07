"""Kyber mobile-bound device proof key routes — /v1/kyber/mobile/proof-keys.

Covers M6c of the Kyber milestone program: a MOBILE device registers an ECDSA
P-256 proof key through the SAME ``DeviceProofKey`` mechanism the browser-proof
path uses. The suite proves:

* Registration persists a ``DeviceProofKey`` row the proof repo reads.
* Registration is an idempotent UPSERT — re-registering ``(device_id,
  operator_id)`` never creates a second row, and a different key REPLACES the
  stored one in place **only after a fresh step-up grant** (a re-key of a live
  attestation key; first enrollment needs no step-up).
* Ownership is enforced with the continuation router's 404 idiom — a foreign or
  absent ``device_id`` / ``proof_key_id`` is indistinguishable from gone, and a
  list never shows another operator's keys.
* Full round-trip: after registration, the unchanged
  ``DeviceProofService.issue_challenge -> verify_proof`` path verifies a real
  ECDSA P-256 signature against the mobile-registered key.
* snake_case wire fields (D6), a redacted list projection, revocation via
  ``revoked_at``, and the unauthenticated HTTP surface denies at the edge.
"""
from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from repositories.repos import reset_in_memory_stores
from shared.common.common import AetherError, BadRequestError, ForbiddenError, NotFoundError
from services.kyber.access.contracts import TrustedDevice, WorkforcePrincipal, WorkforceSession
from services.kyber.access.dependencies import KyberAccessContext
from services.kyber.devices.device_proof import device_proof_service
from services.kyber.devices.mobile_proof_routes import (
    MobileProofKeyRegister,
    list_mobile_proof_keys,
    mobile_proof_router,
    register_mobile_proof_key,
    revoke_mobile_proof_key,
)
from services.kyber.devices.repository import DeviceProofKeyRepository, TrustedDeviceRepository
from services.kyber.sessions.step_up import step_up_service


def _run(coro):
    return asyncio.run(coro)


def _ctx(operator_id: str = "op-1") -> KyberAccessContext:
    """The real ``KyberAccessContext`` a workforce session would authorize.

    Mirrors ``tests/kyber/conftest.py.build_scoped_context`` and
    ``test_kyber_continuations._ctx``: a live, device-bound session plus an
    active principal — the shape ``require_kyber_access`` hands a handler after
    a successful evaluation.
    """
    session = WorkforceSession(
        token_hash=f"hash_{operator_id}",
        operator_id=operator_id,
        device_id="dev_test",
        status="active",
        authentication_strength="device_bound",
        environment="local",
    )
    principal = WorkforcePrincipal(
        operator_id=operator_id,
        email="operator@olympus.test",
        employment_status="active",
        kyber_enabled=True,
    )
    return KyberAccessContext(
        session=session,
        principal=principal,
        environment=session.environment,
    )


def _p256_keypair() -> tuple[str, ec.EllipticCurvePrivateKey]:
    """A fresh ECDSA P-256 keypair; returns the base64url SPKI public half."""
    private = ec.generate_private_key(ec.SECP256R1())
    der = private.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_b64 = base64.urlsafe_b64encode(der).decode("ascii").rstrip("=")
    return public_b64, private


PUB_KEY_A, _PRIVATE_A = _p256_keypair()
PUB_KEY_B, _PRIVATE_B = _p256_keypair()


async def _seed_device(operator_id: str = "op-1", device_id: str = "dev_1") -> TrustedDevice:
    """A trusted device owned by ``operator_id`` in the device store."""
    device = TrustedDevice(
        operator_id=operator_id,
        device_id=device_id,
        display_name="Test mobile device",
        platform_family="mobile",
        approval_state="approved",
        risk_state="ok",
    )
    await TrustedDeviceRepository().save(device)
    return device


def _register(device_id: str, public_key: str, *, operator_id: str = "op-1") -> dict:
    resp = _run(
        register_mobile_proof_key(
            body=MobileProofKeyRegister(device_id=device_id, public_key=public_key),
            context=_ctx(operator_id),
        )
    )
    return resp.data


@pytest.fixture(autouse=True)
def _isolated_stores():
    """Empty every in-memory backing store before and after each test.

    Module-level singletons (``device_proof_service``, the route module's
    ``_keys``) hold references to the shared per-table dicts, which
    ``reset_in_memory_stores`` clears in place — so the singletons keep
    pointing at the same, now-empty, stores.
    """
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ── Registration surface ─────────────────────────────────────────────────────

def test_mobile_proof_router_registers_expected_routes():
    paths = {(r.path, tuple(sorted(r.methods))) for r in mobile_proof_router.routes}
    assert ("/v1/kyber/mobile/proof-keys", ("POST",)) in paths
    assert ("/v1/kyber/mobile/proof-keys", ("GET",)) in paths
    assert ("/v1/kyber/mobile/proof-keys/{proof_key_id}", ("DELETE",)) in paths


def _client() -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _handle(_request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    app.include_router(mobile_proof_router)
    return TestClient(app, raise_server_exceptions=False)


def test_unauthenticated_http_denied() -> None:
    """No Kyber workforce session -> the kyber guard denies at the edge."""
    client = _client()
    for method, path, json_body in [
        ("get", "/v1/kyber/mobile/proof-keys", None),
        ("post", "/v1/kyber/mobile/proof-keys", {"device_id": "dev_1", "public_key": PUB_KEY_A}),
        ("delete", "/v1/kyber/mobile/proof-keys/dpk_missing", None),
    ]:
        kwargs = {"json": json_body} if json_body is not None else {}
        resp = getattr(client, method)(path, **kwargs)
        assert resp.status_code in (401, 403), f"{method} {path} -> {resp.status_code}"


# ── Register ─────────────────────────────────────────────────────────────────

def test_register_creates_proof_key_row_via_the_proof_repo():
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))

    data = _register("dev_1", PUB_KEY_A)

    assert data["device_id"] == "dev_1"
    assert data["operator_id"] == "op-1"
    assert data["algorithm"] == "ES256"
    assert data["proof_key_id"].startswith("dpk_")
    assert data["public_key"] == PUB_KEY_A

    # The row lands in the exact repo DeviceProofService verifies from.
    row = _run(DeviceProofKeyRepository().find_active_by_device("dev_1"))
    assert row is not None
    assert row.proof_key_id == data["proof_key_id"]
    assert row.operator_id == "op-1"
    assert row.algorithm == "ES256"
    assert row.public_key == PUB_KEY_A


def test_register_is_idempotent_upsert(monkeypatch):
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))

    first = _register("dev_1", PUB_KEY_A)

    # Re-registration rides the replace path, which demands a fresh step-up.
    monkeypatch.setattr(
        step_up_service, "require_fresh", AsyncMock(return_value=(True, None))
    )
    second = _register("dev_1", PUB_KEY_A)

    assert second["proof_key_id"] == first["proof_key_id"]
    rows = _run(DeviceProofKeyRepository().find_by_device("dev_1"))
    assert len(rows) == 1


def test_register_with_different_key_replaces_in_place(monkeypatch):
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))

    first = _register("dev_1", PUB_KEY_A)

    # Re-keying a live key rides the replace path, which demands a fresh
    # step-up; with the grant, the stored key is REPLACED in place.
    monkeypatch.setattr(
        step_up_service, "require_fresh", AsyncMock(return_value=(True, None))
    )
    second = _register("dev_1", PUB_KEY_B)

    # One live row per device; a re-enrollment REPLACES the stored key.
    assert second["proof_key_id"] == first["proof_key_id"]
    assert second["public_key"] == PUB_KEY_B
    rows = _run(DeviceProofKeyRepository().find_by_device("dev_1"))
    assert len(rows) == 1
    assert rows[0].public_key == PUB_KEY_B


def test_register_replacement_denied_without_fresh_step_up():
    """A live key cannot be re-bound without a fresh step-up grant (D2).

    The vulnerability this closes: under only a SELF_CAPABILITY session, an
    attacker holding a captured cookie could re-key the device to a key they
    control and then pass ``/step-up/verify``. Because the grant itself is only
    obtainable against the *current* live key, the re-key must fail here and
    leave the existing key intact.
    """
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))
    first = _register("dev_1", PUB_KEY_A)

    # No step-up grant for this session -> the re-key is refused outright.
    with pytest.raises(ForbiddenError) as excinfo:
        _register("dev_1", PUB_KEY_B)
    assert excinfo.value.details.get("denial_reason") == "step_up_required"

    # The live attestation key is untouched — the device still proves with A.
    row = _run(DeviceProofKeyRepository().find_active_by_device("dev_1"))
    assert row is not None
    assert row.public_key == PUB_KEY_A
    assert row.proof_key_id == first["proof_key_id"]
    rows = _run(DeviceProofKeyRepository().find_by_device("dev_1"))
    assert len(rows) == 1


def test_first_time_enrollment_still_allowed_without_step_up():
    """First enrollment (no existing live key) needs no step-up grant."""
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))

    data = _register("dev_1", PUB_KEY_A)

    assert data["public_key"] == PUB_KEY_A
    row = _run(DeviceProofKeyRepository().find_active_by_device("dev_1"))
    assert row is not None and row.public_key == PUB_KEY_A


def test_register_foreign_device_is_404():
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))

    # op-2 tries to bind a key to op-1's device -> indistinguishable from absent.
    with pytest.raises(NotFoundError):
        _run(
            register_mobile_proof_key(
                body=MobileProofKeyRegister(device_id="dev_1", public_key=PUB_KEY_A),
                context=_ctx("op-2"),
            )
        )
    # Absent device id is the same 404.
    with pytest.raises(NotFoundError):
        _register("dev_does_not_exist", PUB_KEY_A)

    rows = _run(DeviceProofKeyRepository().find_by_device("dev_1"))
    assert rows == []


def test_register_rejects_non_es256_and_bad_public_keys():
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))

    with pytest.raises(BadRequestError):
        _run(
            register_mobile_proof_key(
                body=MobileProofKeyRegister(
                    device_id="dev_1", public_key=PUB_KEY_A, algorithm="ES512"
                ),
                context=_ctx("op-1"),
            )
        )
    with pytest.raises(BadRequestError):
        _register("dev_1", "not-a-real-spki-key")

    rows = _run(DeviceProofKeyRepository().find_by_device("dev_1"))
    assert rows == []


# ── List ─────────────────────────────────────────────────────────────────────

def test_list_is_scoped_to_the_caller_and_redacted():
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))
    _run(_seed_device(operator_id="op-2", device_id="dev_2"))

    _register("dev_1", PUB_KEY_A, operator_id="op-1")

    mine = _run(list_mobile_proof_keys(context=_ctx("op-1"))).data
    assert mine["operator_id"] == "op-1"
    assert len(mine["proof_keys"]) == 1
    item = mine["proof_keys"][0]
    assert item["proof_key_id"].startswith("dpk_")
    assert item["device_id"] == "dev_1"
    assert item["algorithm"] == "ES256"
    # snake_case wire keys (D6) and no public-key material in the list.
    assert set(item) == {
        "proof_key_id",
        "device_id",
        "operator_id",
        "algorithm",
        "created_at",
        "last_verified_at",
    }
    assert "public_key" not in item

    theirs = _run(list_mobile_proof_keys(context=_ctx("op-2"))).data
    assert theirs["proof_keys"] == []


# ── Round-trip through DeviceProofService ────────────────────────────────────

def test_round_trip_issue_and_verify_against_registered_key():
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))
    public_b64, private_key = _p256_keypair()
    data = _register("dev_1", public_b64)

    # The key is retrievable by the proof repo for (device_id, operator_id).
    row = _run(DeviceProofKeyRepository().find_active_by_device("dev_1"))
    assert row is not None and row.public_key == public_b64
    assert row.operator_id == "op-1"

    # Full ceremony through the unchanged browser-proof service.
    challenge_id, challenge_b64 = _run(device_proof_service.issue_challenge(device_id="dev_1"))
    challenge_bytes = base64.urlsafe_b64decode(
        challenge_b64 + "=" * (-len(challenge_b64) % 4)
    )
    signature = private_key.sign(challenge_bytes, ec.ECDSA(hashes.SHA256()))
    signature_b64 = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")

    verified = _run(
        device_proof_service.verify_proof(
            device_id="dev_1",
            challenge_id=challenge_id,
            signature_b64=signature_b64,
        )
    )
    assert verified is True

    # The proof path stamped last_verified_at on the registered row.
    refreshed = _run(DeviceProofKeyRepository().find_active_by_device("dev_1"))
    assert refreshed is not None
    assert refreshed.last_verified_at is not None
    assert refreshed.proof_key_id == data["proof_key_id"]


# ── Revoke ───────────────────────────────────────────────────────────────────

def test_revoke_sets_revoked_at_and_removes_from_the_active_list():
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))
    data = _register("dev_1", PUB_KEY_A)

    out = _run(revoke_mobile_proof_key(proof_key_id=data["proof_key_id"], context=_ctx("op-1"))).data
    assert out["revoked_at"] is not None
    assert out["proof_key_id"] == data["proof_key_id"]

    row = _run(DeviceProofKeyRepository().get(data["proof_key_id"]))
    assert row is not None and row.revoked_at is not None

    listed = _run(list_mobile_proof_keys(context=_ctx("op-1"))).data
    assert listed["proof_keys"] == []

    # Revoking again is idempotent — no error, still revoked.
    again = _run(revoke_mobile_proof_key(proof_key_id=data["proof_key_id"], context=_ctx("op-1"))).data
    assert again["revoked_at"] == out["revoked_at"]


def test_revoke_foreign_key_is_404():
    _run(_seed_device(operator_id="op-1", device_id="dev_1"))
    data = _register("dev_1", PUB_KEY_A, operator_id="op-1")

    with pytest.raises(NotFoundError):
        _run(revoke_mobile_proof_key(proof_key_id=data["proof_key_id"], context=_ctx("op-2")))
    with pytest.raises(NotFoundError):
        _run(revoke_mobile_proof_key(proof_key_id="dpk_nope", context=_ctx("op-1")))

    row = _run(DeviceProofKeyRepository().get(data["proof_key_id"]))
    assert row is not None and row.revoked_at is None
