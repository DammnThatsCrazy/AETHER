"""Kyber BYOD device trust.

These tests exercise the real code paths, with real cryptography. Device-proof
keys are genuine ECDSA P-256 keypairs and the signatures are produced by
``cryptography``; the WebAuthn structures are synthetic but valid, verified by
py_webauthn itself rather than by a stub.

The case the whole design exists for has its own test:
:func:`test_synced_passkey_alone_on_a_second_machine_is_denied`. A platform
passkey syncs between an operator's personal machines. The assertion made on the
second machine verifies perfectly — and the device is still refused, because
that machine holds neither the browser-profile-bound proof key nor an approved
device grant.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from webauthn.helpers import encode_cbor

from repositories.repos import reset_in_memory_stores
from services.kyber.access.roles import DEVICE_APPROVER_TEMPLATE_IDS
from services.kyber.devices.approvals import (
    DeviceApprovalService,
    device_approval_service,
    grant_hash,
)
from services.kyber.devices.device_proof import device_proof_service
from services.kyber.devices.repository import (
    DeviceProofKeyRepository,
    TrustedDeviceRepository,
    WebAuthnCredentialRepository,
)
from services.kyber.devices.risk import browser_family, device_risk_service
from services.kyber.devices.webauthn import relying_party, webauthn_service
from services.security.repositories import SecurityAuditEventRepository
from shared.common.common import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
)

APPROVER_ROLE = sorted(DEVICE_APPROVER_TEMPLATE_IDS)[0]
NON_APPROVER_ROLES = ["observer", "product_manager"]

OPERATOR = "op_alice"
APPROVER = "op_founder"

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
FIREFOX_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0"


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ── encoding helpers ──────────────────────────────────────────────────────────

def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def unb64u(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def spki_b64(key: ec.EllipticCurvePrivateKey) -> str:
    return b64u(
        key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


# ── synthetic-but-valid WebAuthn structures ───────────────────────────────────

FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40


def _cose_es256(key: ec.EllipticCurvePrivateKey) -> bytes:
    numbers = key.public_key().public_numbers()
    return encode_cbor(
        {
            1: 2,  # kty: EC2
            3: -7,  # alg: ES256
            -1: 1,  # crv: P-256
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        }
    )


def _authenticator_data(
    rp_id: str, *, flags: int, sign_count: int, attested: bytes = b""
) -> bytes:
    return (
        hashlib.sha256(rp_id.encode("utf-8")).digest()
        + bytes([flags])
        + sign_count.to_bytes(4, "big")
        + attested
    )


def _client_data(kind: str, challenge_b64: str, origin: str) -> bytes:
    return json.dumps(
        {
            "type": kind,
            "challenge": challenge_b64,
            "origin": origin,
            "crossOrigin": False,
        }
    ).encode("utf-8")


def make_registration_credential(
    *,
    challenge_b64: str,
    key: ec.EllipticCurvePrivateKey,
    credential_id: bytes,
    sign_count: int = 0,
    aaguid: bytes = b"\x00" * 16,
):
    """A ``navigator.credentials.create()`` response py_webauthn will accept."""
    rp = relying_party()
    cose = _cose_es256(key)
    attested = aaguid + len(credential_id).to_bytes(2, "big") + credential_id + cose
    auth_data = _authenticator_data(
        rp.rp_id, flags=FLAG_UP | FLAG_UV | FLAG_AT, sign_count=sign_count, attested=attested
    )
    attestation = encode_cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
    return {
        "id": b64u(credential_id),
        "rawId": b64u(credential_id),
        "type": "public-key",
        "authenticatorAttachment": "platform",
        "response": {
            "clientDataJSON": b64u(_client_data("webauthn.create", challenge_b64, rp.origins[0])),
            "attestationObject": b64u(attestation),
            "transports": ["internal", "hybrid"],
        },
    }


def make_assertion_credential(
    *,
    challenge_b64: str,
    key: ec.EllipticCurvePrivateKey,
    credential_id: bytes,
    sign_count: int,
):
    """A ``navigator.credentials.get()`` response py_webauthn will accept."""
    rp = relying_party()
    auth_data = _authenticator_data(rp.rp_id, flags=FLAG_UP | FLAG_UV, sign_count=sign_count)
    client_data = _client_data("webauthn.get", challenge_b64, rp.origins[0])
    signature = key.sign(
        auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
    )
    return {
        "id": b64u(credential_id),
        "rawId": b64u(credential_id),
        "type": "public-key",
        "authenticatorAttachment": "platform",
        "response": {
            "clientDataJSON": b64u(client_data),
            "authenticatorData": b64u(auth_data),
            "signature": b64u(signature),
            "userHandle": None,
        },
    }


async def enroll_credential(
    *,
    operator_id: str = OPERATOR,
    display_name: str = "Alice MacBook / Chrome",
    browser: str = "chrome",
    sign_count: int = 0,
    key: ec.EllipticCurvePrivateKey | None = None,
    credential_id: bytes | None = None,
):
    """Run a full registration ceremony and return ``(device, credential, key)``."""
    key = key or ec.generate_private_key(ec.SECP256R1())
    credential_id = credential_id or os.urandom(20)

    options = await webauthn_service.registration_options(
        operator_id=operator_id,
        display_name=display_name,
        existing_credential_ids=[],
    )
    response = make_registration_credential(
        challenge_b64=options["options"]["challenge"],
        key=key,
        credential_id=credential_id,
        sign_count=sign_count,
    )
    credential = await webauthn_service.verify_registration(
        operator_id=operator_id,
        credential=response,
        expected_challenge_id=options["challenge_id"],
        display_name=display_name,
        platform_family="macos",
        browser_family=browser,
    )
    device = await device_approval_service.get_device(credential.device_id)
    return device, credential, key


async def audit_events(event_type: str) -> list[dict]:
    repo = SecurityAuditEventRepository()
    return await repo.find_many({"event_type": event_type}, limit=100)


# ══════════════════════════════════════════════════════════════════════════════
# Registration and approval
# ══════════════════════════════════════════════════════════════════════════════

async def test_registration_creates_a_pending_device_that_is_not_usable():
    device, credential, _ = await enroll_credential()

    assert device is not None
    assert device.approval_state == "pending"
    assert device.grant_hash is None
    assert credential.operator_id == OPERATOR
    assert credential.sign_count == 0

    usable, reason = await device_approval_service.is_usable(device.device_id)
    assert usable is False
    assert reason == "device_unapproved"


async def test_unapproved_device_is_denied():
    device = await device_approval_service.register_device(
        operator_id=OPERATOR, display_name="Unapproved laptop", platform_family="macos",
        browser_family="chrome",
    )
    usable, reason = await device_approval_service.is_usable(device.device_id)
    assert (usable, reason) == (False, "device_unapproved")


async def test_unknown_device_is_denied_exactly_like_an_unapproved_one():
    usable, reason = await device_approval_service.is_usable("dev_does_not_exist")
    assert (usable, reason) == (False, "device_unapproved")


async def test_approval_makes_a_device_usable_and_returns_the_grant_once():
    device, _, _ = await enroll_credential()
    approved, token = await device_approval_service.approve_device(
        device.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )

    assert approved.approval_state == "approved"
    assert approved.approved_by == APPROVER
    assert token
    usable, reason = await device_approval_service.is_usable(device.device_id)
    assert (usable, reason) == (True, None)

    resolved = await device_approval_service.resolve_by_grant(token)
    assert resolved is not None and resolved.device_id == device.device_id


async def test_grant_token_is_stored_only_as_a_hash():
    device, _, _ = await enroll_credential()
    _, token = await device_approval_service.approve_device(
        device.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )

    repo = TrustedDeviceRepository()
    row = await repo.find_by_id(device.device_id)
    assert row is not None
    assert row["grant_hash"] == grant_hash(token)
    # The raw token must appear nowhere in the persisted record.
    assert token not in json.dumps(row)


async def test_self_approval_is_refused_and_audited():
    device, _, _ = await enroll_credential()

    with pytest.raises(ForbiddenError):
        await device_approval_service.approve_device(
            device.device_id,
            actor_id=OPERATOR,  # the device owner
            actor_role_template_ids=[APPROVER_ROLE],
            registration_days=30,
        )

    still = await device_approval_service.get_device(device.device_id)
    assert still.approval_state == "pending"
    assert still.grant_hash is None

    blocked = await audit_events("kyber.device.self_approval_blocked")
    assert len(blocked) == 1
    assert blocked[0]["outcome"] == "blocked"
    assert blocked[0]["actor_id"] == OPERATOR
    assert blocked[0]["resource_id"] == device.device_id


async def test_self_approval_bootstrap_is_allowed_but_audited_as_bootstrap():
    device, _, _ = await enroll_credential()
    approved, token = await device_approval_service.approve_device(
        device.device_id,
        actor_id=OPERATOR,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
        allow_self_approval=True,
        self_approval_reason="first founder device",
    )

    assert approved.approval_state == "approved"
    assert token
    bootstrap = await audit_events("kyber.device.self_approval_bootstrap")
    assert len(bootstrap) == 1
    assert bootstrap[0]["metadata"]["self_approved"] is True
    assert not await audit_events("kyber.device.approved")


async def test_a_non_approver_role_cannot_approve():
    device, _, _ = await enroll_credential()

    with pytest.raises(ForbiddenError):
        await device_approval_service.approve_device(
            device.device_id,
            actor_id=APPROVER,
            actor_role_template_ids=NON_APPROVER_ROLES,
            registration_days=30,
        )

    still = await device_approval_service.get_device(device.device_id)
    assert still.approval_state == "pending"
    blocked = await audit_events("kyber.device.approve_blocked")
    assert blocked and blocked[0]["metadata"]["reason"] == "approver_role_missing"


async def test_a_second_browser_is_a_separate_device_pending_its_own_approval():
    first, _, _ = await enroll_credential(display_name="Alice MacBook / Chrome", browser="chrome")
    await device_approval_service.approve_device(
        first.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )

    second, _, _ = await enroll_credential(
        display_name="Alice MacBook / Firefox", browser="firefox"
    )

    assert second.device_id != first.device_id
    assert second.approval_state == "pending"
    assert (await device_approval_service.is_usable(first.device_id)) == (True, None)
    assert (await device_approval_service.is_usable(second.device_id)) == (
        False,
        "device_unapproved",
    )

    # It becomes usable only after its own, separate approval.
    await device_approval_service.approve_device(
        second.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )
    assert (await device_approval_service.is_usable(second.device_id)) == (True, None)


async def test_registering_the_same_browser_twice_is_idempotent():
    first = await device_approval_service.register_device(
        operator_id=OPERATOR, display_name="Alice MacBook", platform_family="macos",
        browser_family="chrome",
    )
    again = await device_approval_service.register_device(
        operator_id=OPERATOR, display_name="Alice MacBook", platform_family="macos",
        browser_family="chrome",
    )
    assert again.device_id == first.device_id
    assert len(await device_approval_service.list_devices(OPERATOR)) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Withdrawal
# ══════════════════════════════════════════════════════════════════════════════

async def test_revoked_device_is_denied():
    device, _, _ = await enroll_credential()
    _, token = await device_approval_service.approve_device(
        device.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )
    assert (await device_approval_service.is_usable(device.device_id)) == (True, None)

    await device_approval_service.revoke_device(
        device.device_id, actor_id=APPROVER, reason="laptop lost"
    )

    usable, reason = await device_approval_service.is_usable(device.device_id)
    assert (usable, reason) == (False, "device_revoked")
    # The cookie still resolves — to a precise denial, not to an unknown device.
    resolved = await device_approval_service.resolve_by_grant(token)
    assert resolved is not None and resolved.approval_state == "revoked"


async def test_revoking_a_device_is_idempotent():
    device, _, _ = await enroll_credential()
    await device_approval_service.approve_device(
        device.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )

    first = await device_approval_service.revoke_device(
        device.device_id, actor_id=APPROVER, reason="offboarding"
    )
    second = await device_approval_service.revoke_device(
        device.device_id, actor_id=APPROVER, reason="offboarding"
    )

    assert first.approval_state == second.approval_state == "revoked"
    assert first.revoked_at == second.revoked_at
    assert first.revocation_reason == "offboarding"

    events = await device_approval_service.history(device.device_id)
    assert [e.action for e in events].count("revoked") == 1
    # The session plane is owned elsewhere; the attempt is always reported.
    report = second.metadata["session_revocation"]
    assert report["attempted"] is True
    assert "succeeded" in report


async def test_a_revoked_device_cannot_be_approved_again():
    device, _, _ = await enroll_credential()
    await device_approval_service.revoke_device(
        device.device_id, actor_id=APPROVER, reason="compromised"
    )
    with pytest.raises(ConflictError):
        await device_approval_service.approve_device(
            device.device_id,
            actor_id=APPROVER,
            actor_role_template_ids=[APPROVER_ROLE],
            registration_days=30,
        )


async def test_suspended_device_is_denied_and_suspension_is_idempotent():
    device, _, _ = await enroll_credential()
    await device_approval_service.approve_device(
        device.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )

    await device_approval_service.suspend_device(
        device.device_id, actor_id=APPROVER, reason="investigating"
    )
    await device_approval_service.suspend_device(
        device.device_id, actor_id=APPROVER, reason="investigating"
    )

    usable, reason = await device_approval_service.is_usable(device.device_id)
    assert (usable, reason) == (False, "device_revoked")
    events = await device_approval_service.history(device.device_id)
    assert [e.action for e in events].count("suspended") == 1


async def test_expired_grant_is_denied():
    device, _, _ = await enroll_credential()
    await device_approval_service.approve_device(
        device.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=1,
    )

    repo = TrustedDeviceRepository()
    row = await repo.find_by_id(device.device_id)
    row["expires_at"] = "2020-01-01T00:00:00+00:00"
    await repo.update(device.device_id, row)

    usable, reason = await device_approval_service.is_usable(device.device_id)
    assert (usable, reason) == (False, "device_unapproved")
    # Expiry is settled lazily at use, so the record reflects it immediately.
    assert (await device_approval_service.get_device(device.device_id)).approval_state == "expired"


async def test_a_blocked_risk_state_denies_an_otherwise_approved_device():
    device, _, _ = await enroll_credential()
    await device_approval_service.approve_device(
        device.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )
    await device_risk_service.mark_blocked(device.device_id, "manual containment")

    usable, reason = await device_approval_service.is_usable(device.device_id)
    assert (usable, reason) == (False, "device_revoked")
    refreshed = await device_approval_service.get_device(device.device_id)
    assert refreshed.approval_state == "approved"
    assert refreshed.risk_state == "blocked"


async def test_renaming_changes_nothing_about_authority():
    device, _, _ = await enroll_credential()
    await device_approval_service.approve_device(
        device.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )
    renamed = await device_approval_service.rename_device(
        device.device_id, actor_id=OPERATOR, display_name="Work laptop"
    )
    assert renamed.display_name == "Work laptop"
    assert renamed.approval_state == "approved"
    assert (await device_approval_service.is_usable(device.device_id)) == (True, None)


async def test_registration_days_outside_the_platform_bounds_are_refused():
    device, _, _ = await enroll_credential()
    for days in (0, -1, 3650):
        with pytest.raises(BadRequestError):
            await device_approval_service.approve_device(
                device.device_id,
                actor_id=APPROVER,
                actor_role_template_ids=[APPROVER_ROLE],
                registration_days=days,
            )


# ══════════════════════════════════════════════════════════════════════════════
# Device proof — the browser-profile-bound factor
# ══════════════════════════════════════════════════════════════════════════════

async def _approved_device_with_proof_key():
    device, _, _ = await enroll_credential()
    await device_approval_service.approve_device(
        device.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )
    proof_key = ec.generate_private_key(ec.SECP256R1())
    await device_proof_service.register_proof_key(
        device_id=device.device_id,
        operator_id=OPERATOR,
        public_key_b64=spki_b64(proof_key),
    )
    return device, proof_key


async def test_device_proof_round_trip_succeeds():
    device, proof_key = await _approved_device_with_proof_key()

    challenge_id, challenge_b64 = await device_proof_service.issue_challenge(
        device_id=device.device_id
    )
    signature = proof_key.sign(unb64u(challenge_b64), ec.ECDSA(hashes.SHA256()))

    assert await device_proof_service.verify_proof(
        device_id=device.device_id,
        challenge_id=challenge_id,
        signature_b64=b64u(signature),
    )


async def test_device_proof_accepts_a_webcrypto_raw_signature():
    """``crypto.subtle.sign`` emits fixed-width r||s, not DER."""
    device, proof_key = await _approved_device_with_proof_key()
    challenge_id, challenge_b64 = await device_proof_service.issue_challenge(
        device_id=device.device_id
    )
    der = proof_key.sign(unb64u(challenge_b64), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")

    assert await device_proof_service.verify_proof(
        device_id=device.device_id, challenge_id=challenge_id, signature_b64=b64u(raw)
    )


async def test_device_proof_signature_failure_is_denied():
    device, proof_key = await _approved_device_with_proof_key()
    challenge_id, _ = await device_proof_service.issue_challenge(device_id=device.device_id)

    # Signed over the wrong bytes: a valid signature, of something else.
    signature = proof_key.sign(b"not the issued challenge", ec.ECDSA(hashes.SHA256()))

    assert not await device_proof_service.verify_proof(
        device_id=device.device_id,
        challenge_id=challenge_id,
        signature_b64=b64u(signature),
    )
    failures = await audit_events("kyber.device.proof_failed")
    assert failures and failures[0]["outcome"] == "blocked"


async def test_device_proof_from_another_browser_profile_key_is_denied():
    """The private half never leaves its profile; a different key cannot stand in."""
    device, _ = await _approved_device_with_proof_key()
    other_profile_key = ec.generate_private_key(ec.SECP256R1())

    challenge_id, challenge_b64 = await device_proof_service.issue_challenge(
        device_id=device.device_id
    )
    signature = other_profile_key.sign(unb64u(challenge_b64), ec.ECDSA(hashes.SHA256()))

    assert not await device_proof_service.verify_proof(
        device_id=device.device_id,
        challenge_id=challenge_id,
        signature_b64=b64u(signature),
    )


async def test_device_proof_replay_is_denied():
    device, proof_key = await _approved_device_with_proof_key()
    challenge_id, challenge_b64 = await device_proof_service.issue_challenge(
        device_id=device.device_id
    )
    signature_b64 = b64u(proof_key.sign(unb64u(challenge_b64), ec.ECDSA(hashes.SHA256())))

    assert await device_proof_service.verify_proof(
        device_id=device.device_id, challenge_id=challenge_id, signature_b64=signature_b64
    )
    # Exact same challenge id and exact same signature, replayed.
    assert not await device_proof_service.verify_proof(
        device_id=device.device_id, challenge_id=challenge_id, signature_b64=signature_b64
    )


async def test_device_proof_against_an_unknown_device_is_denied():
    assert not await device_proof_service.verify_proof(
        device_id="dev_nope", challenge_id="dpc_nope", signature_b64=b64u(b"x" * 64)
    )


async def test_device_proof_after_key_revocation_is_denied():
    device, proof_key = await _approved_device_with_proof_key()
    challenge_id, challenge_b64 = await device_proof_service.issue_challenge(
        device_id=device.device_id
    )
    await device_proof_service.revoke_proof_key(
        device.device_id, actor_id=APPROVER, reason="re-enrollment"
    )
    signature = proof_key.sign(unb64u(challenge_b64), ec.ECDSA(hashes.SHA256()))

    assert not await device_proof_service.verify_proof(
        device_id=device.device_id,
        challenge_id=challenge_id,
        signature_b64=b64u(signature),
    )


async def test_proof_key_must_be_p256():
    device = await device_approval_service.register_device(
        operator_id=OPERATOR, display_name="Laptop", platform_family="macos",
        browser_family="chrome",
    )
    p384 = ec.generate_private_key(ec.SECP384R1())
    with pytest.raises(BadRequestError):
        await device_proof_service.register_proof_key(
            device_id=device.device_id,
            operator_id=OPERATOR,
            public_key_b64=spki_b64(p384),
        )

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_spki = b64u(
        rsa_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    with pytest.raises(BadRequestError):
        await device_proof_service.register_proof_key(
            device_id=device.device_id, operator_id=OPERATOR, public_key_b64=rsa_spki
        )

    with pytest.raises(BadRequestError):
        await device_proof_service.register_proof_key(
            device_id=device.device_id, operator_id=OPERATOR, public_key_b64="not-a-key"
        )

    assert await DeviceProofKeyRepository().find_active_by_device(device.device_id) is None


async def test_repeated_proof_failures_escalate_the_device_to_suspect():
    device, proof_key = await _approved_device_with_proof_key()

    for _ in range(5):
        challenge_id, _ = await device_proof_service.issue_challenge(
            device_id=device.device_id
        )
        await device_proof_service.verify_proof(
            device_id=device.device_id,
            challenge_id=challenge_id,
            signature_b64=b64u(proof_key.sign(b"wrong", ec.ECDSA(hashes.SHA256()))),
        )

    refreshed = await device_approval_service.get_device(device.device_id)
    assert refreshed.risk_state == "suspect"


# ══════════════════════════════════════════════════════════════════════════════
# WebAuthn ceremonies
# ══════════════════════════════════════════════════════════════════════════════

async def test_webauthn_challenge_replay_is_denied():
    key = ec.generate_private_key(ec.SECP256R1())
    credential_id = os.urandom(20)
    options = await webauthn_service.registration_options(
        operator_id=OPERATOR, display_name="Alice MacBook", existing_credential_ids=[]
    )
    response = make_registration_credential(
        challenge_b64=options["options"]["challenge"],
        key=key,
        credential_id=credential_id,
    )

    await webauthn_service.verify_registration(
        operator_id=OPERATOR,
        credential=response,
        expected_challenge_id=options["challenge_id"],
        display_name="Alice MacBook",
        browser_family="chrome",
    )

    with pytest.raises(UnauthorizedError):
        await webauthn_service.verify_registration(
            operator_id=OPERATOR,
            credential=response,
            expected_challenge_id=options["challenge_id"],
            display_name="Alice MacBook",
            browser_family="chrome",
        )

    invalid = await audit_events("kyber.device.webauthn_challenge_invalid")
    assert invalid and invalid[0]["outcome"] == "blocked"


async def test_webauthn_authentication_challenge_replay_is_denied():
    device, credential, key = await enroll_credential()
    credential_id = unb64u(credential.credential_id)

    options = await webauthn_service.authentication_options(operator_id=OPERATOR)
    assertion = make_assertion_credential(
        challenge_b64=options["options"]["challenge"],
        key=key,
        credential_id=credential_id,
        sign_count=1,
    )
    verified = await webauthn_service.verify_authentication(
        operator_id=OPERATOR,
        credential=assertion,
        expected_challenge_id=options["challenge_id"],
    )
    assert verified.sign_count == 1

    with pytest.raises(UnauthorizedError):
        await webauthn_service.verify_authentication(
            operator_id=OPERATOR,
            credential=assertion,
            expected_challenge_id=options["challenge_id"],
        )


async def test_wrong_webauthn_credential_is_denied():
    await enroll_credential()

    stranger_key = ec.generate_private_key(ec.SECP256R1())
    stranger_credential_id = os.urandom(20)
    options = await webauthn_service.authentication_options(operator_id=OPERATOR)
    assertion = make_assertion_credential(
        challenge_b64=options["options"]["challenge"],
        key=stranger_key,
        credential_id=stranger_credential_id,
        sign_count=1,
    )

    with pytest.raises(UnauthorizedError):
        await webauthn_service.verify_authentication(
            operator_id=OPERATOR,
            credential=assertion,
            expected_challenge_id=options["challenge_id"],
        )
    unknown = await audit_events("kyber.device.webauthn_credential_unknown")
    assert unknown and unknown[0]["metadata"]["reason"] == "unknown_authenticator"


async def test_a_credential_belonging_to_another_operator_is_denied():
    _, credential, key = await enroll_credential(operator_id=OPERATOR)

    options = await webauthn_service.authentication_options(operator_id="op_mallory")
    assertion = make_assertion_credential(
        challenge_b64=options["options"]["challenge"],
        key=key,
        credential_id=unb64u(credential.credential_id),
        sign_count=1,
    )
    with pytest.raises(UnauthorizedError):
        await webauthn_service.verify_authentication(
            operator_id="op_mallory",
            credential=assertion,
            expected_challenge_id=options["challenge_id"],
        )


async def test_a_tampered_assertion_signature_is_denied():
    device, credential, key = await enroll_credential()
    options = await webauthn_service.authentication_options(operator_id=OPERATOR)
    assertion = make_assertion_credential(
        challenge_b64=options["options"]["challenge"],
        key=key,
        credential_id=unb64u(credential.credential_id),
        sign_count=1,
    )
    assertion["response"]["signature"] = b64u(os.urandom(70))

    with pytest.raises(UnauthorizedError):
        await webauthn_service.verify_authentication(
            operator_id=OPERATOR,
            credential=assertion,
            expected_challenge_id=options["challenge_id"],
        )


async def test_counter_regression_marks_the_device_suspect_and_rejects():
    device, credential, key = await enroll_credential(sign_count=5)
    assert credential.sign_count == 5

    options = await webauthn_service.authentication_options(operator_id=OPERATOR)
    cloned = make_assertion_credential(
        challenge_b64=options["options"]["challenge"],
        key=key,
        credential_id=unb64u(credential.credential_id),
        sign_count=3,  # went backwards: the classic cloning signal
    )

    with pytest.raises(UnauthorizedError):
        await webauthn_service.verify_authentication(
            operator_id=OPERATOR,
            credential=cloned,
            expected_challenge_id=options["challenge_id"],
        )

    refreshed = await device_approval_service.get_device(device.device_id)
    assert refreshed.risk_state == "suspect"

    regression = await audit_events("kyber.device.webauthn_counter_regression")
    assert len(regression) == 1
    assert regression[0]["outcome"] == "blocked"
    assert regression[0]["metadata"]["stored_sign_count"] == 5
    assert regression[0]["metadata"]["presented_sign_count"] == 3

    # The stored counter must not have been advanced by the rejected assertion.
    stored = await WebAuthnCredentialRepository().find_by_credential_id(
        credential.credential_id
    )
    assert stored.sign_count == 5


async def test_the_same_credential_cannot_be_registered_twice():
    _, credential, key = await enroll_credential()
    credential_id = unb64u(credential.credential_id)

    options = await webauthn_service.registration_options(
        operator_id=OPERATOR, display_name="Alice second machine", existing_credential_ids=[]
    )
    response = make_registration_credential(
        challenge_b64=options["options"]["challenge"],
        key=key,
        credential_id=credential_id,
    )
    with pytest.raises(ConflictError):
        await webauthn_service.verify_registration(
            operator_id=OPERATOR,
            credential=response,
            expected_challenge_id=options["challenge_id"],
            display_name="Alice second machine",
            browser_family="chrome",
        )


# ══════════════════════════════════════════════════════════════════════════════
# The headline case
# ══════════════════════════════════════════════════════════════════════════════

async def test_synced_passkey_alone_on_a_second_machine_is_denied():
    """A synced WebAuthn credential, with no approved grant and no proof key, is refused.

    Platform passkeys replicate across an operator's personal machines. This
    test presents the *same* credential from a second machine: the assertion
    verifies, and the machine is still not trusted, because it has neither the
    browser-profile-bound proof key nor an approved device grant.
    """
    # Machine 1: fully enrolled — credential, proof key, approved grant.
    laptop_one, credential, passkey = await enroll_credential(
        display_name="Alice MacBook / Chrome", browser="chrome"
    )
    await device_approval_service.approve_device(
        laptop_one.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )
    laptop_one_proof_key = ec.generate_private_key(ec.SECP256R1())
    await device_proof_service.register_proof_key(
        device_id=laptop_one.device_id,
        operator_id=OPERATOR,
        public_key_b64=spki_b64(laptop_one_proof_key),
    )
    assert (await device_approval_service.is_usable(laptop_one.device_id)) == (True, None)

    # Machine 2: the passkey synced here through the operator's personal account.
    # The assertion it produces is genuinely valid.
    options = await webauthn_service.authentication_options(operator_id=OPERATOR)
    synced_assertion = make_assertion_credential(
        challenge_b64=options["options"]["challenge"],
        key=passkey,
        credential_id=unb64u(credential.credential_id),
        sign_count=1,
    )
    verified = await webauthn_service.verify_authentication(
        operator_id=OPERATOR,
        credential=synced_assertion,
        expected_challenge_id=options["challenge_id"],
    )
    assert verified.credential_id == credential.credential_id  # the passkey checks out

    # And it buys nothing. Machine 2 is its own device record: pending, and with
    # no proof key it cannot become anything else.
    laptop_two = await device_approval_service.register_device(
        operator_id=OPERATOR,
        display_name="Alice second MacBook / Chrome",
        platform_family="macos",
        browser_family="chrome",
    )
    assert laptop_two.device_id != laptop_one.device_id

    usable, reason = await device_approval_service.is_usable(laptop_two.device_id)
    assert usable is False
    assert reason == "device_unapproved"

    assert await DeviceProofKeyRepository().find_active_by_device(laptop_two.device_id) is None
    challenge_id, challenge_b64 = await device_proof_service.issue_challenge(
        device_id=laptop_two.device_id
    )
    # Machine 2 cannot even attempt a proof: laptop one's private key is
    # non-extractable and stayed in laptop one's browser profile.
    assert not await device_proof_service.verify_proof(
        device_id=laptop_two.device_id,
        challenge_id=challenge_id,
        signature_b64=b64u(
            laptop_one_proof_key.sign(unb64u(challenge_b64), ec.ECDSA(hashes.SHA256()))
        ),
    )

    # Nor can it claim laptop one's grant by re-registering the synced credential.
    reg = await webauthn_service.registration_options(
        operator_id=OPERATOR, display_name="Alice second MacBook", existing_credential_ids=[]
    )
    with pytest.raises(ConflictError):
        await webauthn_service.verify_registration(
            operator_id=OPERATOR,
            credential=make_registration_credential(
                challenge_b64=reg["options"]["challenge"],
                key=passkey,
                credential_id=unb64u(credential.credential_id),
            ),
            expected_challenge_id=reg["challenge_id"],
            device_id=laptop_two.device_id,
            display_name="Alice second MacBook",
            browser_family="chrome",
        )


# ══════════════════════════════════════════════════════════════════════════════
# Risk
# ══════════════════════════════════════════════════════════════════════════════

async def test_browser_family_is_coarse_and_specific_tokens_win():
    assert browser_family(CHROME_UA) == "chrome"
    assert browser_family(FIREFOX_UA) == "firefox"
    assert browser_family("Mozilla/5.0 ... Edg/125.0.0.0") == "edge"
    assert browser_family(None) is None


async def test_a_browser_family_change_raises_risk_and_is_explainable():
    device, _, _ = await enroll_credential(browser="chrome")
    await device_approval_service.approve_device(
        device.device_id,
        actor_id=APPROVER,
        actor_role_template_ids=[APPROVER_ROLE],
        registration_days=30,
    )

    fresh = await device_approval_service.get_device(device.device_id)
    state = await device_risk_service.evaluate(
        fresh, client_ip="203.0.113.10", user_agent=FIREFOX_UA
    )
    assert state == "suspect"

    refreshed = await device_approval_service.get_device(device.device_id)
    assert "browser_family_changed" in refreshed.metadata["risk_signals"]
    assert refreshed.metadata["risk_evaluated_at"]


async def test_risk_never_silently_de_escalates():
    device, _, _ = await enroll_credential(browser="chrome")
    await device_risk_service.mark_suspect(device.device_id, "counter_regression")

    fresh = await device_approval_service.get_device(device.device_id)
    state = await device_risk_service.evaluate(fresh, client_ip=None, user_agent=CHROME_UA)
    assert state == "suspect"


# ══════════════════════════════════════════════════════════════════════════════
# Isolation
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_proof_key_cannot_be_enrolled_against_another_operators_device():
    device = await device_approval_service.register_device(
        operator_id=OPERATOR, display_name="Alice laptop", platform_family="macos",
        browser_family="chrome",
    )
    key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(Exception) as excinfo:
        await device_proof_service.register_proof_key(
            device_id=device.device_id,
            operator_id="op_mallory",
            public_key_b64=spki_b64(key),
        )
    # Reported as "not found" — never as "belongs to someone else".
    assert "not found" in str(excinfo.value).lower()


async def test_list_devices_is_scoped_to_one_operator():
    await device_approval_service.register_device(
        operator_id=OPERATOR, display_name="Alice laptop", platform_family="macos",
        browser_family="chrome",
    )
    await device_approval_service.register_device(
        operator_id="op_bob", display_name="Bob laptop", platform_family="linux",
        browser_family="firefox",
    )

    alice = await device_approval_service.list_devices(OPERATOR)
    assert len(alice) == 1
    assert alice[0].operator_id == OPERATOR
    assert await device_approval_service.list_devices("") == []


async def test_services_share_state_through_the_repository_layer():
    """A fresh service instance sees what the module singleton wrote."""
    device, _, _ = await enroll_credential()
    other = DeviceApprovalService()
    assert (await other.get_device(device.device_id)) is not None
    assert (await other.is_usable(device.device_id)) == (False, "device_unapproved")
