"""Mobile-bound device proof key enrollment — /v1/kyber/mobile/proof-keys.

M6c of the Kyber milestone program: let a MOBILE device bind an ECDSA P-256
proof key to an operator's trusted device through the SAME mechanism the
browser-profile path uses (:mod:`.device_proof`). This is not a second proof
or attestation system:

* **Same store, same verify path.** Persistence goes through
  :class:`DeviceProofKeyRepository` — the exact table (and, in local mode, the
  exact shared backing store) :meth:`DeviceProofService.verify_proof` reads
  from. A key registered here is challenged, verified and risk-scored by the
  unchanged browser-proof path; the proof service is never forked.
* **Same key validation.** Every request reuses
  :func:`load_p256_public_key`, so a device can only ever be enrolled with a
  key the proof path can actually check — base64url SPKI ECDSA P-256
  (``algorithm='ES256'``), and nothing else.
* **Same authorization gate.** Every route is guarded by
  ``require_kyber_access(SELF_CAPABILITY)``: only a live workforce session can
  register or revoke, and a ``device_id`` that is absent or belongs to another
  operator reads as a 404 — never a 403 — so this surface never confirms
  another operator's device ids (the continuation router's ``_require_owned``
  idiom).

Upsert semantics. Re-enrolling the same ``(device_id, operator_id)`` with a
different key REPLACES the stored key **in place** — one live row per device,
exactly what :meth:`DeviceProofKeyRepository.find_active_by_device` returns to
``verify_proof``. A fresh key creates a new row. Revoking a key sets
``revoked_at`` and removes it from the active list; the revoked row stays for
forensics, mirroring browser re-enrollment.

Re-key step-up gate. Replacing a **live** key is the one step that re-binds an
attested device to new key material, so it demands a fresh step-up grant. The
grant itself can only be obtained against the *current* live key (the proof
service verifies against ``find_active_by_device``), which is exactly why a
captured session cookie alone cannot re-key a device. First enrollment — no
existing live key — needs no step-up, so legitimate mobile onboarding still
works.

Projection decision (D6 — all wire fields snake_case). The register and revoke
responses return the full record, including the SPKI ``public_key`` — a public
value the device already holds, returned so the client can confirm the exact
key the server stored. The list endpoint is deliberately redacted to the
read-only mobile posture: it returns only
``proof_key_id, device_id, operator_id, algorithm, created_at, last_verified_at``
and never echoes ``public_key`` material, so a read-only inventory carries no
key bytes a mobile client does not already hold. The optional request ``label``
has no column on :class:`DeviceProofKey`; it is accepted on the wire for API
contract stability and carried in the re-key audit event rather than persisted
on the row.

The router is intentionally not mounted here — the application assembles it, so
the orchestrator mounts ``mobile_proof_router`` serially with the rest of the
Kyber plane (``main.py`` is not edited by this module).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel

from shared.common.common import APIResponse, BadRequestError, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

from ..access.capabilities import (
    ACTION_CLASS_ANNOTATE,
    ACTION_CLASS_READ,
    SELF_CAPABILITY,
)
from ..access.contracts import DeviceProofKey, TrustedDevice, now_iso
from ..access.dependencies import KyberAccessContext, require_kyber_access
from .approvals import device_approval_service
from .device_proof import device_proof_service, load_p256_public_key
from .repository import DeviceProofKeyRepository

logger = get_logger("aether.kyber.devices.mobile_proof")

mobile_proof_router = APIRouter(
    prefix="/v1/kyber/mobile/proof-keys",
    tags=["Kyber Mobile Attestation"],
)

#: The repository :class:`DeviceProofService` verifies against. Local mode
#: shares one in-memory backing dict per table across every instance, so this
#: module-level repo and ``device_proof_service._keys`` observe the same rows.
_keys = DeviceProofKeyRepository()


class MobileProofKeyRegister(BaseModel):
    """Snake_case wire contract for mobile proof key registration (D6)."""

    device_id: str
    #: base64url-encoded SPKI ECDSA P-256 public key.
    public_key: str
    algorithm: str = "ES256"
    #: Informational label (e.g. "aether-mobile-ios"). Not persisted on the
    #: DeviceProofKey row (it has no such column); carried in audit metadata.
    label: Optional[str] = None


#: Fields the read-only list projection exposes. Deliberately excludes
#: ``public_key`` (redacted mobile posture) and ``revoked_at`` (revoked keys
#: are not listed at all).
_LIST_FIELDS = (
    "proof_key_id",
    "device_id",
    "operator_id",
    "algorithm",
    "created_at",
    "last_verified_at",
)


def _proof_key_view(key: DeviceProofKey) -> dict[str, Any]:
    """Full record projection for register/revoke responses.

    ``public_key`` is public SPKI material the device already holds; echoing it
    here lets the client confirm the exact key the server stored. The private
    half never leaves the mobile Secure Enclave and is never transmitted.
    """
    return {
        "proof_key_id": key.proof_key_id,
        "device_id": key.device_id,
        "operator_id": key.operator_id,
        "algorithm": key.algorithm,
        "public_key": key.public_key,
        "created_at": key.created_at,
        "last_verified_at": key.last_verified_at,
        "revoked_at": key.revoked_at,
    }


def _proof_key_list_view(key: DeviceProofKey) -> dict[str, Any]:
    """Redacted inventory projection — never echoes public-key material."""
    return {field: getattr(key, field) for field in _LIST_FIELDS}


async def _require_owned_device(operator_id: str, device_id: str) -> TrustedDevice:
    """The caller's own device, or a 404 indistinguishable from an absent one.

    Unknown and foreign device ids return the same error so this surface never
    confirms whether another operator's device exists — matching the
    continuation router's ``_require_owned`` idiom (404, never 403).
    """
    device = await device_approval_service.get_device(device_id)
    if device is None or device.operator_id != operator_id:
        raise NotFoundError("Kyber device")
    return device


async def _upsert_key(
    *,
    device_id: str,
    operator_id: str,
    public_key_b64: str,
    algorithm: str,
    session_id: str,
) -> tuple[DeviceProofKey, bool]:
    """One live key per device: replace in place (step-up gated), or create.

    Returns ``(key, replaced)``. ``replaced=True`` means an existing live key
    was updated in place; ``replaced=False`` means a new row was created (or an
    identical key was already active). ``find_active_by_device`` is the exact
    lookup ``verify_proof`` performs, so the row this route keeps live is the
    one the proof path will check.

    The replace path re-keys a LIVE attestation key, so it demands a fresh
    step-up grant for this session first — a grant that step-up verification
    itself can only obtain against the current live key, which is exactly why a
    captured session cookie alone cannot re-key a device. First enrollment (no
    existing live key) needs no step-up.
    """
    existing = await _keys.find_active_by_device(device_id)
    if existing is not None and existing.operator_id == operator_id:
        from ..sessions.step_up import step_up_service

        ok, reason = await step_up_service.require_fresh(session_id)
        if not ok:
            raise ForbiddenError(
                "re-keying a live device proof key requires a fresh step-up",
                details={"denial_reason": reason or "step_up_required"},
            )
        existing.public_key = public_key_b64
        existing.algorithm = algorithm
        key = await _keys.save(existing)
        return key, True

    key = await device_proof_service.register_proof_key(
        device_id=device_id,
        operator_id=operator_id,
        public_key_b64=public_key_b64,
    )
    return key, False


async def _audit(
    *,
    actor_id: str,
    event_type: str,
    action: str,
    device_id: str,
    proof_key_id: Optional[str] = None,
    label: Optional[str] = None,
) -> None:
    """Record a governed mobile proof-key event on the shared audit ledger.

    Mirrors the shape :meth:`DeviceProofService._audit` writes so the mobile
    and browser-proof trails stay one ledger.
    """
    from services.security.audit_ledger import audit_ledger

    metadata: dict[str, Any] = {"proof_key_id": proof_key_id} if proof_key_id else {}
    if label:
        metadata["label"] = label
    await audit_ledger.record(
        actor_id=actor_id,
        actor_type="olympus_operator",
        event_type=event_type,
        resource_type="kyber_device",
        action=action,
        outcome="allowed",  # type: ignore[arg-type]
        resource_id=device_id,
        metadata=metadata,
    )


# ── Routes ───────────────────────────────────────────────────────────────────

@mobile_proof_router.post("")
async def register_mobile_proof_key(
    body: MobileProofKeyRegister,
    context: KyberAccessContext = Depends(
        require_kyber_access(SELF_CAPABILITY, action_class=ACTION_CLASS_ANNOTATE)
    ),
) -> APIResponse:
    """Register or re-enroll a mobile-bound proof key for one of the caller's devices."""
    operator_id = context.operator_id

    if body.algorithm != "ES256":
        raise BadRequestError("only the ES256 (ECDSA P-256) algorithm is supported")

    # The same validation the browser-proof path applies: only a base64url SPKI
    # ECDSA P-256 key can ever be enrolled.
    load_p256_public_key(body.public_key)

    await _require_owned_device(operator_id, body.device_id)

    key, replaced = await _upsert_key(
        device_id=body.device_id,
        operator_id=operator_id,
        public_key_b64=body.public_key,
        algorithm=body.algorithm,
        session_id=context.session.session_id,
    )
    if replaced:
        # A re-enrollment replaced an existing live key; record the governed
        # event (the create path is audited inside register_proof_key).
        await _audit(
            actor_id=operator_id,
            event_type="kyber.device.proof_key_replaced",
            action="register_mobile_proof_key",
            device_id=body.device_id,
            proof_key_id=key.proof_key_id,
            label=body.label,
        )
    logger.info(
        "kyber mobile proof key registered device_id=%s proof_key_id=%s replaced=%s",
        body.device_id,
        key.proof_key_id,
        replaced,
    )
    return APIResponse(data=_proof_key_view(key))


