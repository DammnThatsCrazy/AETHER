"""Email ownership-verification service (identity assurance layer).

Implements the challenge/response flows that prove a user controls an email
identifier and, on success, emit durable :class:`VerificationEvidence` via
:class:`EvidenceService`:

* **OTP** — a 6-digit numeric code (TTL 600s), verified + consumed in one step.
* **Magic link** — a URL-safe token (TTL 1800s). The GET landing is
  NON-CONSUMING and scanner-safe (validates only); a separate POST consumes it
  and issues evidence.
* **Trusted provider claim** — a server-side OIDC/SSO adapter that accepts a
  pre-decoded, upstream-verified claims dict.

Security invariants:
* Raw OTPs/tokens are NEVER persisted — only their HMAC digest
  (:func:`hash_verification_token`) under a purpose-bound scope.
* Presented secrets are compared in constant time
  (:func:`verify_token_digest`).
* All randomness comes from :mod:`secrets`.
* Everything is tenant-scoped; PII and secrets are never logged.
"""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import timedelta
from typing import Optional

from shared.common.common import parse_iso, utc_now
from shared.logger.logger import get_logger

from .evidence import EvidenceService
from .hashing import hash_email, hash_verification_token, verify_token_digest
from .metrics import IdentityMetrics
from .models import (
    REASON_UNTRUSTED_VERIFICATION_ISSUER,
    AssuranceLevel,
    VerificationChallenge,
    VerificationChallengeState,
    VerificationMethod,
)
from .verification_repository import VerificationChallengeRepository

logger = get_logger("aether.service.identity.verification")

# Time-to-live per method (seconds).
_OTP_TTL_SECONDS = 600
_MAGIC_LINK_TTL_SECONDS = 1800
_MAX_ATTEMPTS = 5


def _is_expired(record: dict, now_iso: str) -> bool:
    """True when the challenge's ``expires_at`` is in the past."""
    expires_at = record.get("expires_at") or ""
    if not expires_at:
        return False
    try:
        expires = parse_iso(expires_at)
        now = parse_iso(now_iso)
    except Exception:  # noqa: BLE001 - defensive; treat unparseable as not-expired
        return False
    return now > expires


