"""Browser-profile-bound device proof.

This is the factor a synced passkey cannot carry.

The browser generates a non-extractable ECDSA P-256 keypair in one profile's
storage (``crypto.subtle.generateKey`` with ``extractable: false``) and sends
only the SPKI public half. The private half cannot be exported, copied to
another machine, or read by page script — it can only be *used*, by that
profile, on that machine. So when the operator's platform passkey syncs to a
second laptop and is presented there, the assertion may verify but this proof
does not: the second machine has no key to sign with.

Everything on this path is server-issued and single-use. The server picks the
challenge bytes, hands back an opaque id, and deletes the challenge the first
time it is redeemed, so a captured ``(challenge_id, signature)`` pair is worth
nothing on a second attempt.
"""
from __future__ import annotations

import base64
import binascii
import secrets
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics

from ..access.contracts import DeviceProofKey, now_iso
from .repository import (
    DeviceProofChallengeRepository,
    DeviceProofKeyRepository,
    TrustedDeviceRepository,
)
from .risk import DeviceRiskService, device_risk_service

logger = get_logger("aether.kyber.devices.proof")

#: Challenge lifetime. Long enough for a user-gesture-free WebCrypto sign,
#: short enough that a captured challenge is stale before it can be relayed.
CHALLENGE_TTL_SECONDS = 120

#: Challenge size. 32 bytes of CSPRNG output — the client never contributes.
CHALLENGE_BYTES = 32

_PURPOSE = "device_proof"

#: The only curve accepted. P-256 is what WebCrypto guarantees everywhere and
#: what the contract's ``algorithm='ES256'`` declares; anything else is a
#: client trying to move the ceremony onto ground we have not verified.
_REQUIRED_CURVE = "secp256r1"


def _b64url_decode(value: str) -> bytes:
    """Decode base64url (padded or not), falling back to standard base64."""
    if not isinstance(value, str) or not value.strip():
        raise BadRequestError("expected a base64url-encoded value")
    raw = value.strip()
    padded = raw + "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError):
        pass
    try:
        return base64.b64decode(padded)
    except (binascii.Error, ValueError) as exc:
        raise BadRequestError("value was not valid base64url") from exc


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def load_p256_public_key(public_key_b64: str) -> ec.EllipticCurvePublicKey:
    """Parse and validate a base64url SPKI ECDSA P-256 public key.

    Rejects anything that is not an EC key on P-256: an RSA key, a P-384 key or
    a malformed blob all fail here rather than at verification time, so a
    device can never be enrolled with a key the proof path cannot check.
    """
    der = _b64url_decode(public_key_b64)
    try:
        key = serialization.load_der_public_key(der)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise BadRequestError("device proof key was not a valid SPKI public key") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise BadRequestError("device proof key must be an ECDSA key")
    if key.curve.name != _REQUIRED_CURVE:
        raise BadRequestError(
            f"device proof key must use P-256; got {key.curve.name}"
        )
    return key


def _normalize_signature(signature: bytes) -> bytes:
    """Accept both WebCrypto (raw r||s) and DER ECDSA signatures.

    ``crypto.subtle.sign`` emits the IEEE P1363 fixed-width form; OpenSSL and
    most server-side tooling emit DER. Converting here keeps the browser from
    having to ship an ASN.1 encoder, without loosening what is verified.
    """
    if len(signature) == 64:
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        return encode_dss_signature(r, s)
    return signature


