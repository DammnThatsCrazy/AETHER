"""Signed, expiring, capability-bound OAuth authorization state.

The ``state`` parameter is the CSRF and flow-integrity anchor of an OAuth
authorization-code round trip: the value handed to the provider on the authorize
call must come back unchanged on the callback, and nothing else may forge it.

This module issues an opaque, URL-safe token of the form::

    base64url(payload_json) + "." + base64url(hmac_sha256(payload))

The payload binds the flow to a tenant, a *single* provider capability
(:class:`ProviderIdentity`), and the redirect URI, and carries an issue time, an
expiry, and a random nonce. :func:`verify_state` recomputes the HMAC in constant
time and rejects tamper or expiry with a typed :class:`OAuthStateError`; it never
trusts a value it did not sign.

The signing key is *derived* from an existing application secret
(``settings.auth.jwt_secret``) via HMAC with a fixed context label — this module
reads settings but never mutates them, and the derived key is never the JWT
secret itself.

Replay prevention is layered on top via :class:`SingleUseNonceStore`. The default
:class:`InMemoryNonceStore` is process-local and therefore correct only for a
single process; a durable (Redis/DB) implementation of the same protocol is the
sanctioned follow-up for multi-replica deployments.

All time handling uses epoch integers to stay clear of naive-datetime debt;
:func:`expires_at_utc` is the single seam that materializes an aware datetime,
via :func:`shared.temporal.instant.ensure_aware_utc`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

from shared.integration_contracts.identity import (
    IdentityError,
    ProviderIdentity,
    parse_identity,
)
from shared.temporal.instant import ensure_aware_utc

_STATE_VERSION = "v1"
#: Context label for HKDF-style key separation; changing it rotates every token.
_SIGNING_INFO = b"aether.integrations.oauth.state.v1"
DEFAULT_TTL_SECONDS = 600
_NONCE_BYTES = 24


class OAuthStateError(Exception):
    """A fail-closed rejection of an OAuth state token.

    ``reason`` is a stable, non-disclosing code (e.g. ``state_signature_invalid``,
    ``state_expired``, ``state_replayed``) so callers classify without parsing
    messages.
    """

    def __init__(self, reason: str, message: Optional[str] = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


@runtime_checkable
class SingleUseNonceStore(Protocol):
    """Marks flow nonces as consumed to make an authorization state single-use."""

    def consume(self, nonce: str) -> bool:
        """Consume ``nonce``.

        Return ``True`` when it was previously unseen (first, legitimate use) and
        ``False`` when it has already been consumed (a replay) or is empty.
        """
        ...


class InMemoryNonceStore:
    """Process-local single-use nonce store.

    Correct for a single process only. Durable, cross-replica replay prevention
    (Redis/DB) is a follow-up implementing the same :class:`SingleUseNonceStore`
    protocol.
    """

    def __init__(self) -> None:
        self._used: set[str] = set()

    def consume(self, nonce: str) -> bool:
        if not nonce or nonce in self._used:
            return False
        self._used.add(nonce)
        return True

    def clear(self) -> None:
        self._used.clear()

    def __len__(self) -> int:
        return len(self._used)


@dataclass(frozen=True)
class OAuthState:
    """The verified contents of an OAuth state token. Carries no secret."""

    tenant_id: str
    identity: ProviderIdentity
    redirect_uri: str
    issued_at: int
    expires_at: int
    nonce: str
    extra: dict[str, Any] = field(default_factory=dict)

    def expires_at_utc(self) -> datetime:
        """The expiry as an aware UTC datetime (the only datetime seam here)."""
        return ensure_aware_utc(
            datetime.fromtimestamp(self.expires_at, tz=timezone.utc)
        )


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _signing_key() -> bytes:
    """Derive the state-signing key from an existing app secret (read-only).

    The JWT secret is never used directly: HMAC over a fixed context label gives
    domain separation, so a leaked state signature cannot be replayed against the
    JWT path and vice versa.
    """
    from config.settings import get_settings

    secret = (get_settings().auth.jwt_secret or "").encode("utf-8")
    return hmac.new(secret, _SIGNING_INFO, hashlib.sha256).digest()


def _sign(encoded_payload: str) -> str:
    mac = hmac.new(_signing_key(), encoded_payload.encode("ascii"), hashlib.sha256)
    return _b64url_encode(mac.digest())


def issue_state(
    tenant_id: str,
    identity: ProviderIdentity,
    redirect_uri: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    """Issue a signed, expiring, capability-bound state token.

    The returned token is opaque and URL-safe. It embeds the tenant, the provider
    capability (as its canonical ``family.product.capability`` key), the redirect
    URI, issue/expiry epochs, and a random nonce. It is signed but *not*
    encrypted — never place a secret in ``extra``.
    """
    if not tenant_id:
        raise OAuthStateError("tenant_missing", "tenant_id is required")
    if not redirect_uri:
        raise OAuthStateError("redirect_uri_missing", "redirect_uri is required")
    if not isinstance(identity, ProviderIdentity):
        raise OAuthStateError("identity_invalid", "identity must be a ProviderIdentity")
    if ttl_seconds <= 0:
        raise OAuthStateError("ttl_invalid", "ttl_seconds must be positive")

    now = int(time.time())
    payload: dict[str, Any] = {
        "v": _STATE_VERSION,
        "tid": tenant_id,
        "idk": identity.key,
        "ruri": redirect_uri,
        "iat": now,
        "exp": now + int(ttl_seconds),
        "nonce": secrets.token_urlsafe(_NONCE_BYTES),
    }
    if extra:
        payload["extra"] = extra
    encoded = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{encoded}.{_sign(encoded)}"


def verify_state(
    token: str,
    *,
    now: Optional[int] = None,
    nonce_store: Optional[SingleUseNonceStore] = None,
) -> OAuthState:
    """Verify a state token's signature and expiry, returning its contents.

    Verification is fail-closed: a malformed token, a bad signature, an expired
    window, an unparseable identity, or (when ``nonce_store`` is supplied) a
    replayed nonce each raise :class:`OAuthStateError` with a distinct reason.

    ``now`` overrides the clock (epoch seconds) for testing. ``nonce_store``, when
    given, consumes the nonce to enforce single use — pass the same store to both
    the issuing broker instance and the callback so a replay is detected.
    """
    if not isinstance(token, str) or token.count(".") != 1:
        raise OAuthStateError("state_malformed", "state token is malformed")
    encoded, signature = token.split(".", 1)
    expected = _sign(encoded)
    if not hmac.compare_digest(expected, signature):
        raise OAuthStateError("state_signature_invalid", "state signature mismatch")

    try:
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise OAuthStateError("state_malformed", "state payload undecodable") from exc
    if not isinstance(payload, dict) or payload.get("v") != _STATE_VERSION:
        raise OAuthStateError("state_version_unsupported", "unsupported state version")

    try:
        expires_at = int(payload["exp"])
        issued_at = int(payload["iat"])
        tenant_id = str(payload["tid"])
        redirect_uri = str(payload["ruri"])
        nonce = str(payload["nonce"])
        identity_key = str(payload["idk"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OAuthStateError("state_malformed", "state payload incomplete") from exc

    reference = now if now is not None else int(time.time())
    if reference >= expires_at:
        raise OAuthStateError("state_expired", "state token has expired")

    try:
        identity = parse_identity(identity_key)
    except IdentityError as exc:
        raise OAuthStateError("state_identity_invalid", str(exc)) from exc

    if nonce_store is not None and not nonce_store.consume(nonce):
        raise OAuthStateError("state_replayed", "state nonce already consumed")

    extra = payload.get("extra")
    return OAuthState(
        tenant_id=tenant_id,
        identity=identity,
        redirect_uri=redirect_uri,
        issued_at=issued_at,
        expires_at=expires_at,
        nonce=nonce,
        extra=extra if isinstance(extra, dict) else {},
    )


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "InMemoryNonceStore",
    "OAuthState",
    "OAuthStateError",
    "SingleUseNonceStore",
    "issue_state",
    "verify_state",
]
