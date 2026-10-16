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
import base64
import hashlib
import re
import uuid
from datetime import timedelta
from typing import Optional

from shared.common.common import parse_iso, utc_now
from shared.logger.logger import get_logger

from .evidence import EvidenceService
from .hashing import (
    ensure_wallet_subject_binding_key,
    hash_email,
    hash_value,
    hash_verification_token,
    hash_wallet,
    verify_token_digest,
)
from .metrics import IdentityMetrics
from .models import (
    REASON_UNTRUSTED_VERIFICATION_ISSUER,
    AssuranceLevel,
    VerificationChallenge,
    VerificationChallengeState,
    VerificationEvidenceType,
    VerificationMethod,
)
from .verification_repository import VerificationChallengeRepository

logger = get_logger("aether.service.identity.verification")

# Time-to-live per method (seconds).
_OTP_TTL_SECONDS = 600
_MAGIC_LINK_TTL_SECONDS = 1800
_MAX_ATTEMPTS = 5
_WALLET_CHALLENGE_TTL_SECONDS = 300


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


class WalletVerificationService:
    """Issue one-time wallet challenges and persist verified ownership.

    EVM uses EIP-191 ``personal_sign`` recovery. Solana verifies an Ed25519
    signature over the exact UTF-8 message. Unsupported address families fail
    closed; a transaction observation is not a substitute for key-control
    proof.
    """

    def __init__(
        self,
        challenge_repo: Optional[VerificationChallengeRepository] = None,
        evidence_service: Optional[EvidenceService] = None,
        metrics: Optional[IdentityMetrics] = None,
    ) -> None:
        self._challenges = challenge_repo or VerificationChallengeRepository()
        self._evidence = evidence_service or EvidenceService()
        self._metrics = metrics or IdentityMetrics()

    async def issue_wallet_challenge(
        self,
        *,
        tenant_id: str,
        anonymous_id: str,
        wallet_address: str,
        chain_namespace: str,
        identity_namespace: str = "",
        consent_snapshot: Optional[dict] = None,
    ) -> dict:
        """Persist a bounded challenge bound to a tenant and consented subject."""
        ensure_wallet_subject_binding_key(tenant_id)
        namespace = _wallet_proof_namespace(chain_namespace)
        address = _wallet_proof_address(wallet_address, namespace)
        subject = _required_identity_value(anonymous_id, "anonymous_id")
        subject_hash = hash_value(
            subject, scope=f"wallet-proof-subject:{tenant_id}"
        )
        identifier_hash = hash_wallet(address, namespace)
        if not subject_hash or not identifier_hash:
            raise ValueError("invalid wallet proof subject")

        now = utc_now()
        expires_at = (now + timedelta(seconds=_WALLET_CHALLENGE_TTL_SECONDS)).isoformat()
        challenge_id = f"wvc_{secrets.token_urlsafe(24)}"
        nonce = secrets.token_urlsafe(24)
        message = _wallet_proof_message(
            tenant_id=tenant_id,
            subject_hash=subject_hash,
            wallet_address=address,
            chain_namespace=namespace,
            challenge_id=challenge_id,
            nonce=nonce,
            issued_at=now.isoformat(),
            expires_at=expires_at,
        )
        context = {
            "wallet_chain_namespace": namespace,
            "wallet_subject_hash": subject_hash,
            "wallet_proof_nonce": nonce,
            "wallet_identity_namespace": str(identity_namespace or "").strip(),
        }
        if consent_snapshot:
            receipt_id = consent_snapshot.get("receipt_id") or consent_snapshot.get(
                "consent_receipt_id"
            )
            if receipt_id:
                context["consent_receipt_id"] = str(receipt_id)

        challenge = VerificationChallenge(
            id=challenge_id,
            tenant_id=tenant_id,
            identifier_type="wallet",
            identifier_hash=identifier_hash,
            method=VerificationMethod.WALLET_SIGNATURE.value,
            purpose="identity_verification",
            state=VerificationChallengeState.ISSUED.value,
            issued_at=now.isoformat(),
            expires_at=expires_at,
            max_attempts=_MAX_ATTEMPTS,
            source_context=context,
        )
        await self._challenges.create(challenge)
        self._metrics.record_verification_challenge(VerificationMethod.WALLET_SIGNATURE.value)
        return {
            "challenge_id": challenge_id,
            "wallet_address": address,
            "chain_namespace": namespace,
            "message": message,
            "expires_at": expires_at,
        }

    async def verify_wallet_signature(
        self,
        *,
        tenant_id: str,
        challenge_id: str,
        anonymous_id: str,
        wallet_address: str,
        chain_namespace: str,
        signature: str,
        identity_namespace: str = "",
        consent_snapshot: Optional[dict] = None,
    ) -> dict:
        """Consume a valid challenge and issue durable wallet proof evidence."""
        record = await self._challenges.get_for_tenant(tenant_id, challenge_id)
        if (
            record is None
            or record.get("identifier_type") != "wallet"
            or record.get("method") != VerificationMethod.WALLET_SIGNATURE.value
        ):
            self._metrics.record_verification_failure("not_found")
            return {"status": "not_found"}

        now = utc_now()
        expires_at = str(record.get("expires_at") or "")
        try:
            if not expires_at or now >= parse_iso(expires_at):
                await self._challenges.apply_update(
                    tenant_id, challenge_id,
                    {"state": VerificationChallengeState.EXPIRED.value},
                )
                self._metrics.record_verification_expired()
                return {"status": "expired"}
        except Exception:  # noqa: BLE001 - malformed expiry fails closed
            self._metrics.record_verification_failure("invalid_challenge")
            return {"status": "invalid"}

        if record.get("state") != VerificationChallengeState.ISSUED.value:
            return {"status": "invalid_state", "state": record.get("state")}

        context = record.get("source_context") or {}
        namespace = _wallet_proof_namespace(chain_namespace)
        address = _wallet_proof_address(wallet_address, namespace)
        subject_hash = hash_value(
            _required_identity_value(anonymous_id, "anonymous_id"),
            scope=f"wallet-proof-subject:{tenant_id}",
        )
        if (
            namespace != context.get("wallet_chain_namespace")
            or subject_hash != context.get("wallet_subject_hash")
            or str(identity_namespace or "").strip()
            != str(context.get("wallet_identity_namespace") or "").strip()
            or hash_wallet(address, namespace) != record.get("identifier_hash")
        ):
            updated = await self._challenges.record_failed_attempt(
                tenant_id, challenge_id
            )
            if updated and updated.get("state") == VerificationChallengeState.LOCKED.value:
                self._metrics.record_verification_failure("locked")
                return {"status": "locked"}
            if updated is None:
                current = await self._challenges.get_for_tenant(tenant_id, challenge_id)
                if current and current.get("state") == VerificationChallengeState.LOCKED.value:
                    return {"status": "locked"}
                if current and current.get("state") == VerificationChallengeState.CONSUMED.value:
                    return {"status": "already_consumed"}
            self._metrics.record_verification_failure("challenge_mismatch")
            return {"status": "invalid"}

        message = _wallet_proof_message(
            tenant_id=tenant_id,
            subject_hash=subject_hash,
            wallet_address=address,
            chain_namespace=namespace,
            challenge_id=challenge_id,
            nonce=str(context.get("wallet_proof_nonce") or ""),
            issued_at=str(record.get("issued_at") or ""),
            expires_at=expires_at,
        )
        if not _verify_wallet_message(namespace, address, message, signature):
            attempts = await self._challenges.record_failed_attempt(
                tenant_id, challenge_id
            )
            if attempts and attempts.get("state") == VerificationChallengeState.LOCKED.value:
                self._metrics.record_verification_failure("locked")
                return {"status": "locked"}
            self._metrics.record_verification_failure("invalid_signature")
            return {"status": "invalid"}

        # The verified request spends one attempt and transitions issued to
        # consumed atomically. There is no intermediate validated write that a
        # concurrent request could use to resurrect this challenge.
        consumed = await self._challenges.consume_wallet_atomic(
            tenant_id, challenge_id
        )
        if consumed is None:
            current = await self._challenges.get_for_tenant(tenant_id, challenge_id)
            if current and current.get("state") == VerificationChallengeState.LOCKED.value:
                self._metrics.record_verification_failure("locked")
                return {"status": "locked"}
            return {"status": "already_consumed"}

        evidence = await self._evidence.issue_evidence(
            tenant_id=tenant_id,
            identifier_type="wallet",
            identifier_hash=record["identifier_hash"],
            verification_method=VerificationMethod.WALLET_SIGNATURE.value,
            evidence_type=VerificationEvidenceType.WALLET_OWNERSHIP_VERIFIED.value,
            challenge_id=challenge_id,
            source_event_id=challenge_id,
            subject_hint_id=_required_identity_value(anonymous_id, "anonymous_id"),
            identity_namespace=str(
                context.get("wallet_identity_namespace") or ""
            ).strip(),
            proof_reference="server_verified_wallet_challenge",
            proof_digest=hashlib.sha256(signature.encode("utf-8")).hexdigest(),
            consent_snapshot=consent_snapshot,
            metadata={"chain_namespace": namespace},
        )
        self._metrics.record_verification_success(VerificationMethod.WALLET_SIGNATURE.value)
        return {"status": "verified", "evidence_id": evidence.id}