class DeviceProofService:
    """Issues and verifies device-proof challenges."""

    def __init__(
        self,
        keys: Optional[DeviceProofKeyRepository] = None,
        challenges: Optional[DeviceProofChallengeRepository] = None,
        devices: Optional[TrustedDeviceRepository] = None,
        risk: Optional[DeviceRiskService] = None,
    ) -> None:
        self._keys = keys or DeviceProofKeyRepository()
        self._challenges = challenges or DeviceProofChallengeRepository()
        self._devices = devices or TrustedDeviceRepository()
        self._risk = risk or device_risk_service

    # ── Enrollment ────────────────────────────────────────────────────────────

    async def register_proof_key(
        self, *, device_id: str, operator_id: str, public_key_b64: str
    ) -> DeviceProofKey:
        """Bind a browser-profile proof key to a device.

        Enrollment is per device *record*, and a device record is per browser
        profile — which is why a second browser on the same laptop is a second
        pending device rather than an extension of the first.
        """
        device = await self._devices.get(device_id)
        if device is None:
            raise NotFoundError("Kyber device")
        if device.operator_id != operator_id:
            # Never confirm that the device belongs to someone else.
            raise NotFoundError("Kyber device")

        load_p256_public_key(public_key_b64)

        existing = await self._keys.find_active_by_device(device_id)
        if existing is not None and existing.public_key == public_key_b64:
            return existing  # idempotent re-enrollment of the same key

        key = DeviceProofKey(
            device_id=device_id,
            operator_id=operator_id,
            public_key=public_key_b64,
            algorithm="ES256",
        )
        await self._keys.save(key)
        await self._audit(
            actor_id=operator_id,
            event_type="kyber.device.proof_key_registered",
            action="register_proof_key",
            outcome="allowed",
            device_id=device_id,
            metadata={"proof_key_id": key.proof_key_id, "algorithm": key.algorithm},
        )
        logger.info(
            "kyber device proof key registered device_id=%s proof_key_id=%s",
            device_id,
            key.proof_key_id,
        )
        return key

    async def revoke_proof_key(
        self, device_id: str, *, actor_id: str, reason: str
    ) -> bool:
        """Revoke every live proof key on a device. Idempotent."""
        keys = await self._keys.find_by_device(device_id)
        if not keys:
            return False
        for key in keys:
            key.revoked_at = now_iso()
            await self._keys.save(key)
        await self._audit(
            actor_id=actor_id,
            event_type="kyber.device.proof_key_revoked",
            action="revoke_proof_key",
            outcome="allowed",
            device_id=device_id,
            metadata={"reason": reason, "revoked": len(keys)},
        )
        logger.warning(
            "kyber device proof keys revoked device_id=%s count=%s reason=%s",
            device_id,
            len(keys),
            reason,
        )
        return True

    # ── Ceremony ──────────────────────────────────────────────────────────────

    async def issue_challenge(self, *, device_id: str) -> tuple[str, str]:
        """Issue a single-use proof challenge.

        Returns ``(challenge_id, challenge_b64)``. The id is opaque and carries
        no state of its own; the bytes live server-side until redeemed.
        """
        device = await self._devices.get(device_id)
        if device is None:
            raise NotFoundError("Kyber device")

        challenge = secrets.token_bytes(CHALLENGE_BYTES)
        challenge_b64 = _b64url_encode(challenge)
        challenge_id = f"dpc_{secrets.token_urlsafe(24)}"
        await self._challenges.issue(
            challenge_id=challenge_id,
            challenge=challenge_b64,
            subject_id=device_id,
            purpose=_PURPOSE,
            ttl_seconds=CHALLENGE_TTL_SECONDS,
            metadata={"operator_id": device.operator_id},
        )
        return challenge_id, challenge_b64

    async def verify_proof(
        self, *, device_id: str, challenge_id: str, signature_b64: str
    ) -> bool:
        """Verify an ECDSA-SHA256 signature over the issued challenge bytes.

        Returns ``True`` or ``False`` — never raises past this boundary, and
        never returns ``True`` on a path it did not fully verify. Every failure
        mode (unknown device, missing or revoked key, absent/expired/replayed
        challenge, bad signature) is recorded and folded into the device's risk
        signals before ``False`` is returned.
        """
        device = await self._devices.get(device_id) if device_id else None
        if device is None:
            await self._fail(device_id, "device_unknown", record_risk=False)
            return False

        key = await self._keys.find_active_by_device(device_id)
        if key is None:
            await self._fail(device_id, "proof_key_missing")
            return False

        # Consume first: this both fetches and burns the challenge, so a replay
        # of a previously successful proof finds nothing here.
        row = await self._challenges.consume(
            challenge_id, subject_id=device_id, purpose=_PURPOSE
        )
        if row is None:
            await self._fail(device_id, "challenge_invalid_or_replayed")
            return False

        try:
            challenge_bytes = _b64url_decode(str(row.get("challenge", "")))
            signature = _normalize_signature(_b64url_decode(signature_b64))
            public_key = load_p256_public_key(key.public_key)
            public_key.verify(signature, challenge_bytes, ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, BadRequestError, ValueError, TypeError):
            await self._fail(device_id, "signature_invalid")
            return False
        except Exception as exc:  # noqa: BLE001 - fail closed on anything unexpected
            logger.error(
                "kyber device proof verification error device_id=%s error=%s",
                device_id,
                exc,
            )
            await self._fail(device_id, "verification_error")
            return False

        key.last_verified_at = now_iso()
        await self._keys.save(key)
        await self._risk.clear_proof_failures(device_id)
        metrics.increment("kyber_device_proof_verified_total")
        await self._audit(
            actor_id=device.operator_id,
            event_type="kyber.device.proof_verified",
            action="verify_proof",
            outcome="allowed",
            device_id=device_id,
            metadata={"proof_key_id": key.proof_key_id},
        )
        return True

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _fail(
        self, device_id: str, reason: str, *, record_risk: bool = True
    ) -> None:
        metrics.increment("kyber_device_proof_failed_total", labels={"reason": reason})
        metrics.increment("kyber_device_denied_total", labels={"detail": f"proof_{reason}"})
        logger.warning(
            "kyber device proof failed device_id=%s reason=%s", device_id, reason
        )
        if record_risk:
            await self._risk.record_proof_failure(device_id, reason=reason)
        await self._audit(
            actor_id=device_id or "unknown",
            event_type="kyber.device.proof_failed",
            action="verify_proof",
            outcome="blocked",
            device_id=device_id or "unknown",
            metadata={"reason": reason},
        )

    @staticmethod
    async def _audit(
        *,
        actor_id: str,
        event_type: str,
        action: str,
        outcome: str,
        device_id: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        from services.security.audit_ledger import audit_ledger

        await audit_ledger.record(
            actor_id=actor_id,
            actor_type="olympus_operator",
            event_type=event_type,
            resource_type="kyber_device",
            action=action,
            outcome=outcome,  # type: ignore[arg-type]
            resource_id=device_id,
            metadata=metadata or {},
        )


device_proof_service = DeviceProofService()

__all__ = [
    "CHALLENGE_BYTES",
    "CHALLENGE_TTL_SECONDS",
    "DeviceProofService",
    "device_proof_service",
    "load_p256_public_key",
]
