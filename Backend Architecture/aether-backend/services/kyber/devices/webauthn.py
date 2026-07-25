"""WebAuthn platform-authenticator ceremonies for Kyber.

This is the *first* of the three things a trusted device must present, and on
its own it proves the least. Platform passkeys sync: an operator who enrolls a
credential on their MacBook will find the same credential offered on their iPad
and their second laptop, because the platform replicates it through their
personal account. Kyber therefore treats a verified assertion as evidence of
*who* is authenticating, never of *where from*. Location is settled by the
device-proof key (:mod:`.device_proof`) and the device grant
(:mod:`.approvals`).

What this module does enforce, strictly:

* ``userVerification: required`` on both ceremonies. A credential that can be
  used without a biometric or PIN is not accepted as an operator factor.
* Server-issued, single-use, TTL-bound challenges. The browser never chooses
  the challenge, and a captured ceremony cannot be replayed.
* Signature-counter regression is treated as credential cloning: the device is
  marked ``suspect``, the event is audited, and the assertion is rejected.

Relying-party configuration comes from the environment (``settings.py`` is
owned elsewhere) and fails closed: outside ``AETHER_ENV=local`` a missing RP ID
or origin stops the ceremony rather than falling back to a permissive default.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any, Optional

from shared.common.common import (
    BadRequestError,
    ConflictError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from shared.logger.logger import get_logger, metrics

from ..access.contracts import WebAuthnCredential, now_iso
from .approvals import DeviceApprovalService, device_approval_service
from .repository import (
    TrustedDeviceRepository,
    WebAuthnChallengeRepository,
    WebAuthnCredentialRepository,
)
from .risk import DeviceRiskService, device_risk_service

logger = get_logger("aether.kyber.devices.webauthn")

# The library is a hard dependency of the device plane. Guarding the import
# keeps a missing wheel from turning into an *implicit* bypass: the ceremony
# raises a clear 503 instead of some code path deciding it can skip WebAuthn.
try:  # pragma: no cover - exercised by the absence path only in broken installs
    from webauthn import (
        generate_authentication_options,
        generate_registration_options,
        verify_authentication_response,
        verify_registration_response,
    )
    from webauthn.helpers import (
        base64url_to_bytes,
        bytes_to_base64url,
        options_to_json_dict,
    )
    from webauthn.helpers.structs import (
        AttestationConveyancePreference,
        AuthenticatorAttachment,
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialDescriptor,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )

    WEBAUTHN_AVAILABLE = True
    _WEBAUTHN_IMPORT_ERROR: Optional[str] = None
except ImportError as exc:  # pragma: no cover
    WEBAUTHN_AVAILABLE = False
    _WEBAUTHN_IMPORT_ERROR = str(exc)

#: Environment variables this module reads. Worker D owns ``settings.py``;
#: these names are the contract between the two.
SETTINGS_NEEDED: tuple[str, ...] = (
    "KYBER_WEBAUTHN_RP_ID",
    "KYBER_WEBAUTHN_RP_NAME",
    "KYBER_WEBAUTHN_ORIGIN",
)

#: Challenge lifetime. Comfortably longer than a biometric prompt, far shorter
#: than anything worth capturing.
CHALLENGE_TTL_SECONDS = 300

_REGISTRATION_PURPOSE = "webauthn_registration"
_AUTHENTICATION_PURPOSE = "webauthn_authentication"

_LOCAL_RP_ID = "localhost"
_LOCAL_RP_NAME = "Olympus Kyber (local)"
_LOCAL_ORIGIN = "http://localhost:3000"


@dataclass(frozen=True)
class RelyingParty:
    """Resolved WebAuthn relying-party configuration."""

    rp_id: str
    rp_name: str
    origins: tuple[str, ...]


def _environment() -> str:
    return os.getenv("AETHER_ENV", "local").strip().lower()


def relying_party() -> RelyingParty:
    """Resolve RP configuration from the environment, failing closed.

    A wrong RP ID is not a cosmetic problem — it is what lets a credential
    registered for one origin be presented from another. Outside local
    development, an unset value stops the ceremony.
    """
    rp_id = os.getenv("KYBER_WEBAUTHN_RP_ID", "").strip()
    rp_name = os.getenv("KYBER_WEBAUTHN_RP_NAME", "").strip()
    origin_raw = os.getenv("KYBER_WEBAUTHN_ORIGIN", "").strip()

    if not rp_id or not origin_raw:
        if _environment() != "local":
            missing = [
                name
                for name, value in (
                    ("KYBER_WEBAUTHN_RP_ID", rp_id),
                    ("KYBER_WEBAUTHN_ORIGIN", origin_raw),
                )
                if not value
            ]
            raise ServiceUnavailableError(
                "Kyber WebAuthn", details={"reason": "unconfigured", "missing": missing}
            )
        rp_id = rp_id or _LOCAL_RP_ID
        rp_name = rp_name or _LOCAL_RP_NAME
        origin_raw = origin_raw or _LOCAL_ORIGIN

    origins = tuple(part.strip() for part in origin_raw.split(",") if part.strip())
    if not origins:
        raise ServiceUnavailableError(
            "Kyber WebAuthn", details={"reason": "origin_configuration_empty"}
        )
    return RelyingParty(rp_id=rp_id, rp_name=rp_name or _LOCAL_RP_NAME, origins=origins)


def _require_library() -> None:
    if not WEBAUTHN_AVAILABLE:
        raise ServiceUnavailableError(
            "Kyber WebAuthn",
            details={
                "reason": "py_webauthn_unavailable",
                "import_error": _WEBAUTHN_IMPORT_ERROR,
            },
        )


class WebAuthnService:
    """Registration and authentication ceremonies against py_webauthn."""

    def __init__(
        self,
        credentials: Optional[WebAuthnCredentialRepository] = None,
        challenges: Optional[WebAuthnChallengeRepository] = None,
        devices: Optional[TrustedDeviceRepository] = None,
        approvals: Optional[DeviceApprovalService] = None,
        risk: Optional[DeviceRiskService] = None,
    ) -> None:
        self._credentials = credentials or WebAuthnCredentialRepository()
        self._challenges = challenges or WebAuthnChallengeRepository()
        self._devices = devices or TrustedDeviceRepository()
        self._approvals = approvals or device_approval_service
        self._risk = risk or device_risk_service

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def list_credentials(self, operator_id: str) -> list[WebAuthnCredential]:
        """Every live credential for one operator. Public keys only."""
        if not operator_id:
            return []
        return await self._credentials.find_by_operator(operator_id)

    async def credentials_for_device(self, device_id: str) -> list[WebAuthnCredential]:
        return await self._credentials.find_by_device(device_id)

    # ── Registration ──────────────────────────────────────────────────────────

    async def registration_options(
        self,
        *,
        operator_id: str,
        display_name: str,
        existing_credential_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Build ``navigator.credentials.create()`` options.

        Returns ``{"challenge_id", "options", "rp_id"}``. The challenge itself
        is held server-side; the client receives it only inside the options it
        must hand straight to the authenticator.
        """
        _require_library()
        rp = relying_party()
        operator_id = (operator_id or "").strip()
        if not operator_id:
            raise BadRequestError("operator_id is required")

        exclude = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(cred_id))
            for cred_id in (existing_credential_ids or [])
            if cred_id
        ]

        options = generate_registration_options(
            rp_id=rp.rp_id,
            rp_name=rp.rp_name,
            user_id=operator_id.encode("utf-8"),
            user_name=display_name or operator_id,
            user_display_name=display_name or operator_id,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                # Platform only: a roaming key could be carried to any machine,
                # which is precisely the property the device model refuses.
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                # Discoverable is preferred, not required: the operator's
                # identity is already established by Google OIDC before this
                # ceremony runs, so demanding resident-key storage would exclude
                # otherwise sound authenticators for no security gain.
                resident_key=ResidentKeyRequirement.PREFERRED,
                require_resident_key=False,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=exclude or None,
            timeout=CHALLENGE_TTL_SECONDS * 1000,
        )

        challenge_id = await self._store_challenge(
            challenge=options.challenge,
            subject_id=operator_id,
            purpose=_REGISTRATION_PURPOSE,
        )
        return {
            "challenge_id": challenge_id,
            "rp_id": rp.rp_id,
            "options": options_to_json_dict(options),
        }

    async def verify_registration(
        self,
        *,
        operator_id: str,
        credential: dict[str, Any],
        expected_challenge_id: str,
        device_id: Optional[str] = None,
        display_name: Optional[str] = None,
        platform_family: Optional[str] = None,
        browser_family: Optional[str] = None,
    ) -> WebAuthnCredential:
        """Verify a registration response and persist the credential.

        When ``device_id`` is omitted a new **pending** device record is created
        for this credential. Registration never approves anything: the operator
        still needs a second actor to approve the device and a proof key
        enrolled in this browser profile before the credential is worth
        anything.
        """
        _require_library()
        rp = relying_party()

        challenge = await self._consume_challenge(
            expected_challenge_id,
            subject_id=operator_id,
            purpose=_REGISTRATION_PURPOSE,
            device_id=device_id,
        )

        try:
            verification = verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=rp.rp_id,
                expected_origin=list(rp.origins),
                require_user_presence=True,
                require_user_verification=True,
            )
        except Exception as exc:  # noqa: BLE001 - every failure is one denial
            await self._audit(
                actor_id=operator_id,
                event_type="kyber.device.webauthn_registration_failed",
                action="verify_registration",
                outcome="failed",
                device_id=device_id or "unknown",
                metadata={"error": type(exc).__name__},
            )
            metrics.increment(
                "kyber_device_denied_total", labels={"detail": "webauthn_registration"}
            )
            logger.warning(
                "kyber webauthn registration rejected operator_id=%s error=%s",
                operator_id,
                exc,
            )
            raise UnauthorizedError("WebAuthn registration could not be verified") from exc

        credential_id = bytes_to_base64url(verification.credential_id)
        if await self._credentials.find_by_credential_id(credential_id) is not None:
            raise ConflictError("this authenticator credential is already registered")

        if device_id is None:
            device = await self._approvals.register_device(
                operator_id=operator_id,
                display_name=display_name or "Unnamed device",
                platform_family=platform_family,
                browser_family=browser_family,
            )
            device_id = device.device_id
        else:
            device = await self._devices.get(device_id)
            if device is None or device.operator_id != operator_id:
                raise UnauthorizedError("device does not belong to this operator")

        response = credential.get("response") or {}
        transports = [t for t in (response.get("transports") or []) if isinstance(t, str)]
        device_type = getattr(
            verification.credential_device_type, "value", verification.credential_device_type
        )
        record = WebAuthnCredential(
            device_id=device_id,
            operator_id=operator_id,
            credential_id=credential_id,
            public_key=bytes_to_base64url(verification.credential_public_key),
            sign_count=int(verification.sign_count or 0),
            credential_attachment=(
                credential.get("authenticatorAttachment")
                if isinstance(credential.get("authenticatorAttachment"), str)
                else None
            ),
            credential_transports=transports,
            aaguid=verification.aaguid,
            # A "multi_device" credential is one the platform may sync to the
            # operator's other machines. We record it rather than refuse it —
            # the proof key and the grant are what make sync harmless.
            backup_eligible=str(device_type) == "multi_device",
            backup_state=bool(verification.credential_backed_up),
        )
        await self._credentials.save(record)

        await self._audit(
            actor_id=operator_id,
            event_type="kyber.device.webauthn_registered",
            action="verify_registration",
            outcome="allowed",
            device_id=device_id,
            metadata={
                "credential_pk": record.credential_pk,
                "aaguid": record.aaguid,
                "backup_eligible": record.backup_eligible,
                "backup_state": record.backup_state,
            },
        )
        metrics.increment("kyber_device_webauthn_registered_total")
        logger.info(
            "kyber webauthn credential registered device_id=%s operator_id=%s synced=%s",
            device_id,
            operator_id,
            record.backup_eligible,
        )
        return record

    # ── Authentication ────────────────────────────────────────────────────────

    async def authentication_options(self, *, operator_id: str) -> dict[str, Any]:
        """Build ``navigator.credentials.get()`` options for one operator."""
        _require_library()
        rp = relying_party()
        operator_id = (operator_id or "").strip()
        if not operator_id:
            raise BadRequestError("operator_id is required")

        credentials = await self._credentials.find_by_operator(operator_id)
        allow = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
            for c in credentials
        ]

        options = generate_authentication_options(
            rp_id=rp.rp_id,
            allow_credentials=allow or None,
            user_verification=UserVerificationRequirement.REQUIRED,
            timeout=CHALLENGE_TTL_SECONDS * 1000,
        )
        challenge_id = await self._store_challenge(
            challenge=options.challenge,
            subject_id=operator_id,
            purpose=_AUTHENTICATION_PURPOSE,
        )
        return {
            "challenge_id": challenge_id,
            "rp_id": rp.rp_id,
            "options": options_to_json_dict(options),
        }

    async def verify_authentication(
        self,
        *,
        operator_id: str,
        credential: dict[str, Any],
        expected_challenge_id: str,
    ) -> WebAuthnCredential:
        """Verify an assertion and advance the stored signature counter."""
        _require_library()
        rp = relying_party()

        challenge = await self._consume_challenge(
            expected_challenge_id,
            subject_id=operator_id,
            purpose=_AUTHENTICATION_PURPOSE,
            device_id=None,
        )

        credential_id = credential.get("id")
        stored = (
            await self._credentials.find_by_credential_id(credential_id)
            if isinstance(credential_id, str)
            else None
        )
        if stored is None or stored.operator_id != operator_id or stored.revoked_at:
            await self._audit(
                actor_id=operator_id,
                event_type="kyber.device.webauthn_credential_unknown",
                action="verify_authentication",
                outcome="blocked",
                device_id=stored.device_id if stored else "unknown",
                metadata={"reason": "credential_not_registered"},
            )
            metrics.increment(
                "kyber_device_denied_total", labels={"detail": "webauthn_unknown_credential"}
            )
            raise UnauthorizedError("WebAuthn credential is not recognised")

        try:
            verification = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=rp.rp_id,
                expected_origin=list(rp.origins),
                credential_public_key=base64url_to_bytes(stored.public_key),
                # The library's own counter check is disabled here on purpose:
                # a regression is a *cloning* signal that has to raise device
                # risk, not just fail the request, so it is evaluated below
                # where that escalation can happen.
                credential_current_sign_count=0,
                require_user_verification=True,
            )
        except Exception as exc:  # noqa: BLE001 - every failure is one denial
            await self._audit(
                actor_id=operator_id,
                event_type="kyber.device.webauthn_authentication_failed",
                action="verify_authentication",
                outcome="failed",
                device_id=stored.device_id,
                metadata={"error": type(exc).__name__},
            )
            metrics.increment(
                "kyber_device_denied_total", labels={"detail": "webauthn_authentication"}
            )
            raise UnauthorizedError("WebAuthn assertion could not be verified") from exc

        new_sign_count = int(verification.new_sign_count or 0)
        if stored.sign_count > 0 and new_sign_count <= stored.sign_count:
            await self._on_counter_regression(stored, new_sign_count)
            raise UnauthorizedError("WebAuthn assertion rejected")

        stored.sign_count = max(new_sign_count, stored.sign_count)
        stored.last_used_at = now_iso()
        stored.backup_state = bool(verification.credential_backed_up)
        await self._credentials.save(stored)
        await self._approvals.touch(stored.device_id)

        await self._audit(
            actor_id=operator_id,
            event_type="kyber.device.webauthn_authenticated",
            action="verify_authentication",
            outcome="allowed",
            device_id=stored.device_id,
            metadata={"credential_pk": stored.credential_pk, "sign_count": stored.sign_count},
        )
        metrics.increment("kyber_device_webauthn_verified_total")
        return stored

    async def revoke_credential(
        self, credential_pk: str, *, actor_id: str, reason: str
    ) -> bool:
        """Revoke one stored credential. Frees its unique id for re-enrollment."""
        stored = await self._credentials.get(credential_pk)
        if stored is None or stored.revoked_at:
            return False
        stored.revoked_at = now_iso()
        await self._credentials.save(stored)
        await self._audit(
            actor_id=actor_id,
            event_type="kyber.device.webauthn_revoked",
            action="revoke_credential",
            outcome="allowed",
            device_id=stored.device_id,
            metadata={"credential_pk": credential_pk, "reason": reason},
        )
        return True

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _on_counter_regression(
        self, stored: WebAuthnCredential, new_sign_count: int
    ) -> None:
        """Handle a signature counter that did not advance.

        An authenticator that maintains a counter never replays a value. A
        value at or below the stored one means either a cloned credential or a
        replayed assertion, and both deserve the same answer: reject, mark the
        device suspect, and leave a record an investigator can find.
        """
        await self._risk.mark_suspect(stored.device_id, "counter_regression")
        await self._audit(
            actor_id=stored.operator_id,
            event_type="kyber.device.webauthn_counter_regression",
            action="verify_authentication",
            outcome="blocked",
            device_id=stored.device_id,
            metadata={
                "credential_pk": stored.credential_pk,
                "stored_sign_count": stored.sign_count,
                "presented_sign_count": new_sign_count,
                "interpretation": "possible credential cloning",
            },
        )
        metrics.increment("kyber_device_counter_regression_total")
        metrics.increment(
            "kyber_device_denied_total", labels={"detail": "counter_regression"}
        )
        logger.error(
            "kyber webauthn counter regression device_id=%s stored=%s presented=%s",
            stored.device_id,
            stored.sign_count,
            new_sign_count,
        )

    async def _store_challenge(
        self, *, challenge: bytes, subject_id: str, purpose: str
    ) -> str:
        challenge_id = f"wac_{secrets.token_urlsafe(24)}"
        await self._challenges.issue(
            challenge_id=challenge_id,
            challenge=bytes_to_base64url(challenge),
            subject_id=subject_id,
            purpose=purpose,
            ttl_seconds=CHALLENGE_TTL_SECONDS,
        )
        return challenge_id

    async def _consume_challenge(
        self, challenge_id: str, *, subject_id: str, purpose: str, device_id: Optional[str]
    ) -> bytes:
        row = await self._challenges.consume(
            challenge_id, subject_id=subject_id, purpose=purpose
        )
        if row is None:
            await self._audit(
                actor_id=subject_id,
                event_type="kyber.device.webauthn_challenge_invalid",
                action=purpose,
                outcome="blocked",
                device_id=device_id or "unknown",
                metadata={"reason": "challenge_absent_expired_or_replayed"},
            )
            metrics.increment(
                "kyber_device_denied_total", labels={"detail": "webauthn_challenge"}
            )
            raise UnauthorizedError("WebAuthn challenge is invalid or already used")
        return base64url_to_bytes(str(row.get("challenge", "")))

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


webauthn_service = WebAuthnService()

__all__ = [
    "CHALLENGE_TTL_SECONDS",
    "SETTINGS_NEEDED",
    "WEBAUTHN_AVAILABLE",
    "RelyingParty",
    "WebAuthnService",
    "relying_party",
    "webauthn_service",
]