class EmailVerificationService:
    """Issue and validate email ownership-verification challenges."""

    def __init__(
        self,
        challenge_repo: Optional[VerificationChallengeRepository] = None,
        evidence_service: Optional[EvidenceService] = None,
        metrics: Optional[IdentityMetrics] = None,
    ) -> None:
        self._challenges = challenge_repo or VerificationChallengeRepository()
        self._evidence = evidence_service or EvidenceService()
        self._metrics = metrics or IdentityMetrics()

    async def issue_email_challenge(
        self,
        *,
        tenant_id: str,
        email: str,
        method: str = VerificationMethod.EMAIL_OTP.value,
        purpose: str = "identity_verification",
        subject_hint_id: Optional[str] = None,
        consent_snapshot: Optional[dict] = None,
        source_context: Optional[dict] = None,
    ) -> dict:
        """Create an OTP or magic-link challenge for ``email``.

        The raw secret is delivered out-of-band (email) in production; only its
        digest is persisted. In the ``local`` env the secret is echoed back so
        tests and the callback flow can drive verification.
        """
        identifier_hash = hash_email(email, tenant_id)
        if not identifier_hash:
            raise ValueError("invalid email")

        scope = f"{purpose}:{tenant_id}"
        if method == VerificationMethod.EMAIL_MAGIC_LINK.value:
            secret = secrets.token_urlsafe(32)
            ttl = _MAGIC_LINK_TTL_SECONDS
        else:
            secret = f"{secrets.randbelow(1000000):06d}"
            ttl = _OTP_TTL_SECONDS
        secret_digest = hash_verification_token(secret, scope)

        now = utc_now()
        expires_at = (now + timedelta(seconds=ttl)).isoformat()

        # PII-safe provenance only; consent rides inside source_context so a
        # downstream replay can read it back.
        ctx = dict(source_context or {})
        if consent_snapshot is not None:
            ctx["consent"] = consent_snapshot

        challenge = VerificationChallenge(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            identifier_type="email",
            identifier_hash=identifier_hash,
            method=method,
            purpose=purpose,
            secret_digest=secret_digest,
            state=VerificationChallengeState.ISSUED.value,
            subject_hint_id=subject_hint_id,
            issued_at=now.isoformat(),
            expires_at=expires_at,
            max_attempts=_MAX_ATTEMPTS,
            source_context=ctx,
        )
        await self._challenges.create(challenge)
        self._metrics.record_verification_challenge(method)

        result = {
            "challenge_id": challenge.id,
            "method": method,
            "expires_at": expires_at,
            "identifier_hash": identifier_hash,
        }
        if os.getenv("AETHER_ENV", "local") == "local":
            result["secret"] = secret
        return result

    async def verify_email_otp(
        self, *, tenant_id: str, challenge_id: str, code: str
    ) -> dict:
        """Verify an OTP code and, on success, consume + issue evidence."""
        record = await self._challenges.get_for_tenant(tenant_id, challenge_id)
        if record is None:
            self._metrics.record_verification_failure("not_found")
            return {"status": "not_found"}

        now = utc_now()
        now_iso = now.isoformat()
        if _is_expired(record, now_iso):
            await self._challenges.apply_update(
                tenant_id,
                challenge_id,
                {"state": VerificationChallengeState.EXPIRED.value},
            )
            self._metrics.record_verification_expired()
            return {"status": "expired"}

        if record.get("state") != VerificationChallengeState.ISSUED.value:
            return {"status": "invalid_state", "state": record.get("state")}

        updated = await self._challenges.increment_attempt(tenant_id, challenge_id)
        if updated and updated.get("state") == VerificationChallengeState.LOCKED.value:
            self._metrics.record_verification_failure("locked")
            return {"status": "locked"}

        scope = f"{record.get('purpose', 'identity_verification')}:{tenant_id}"
        if not verify_token_digest(code, record.get("secret_digest", ""), scope):
            attempts = (updated or record).get("attempt_count", 0)
            self._metrics.record_verification_failure("invalid_code")
            return {"status": "invalid", "attempts": attempts}

        await self._challenges.apply_update(
            tenant_id,
            challenge_id,
            {
                "state": VerificationChallengeState.VALIDATED.value,
                "validated_at": now_iso,
            },
        )
        consumed = await self._challenges.consume_atomic(tenant_id, challenge_id)
        if consumed is None:
            return {"status": "already_consumed"}

        evidence = await self._evidence.issue_evidence(
            tenant_id=tenant_id,
            identifier_type="email",
            identifier_hash=record["identifier_hash"],
            verification_method=VerificationMethod.EMAIL_OTP.value,
            challenge_id=challenge_id,
            consent_snapshot=(record.get("source_context") or {}).get("consent"),
        )
        self._metrics.record_verification_success(VerificationMethod.EMAIL_OTP.value)
        return {"status": "verified", "evidence_id": evidence.id}

    async def validate_magic_link(
        self, *, tenant_id: str, challenge_id: str, token: str
    ) -> dict:
        """GET landing for a magic link: NON-CONSUMING, scanner-safe.

        Validates the token and, if it matches, marks the challenge validated.
        It NEVER consumes the challenge and NEVER creates evidence — link
        pre-scanners hitting this endpoint must not burn or complete the flow.
        """
        record = await self._challenges.get_for_tenant(tenant_id, challenge_id)
        if record is None:
            return {"status": "not_found"}

        now = utc_now()
        now_iso = now.isoformat()
        if _is_expired(record, now_iso):
            await self._challenges.apply_update(
                tenant_id,
                challenge_id,
                {"state": VerificationChallengeState.EXPIRED.value},
            )
            self._metrics.record_verification_expired()
            return {"status": "expired"}

        scope = f"{record.get('purpose', 'identity_verification')}:{tenant_id}"
        if record.get("state") == VerificationChallengeState.ISSUED.value and (
            verify_token_digest(token, record.get("secret_digest", ""), scope)
        ):
            await self._challenges.apply_update(
                tenant_id,
                challenge_id,
                {
                    "state": VerificationChallengeState.VALIDATED.value,
                    "validated_at": now_iso,
                },
            )
            return {"status": "validated", "challenge_id": challenge_id}
        return {"status": "invalid"}

    async def consume_magic_link(
        self, *, tenant_id: str, challenge_id: str
    ) -> dict:
        """POST consume for a magic link: only succeeds on a validated
        challenge, then issues evidence."""
        record = await self._challenges.get_for_tenant(tenant_id, challenge_id)
        if record is None:
            return {"status": "not_found"}

        consumed = await self._challenges.consume_atomic(tenant_id, challenge_id)
        if consumed is None:
            return {"status": "not_validated_or_consumed"}

        evidence = await self._evidence.issue_evidence(
            tenant_id=tenant_id,
            identifier_type="email",
            identifier_hash=record["identifier_hash"],
            verification_method=VerificationMethod.EMAIL_MAGIC_LINK.value,
            challenge_id=challenge_id,
            consent_snapshot=(record.get("source_context") or {}).get("consent"),
        )
        self._metrics.record_verification_success(
            VerificationMethod.EMAIL_MAGIC_LINK.value
        )
        return {"status": "verified", "evidence_id": evidence.id}

    async def verify_trusted_claim(
        self,
        *,
        tenant_id: str,
        claims: dict,
        issuer_allowlist: list[str],
        expected_audience: str,
        consent_snapshot: Optional[dict] = None,
    ) -> dict:
        """Server-side trusted OIDC/SSO adapter.

        ``claims`` MUST already be a fully validated, decoded token payload:
        signature, expiry (``exp``) and nonce verification are the caller's or
        the gateway's responsibility (e.g. PyJWT against the provider JWKS) and
        MUST happen BEFORE this method is called. This method performs only the
        trust/authorization checks below and NEVER verifies a signature.

        NEVER trust a client SDK's ``email_verified`` — this path is only for
        backend-validated provider claims.
        """
        issuer = claims.get("iss")
        if issuer not in issuer_allowlist:
            self._metrics.record_verification_failure("untrusted_issuer")
            return {
                "status": "untrusted_issuer",
                "reason": REASON_UNTRUSTED_VERIFICATION_ISSUER,
            }

        aud = claims.get("aud")
        aud_values = aud if isinstance(aud, (list, tuple, set)) else [aud]
        if expected_audience not in aud_values:
            self._metrics.record_verification_failure("audience_mismatch")
            return {"status": "invalid_audience"}

        email = claims.get("email")
        if claims.get("email_verified") is not True or not email:
            self._metrics.record_verification_failure("unverified")
            return {"status": "unverified"}

        identifier_hash = hash_email(email, tenant_id)
        if not identifier_hash:
            self._metrics.record_verification_failure("unverified")
            return {"status": "unverified"}

        evidence = await self._evidence.issue_evidence(
            tenant_id=tenant_id,
            identifier_type="email",
            identifier_hash=identifier_hash,
            verification_method=VerificationMethod.OIDC_VERIFIED_CLAIM.value,
            issuer=str(issuer),
            issuer_subject_hash=hash_verification_token(
                str(claims.get("sub")), f"sub:{tenant_id}"
            ),
            assurance_level=AssuranceLevel.AUTHORITATIVE.value,
            consent_snapshot=consent_snapshot,
        )
        self._metrics.record_verification_success(
            VerificationMethod.OIDC_VERIFIED_CLAIM.value
        )
        return {"status": "verified", "evidence_id": evidence.id}


__all__ = ["EmailVerificationService"]
