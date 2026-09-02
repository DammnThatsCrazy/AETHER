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
import time
import uuid
from datetime import timedelta
from typing import Any, Optional

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
from .oidc_verifier import OIDCVerificationError, verify_oidc_id_token
from .verification_repository import VerificationChallengeRepository

logger = get_logger("aether.service.identity.verification")

# Time-to-live per method (seconds).
_OTP_TTL_SECONDS = 600
_MAGIC_LINK_TTL_SECONDS = 1800
_MAX_ATTEMPTS = 5

# ── Challenge issuance rate-limit caps (env-overridable module constants) ──────
# Sliding hourly window. Caps abuse of the (costly) email-send + challenge
# issuance path. The source IP is used ONLY for limiting and is never persisted
# as an identity signal.
_RATE_LIMIT_WINDOW_SECONDS = int(
    os.getenv("AETHER_VERIFY_RATE_WINDOW_SECONDS", "3600")
)
_MAX_CHALLENGES_PER_IDENTIFIER = int(
    os.getenv("AETHER_VERIFY_MAX_CHALLENGES_PER_IDENTIFIER_PER_HOUR", "5")
)
_MAX_CHALLENGES_PER_IP = int(
    os.getenv("AETHER_VERIFY_MAX_CHALLENGES_PER_IP_PER_HOUR", "20")
)