def _wallet_proof_namespace(value: str) -> str:
    namespace = str(value or "").strip().lower()
    if re.fullmatch(r"eip155:[1-9][0-9]*", namespace):
        return namespace
    if re.fullmatch(r"solana:[a-z0-9][a-z0-9._-]{0,63}", namespace):
        return namespace
    raise ValueError("unsupported wallet proof network")


def _wallet_proof_address(address: str, namespace: str) -> str:
    value = _required_identity_value(address, "wallet_address")
    family = namespace.split(":", 1)[0]
    if family == "eip155":
        from eth_utils import is_address, to_checksum_address

        if not is_address(value):
            raise ValueError("invalid wallet address")
        return to_checksum_address(value)
    decoded = _base58_decode(value)
    if len(decoded) != 32:
        raise ValueError("invalid wallet address")
    return _base58_encode(decoded)


def _wallet_proof_message(
    *,
    tenant_id: str,
    subject_hash: str,
    wallet_address: str,
    chain_namespace: str,
    challenge_id: str,
    nonce: str,
    issued_at: str,
    expires_at: str,
) -> str:
    return "\n".join((
        "Aether Wallet Ownership Proof",
        "Sign this message to prove control of the named wallet for identity linking.",
        "This does not authorize a payment or transaction.",
        f"Tenant: {tenant_id}",
        f"Identity subject: {subject_hash}",
        f"Wallet: {wallet_address}",
        f"Chain: {chain_namespace}",
        f"Challenge: {challenge_id}",
        f"Nonce: {nonce}",
        f"Issued At: {issued_at}",
        f"Expiration Time: {expires_at}",
    ))