@mobile_proof_router.get("")
async def list_mobile_proof_keys(
    context: KyberAccessContext = Depends(
        require_kyber_access(SELF_CAPABILITY, action_class=ACTION_CLASS_READ)
    ),
) -> APIResponse:
    """List the caller's live registered proof keys (redacted projection)."""
    operator_id = context.operator_id
    keys = await _keys.find_by_operator(operator_id)
    active = [key for key in keys if not key.revoked_at]
    return APIResponse(
        data={
            "operator_id": operator_id,
            "proof_keys": [_proof_key_list_view(key) for key in active],
        }
    )


@mobile_proof_router.delete("/{proof_key_id}")
async def revoke_mobile_proof_key(
    proof_key_id: str = Path(...),
    context: KyberAccessContext = Depends(
        require_kyber_access(SELF_CAPABILITY, action_class=ACTION_CLASS_ANNOTATE)
    ),
) -> APIResponse:
    """Revoke one of the caller's proof keys (sets ``revoked_at``). Idempotent."""
    operator_id = context.operator_id
    key = await _keys.get(proof_key_id)
    if key is None or key.operator_id != operator_id:
        # Absent and foreign keys are indistinguishable — 404, never 403.
        raise NotFoundError("device proof key")

    if key.revoked_at is None:
        key.revoked_at = now_iso()
        key = await _keys.save(key)
        await _audit(
            actor_id=operator_id,
            event_type="kyber.device.proof_key_revoked",
            action="revoke_mobile_proof_key",
            device_id=key.device_id,
            proof_key_id=key.proof_key_id,
        )
    return APIResponse(data=_proof_key_view(key))


__all__ = [
    "MobileProofKeyRegister",
    "mobile_proof_router",
]