class _ChallengeRateLimiter:
    """Fixed-window issuance limiter for verification challenges.

    Caps challenge issuance per ``(tenant, identifier_hash)`` and per
    ``(tenant, source_ip)`` over a fixed window. Redis-backed (INCR + EXPIRE)
    when a client is injected; per-process in-memory otherwise (local / dev).
    Modeled on :class:`shared.rate_limit.limiter.BurstRateLimiter`'s
    ``_check_memory`` / ``_check_redis``.

    An instance is owned per :class:`EmailVerificationService`; the route holds a
    process singleton service, so counters persist across requests in
    production, while tests that build a fresh service get isolated counters.
    """

    def __init__(self, redis_client: Optional[Any] = None) -> None:
        self._redis = redis_client
        self._buckets: dict[str, dict] = {}

    async def check_issue(
        self,
        *,
        tenant_id: str,
        identifier_hash: str,
        source_ip: Optional[str] = None,
    ) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)`` for one issuance attempt.

        Identifier is checked first; the IP dimension is only consulted when a
        source IP is available. ``retry_after`` is 0 when allowed.
        """
        allowed, retry = await self._hit(
            f"verify:chal:id:{tenant_id}:{identifier_hash}",
            _MAX_CHALLENGES_PER_IDENTIFIER,
        )
        if not allowed:
            return False, retry
        if source_ip:
            allowed, retry = await self._hit(
                f"verify:chal:ip:{tenant_id}:{source_ip}",
                _MAX_CHALLENGES_PER_IP,
            )
            if not allowed:
                return False, retry
        return True, 0

    async def _hit(self, key: str, limit: int) -> tuple[bool, int]:
        if self._redis is not None:
            return await self._hit_redis(key, limit)
        return self._hit_memory(key, limit)

    def _hit_memory(self, key: str, limit: int) -> tuple[bool, int]:
        now = time.time()
        window = _RATE_LIMIT_WINDOW_SECONDS
        bucket = self._buckets.get(key)
        if bucket is None or (now - bucket["window_start"]) >= window:
            self._buckets[key] = {"count": 1, "window_start": now}
            return True, 0
        bucket["count"] += 1
        if bucket["count"] > limit:
            retry = max(1, int(bucket["window_start"] + window - now))
            return False, retry
        return True, 0

    async def _hit_redis(self, key: str, limit: int) -> tuple[bool, int]:
        now = time.time()
        window = _RATE_LIMIT_WINDOW_SECONDS
        bucket_ts = int(now // window)
        rkey = f"{key}:{bucket_ts}"
        try:
            count = await self._redis.incr(rkey)
            if count == 1:
                await self._redis.expire(rkey, window + 60)
        except Exception:  # noqa: BLE001 - fall back to in-memory on Redis error
            return self._hit_memory(key, limit)
        if count > limit:
            retry = max(1, int((bucket_ts + 1) * window - now))
            return False, retry
        return True, 0


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
        rate_limiter: Optional[_ChallengeRateLimiter] = None,
    ) -> None:
        self._challenges = challenge_repo or VerificationChallengeRepository()
        self._evidence = evidence_service or EvidenceService()
        self._metrics = metrics or IdentityMetrics()
        self._rate_limiter = rate_limiter or _ChallengeRateLimiter()

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

        # GAP 3: cap issuance per (tenant, identifier) and per (tenant, IP). The
        # source IP is read from provenance ONLY for limiting and is never
        # persisted or hashed as an identity signal. On exceed we return a
        # shaped dict (never raise) so the route can surface a 429-style result.
        source_ip = None
        if source_context:
            source_ip = (
                source_context.get("ip")
                or source_context.get("source_ip")
                or source_context.get("ip_address")
            )
        allowed, retry_after = await self._rate_limiter.check_issue(
            tenant_id=tenant_id,
            identifier_hash=identifier_hash,
            source_ip=source_ip,
        )
        if not allowed:
            self._metrics.record_verification_failure("rate_limited")
            return {"status": "rate_limited", "retry_after": retry_after}

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

    # Map an OIDCVerificationError.reason to the shaped failure dict + metric.
    _OIDC_FAILURE_STATUS = {
        "untrusted_issuer": "untrusted_issuer",
        "invalid_audience": "invalid_audience",
        "expired": "expired",
        "invalid_nonce": "invalid_nonce",
        "signature_unverifiable": "unverified",
        "malformed": "unverified",
    }

    def _oidc_failure(self, reason: str) -> dict:
        status = self._OIDC_FAILURE_STATUS.get(reason, "unverified")
        self._metrics.record_verification_failure(reason)
        if status == "untrusted_issuer":
            return {
                "status": "untrusted_issuer",
                "reason": REASON_UNTRUSTED_VERIFICATION_ISSUER,
            }
        return {"status": status}

    async def verify_trusted_claim(
        self,
        *,
        tenant_id: str,
        id_token: str,
        issuer_allowlist: list[str],
        expected_audience: str,
        expected_nonce: Optional[str] = None,
        consent_snapshot: Optional[dict] = None,
    ) -> dict:
        """Server-side trusted OIDC/SSO adapter.

        Accepts a RAW provider ``id_token`` and performs REAL server-side
        verification via :func:`verify_oidc_id_token` (JWKS + PyJWT RS256 with a
        local-only unsigned fallback): the RS256 signature, ``iss`` allowlist,
        ``aud``, ``exp`` and — when supplied — ``nonce`` are all enforced before
        any trust decision.

        NEVER trust a client SDK's ``email_verified`` — it is only honoured when
        it rides inside a token that passed verification here.
        """
        try:
            claims = await verify_oidc_id_token(
                id_token=id_token,
                issuer_allowlist=issuer_allowlist,
                expected_audience=expected_audience,
                expected_nonce=expected_nonce,
            )
        except OIDCVerificationError as exc:
            return self._oidc_failure(getattr(exc, "reason", "unverified"))
        except ValueError:
            return self._oidc_failure("malformed")

        # email_verified is only trusted because the token was verified above.
        email = claims.get("email")
        if claims.get("email_verified") is not True or not email:
            self._metrics.record_verification_failure("unverified")
            return {"status": "unverified"}

        identifier_hash = hash_email(email, tenant_id)
        if not identifier_hash:
            self._metrics.record_verification_failure("unverified")
            return {"status": "unverified"}

        issuer = claims.get("iss")
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