def _verify_wallet_message(
    namespace: str, address: str, message: str, signature: str
) -> bool:
    if not signature or len(signature) > 1024:
        return False
    family = namespace.split(":", 1)[0]
    if family == "eip155":
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct
            from eth_utils import to_checksum_address

            recovered = Account.recover_message(
                encode_defunct(text=message), signature=signature
            )
            return to_checksum_address(recovered) == address
        except Exception:  # noqa: BLE001 - malformed signatures fail closed
            return False
    try:
        from nacl.signing import VerifyKey

        signature_bytes = base64.b64decode(signature, validate=True)
        if len(signature_bytes) != 64:
            return False
        VerifyKey(_base58_decode(address)).verify(
            message.encode("utf-8"), signature_bytes
        )
        return True
    except Exception:  # noqa: BLE001 - malformed signatures fail closed
        return False


def _base58_decode(value: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    lookup = {char: index for index, char in enumerate(alphabet)}
    number = 0
    for char in value:
        if char not in lookup:
            raise ValueError("invalid base58 value")
        number = number * 58 + lookup[char]
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\x00" * (len(value) - len(value.lstrip("1"))) + body


def _base58_encode(value: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    zero_count = len(value) - len(value.lstrip(b"\x00"))
    number = int.from_bytes(value, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    return "1" * zero_count + (encoded or ("" if zero_count else "1"))


def _required_identity_value(value: str, name: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 512 or any(ord(char) < 32 for char in result):
        raise ValueError(f"{name} must be a non-empty value of at most 512 characters")
    return result


__all__ = ["EmailVerificationService", "WalletVerificationService"]
