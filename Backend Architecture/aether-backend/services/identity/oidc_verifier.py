"""Server-side OIDC/SSO ID-token verification (identity assurance layer).

Performs REAL cryptographic verification of a provider ID token before any
trust decision is made. It mirrors the JWKS + PyJWT RS256 pattern used by
:mod:`shared.auth.auth0_validator`:

* the signing key set is discovered from the token's own ``iss`` claim
  (``{iss}/.well-known/openid-configuration`` ``jwks_uri`` when advertised,
  else ``{iss}/.well-known/jwks.json``),
* the RS256 signature is verified with the matching JWKS key via PyJWT,
* ``iss`` (allowlist), ``aud``, ``exp`` and — when supplied — ``nonce`` are
  enforced.

Security invariants:
* The issuer allowlist is enforced BEFORE any network fetch, so a JWKS document
  is never fetched from a non-allowlisted issuer.
* A client-provided ``email_verified`` is only ever trusted when it rides inside
  a token that passed verification here.
* LOCAL fallback: when PyJWT/cryptography is unavailable OR the JWKS cannot be
  fetched AND ``AETHER_ENV=local``, the token is decoded WITHOUT signature
  verification but ``iss``/``aud``/``exp``/``nonce`` are still enforced and the
  returned claims are stamped ``_sig_unverified=True``. In any non-local
  environment an unverifiable signature is fatal (raises).
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.service.identity.oidc_verifier")

# JWKS cache keyed by issuer: {issuer: {"keys": [...], "fetched_at": float}}.
_JWKS_CACHE: dict[str, Any] = {}
_JWKS_TTL = 3600


class OIDCVerificationError(ValueError):
    """Raised when an OIDC ID token fails verification.

    Subclasses :class:`ValueError` (callers may catch either) and carries a
    machine-readable ``reason`` so the caller can map it to a shaped failure
    response. Reasons: ``malformed``, ``untrusted_issuer``, ``invalid_audience``,
    ``expired``, ``invalid_nonce``, ``signature_unverifiable``.
    """

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _b64url_json(segment: str) -> dict:
    padding = 4 - len(segment) % 4
    raw = base64.urlsafe_b64decode(segment + "=" * (padding % 4))
    return json.loads(raw)


def _decode_claims(token: str) -> dict:
    """Decode JWT claims WITHOUT signature verification (for iss/kid/fallback)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT (expected 3 dot-separated segments)")
    return _b64url_json(parts[1])


def _get_header(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 1:
        raise ValueError("not a JWT")
    return _b64url_json(parts[0])


async def _fetch_jwks(issuer: str) -> list[dict]:
    """Discover and fetch the JWKS for ``issuer``. Cached for 1 hour.

    Best-effort OIDC discovery: try the issuer's ``openid-configuration`` for a
    ``jwks_uri``; fall back to ``{iss}/.well-known/jwks.json``. Trailing slashes
    on the issuer are trimmed. Tests monkeypatch this function to avoid network.
    """
    cached = _JWKS_CACHE.get(issuer)
    if cached and time.time() - cached["fetched_at"] < _JWKS_TTL:
        return cached["keys"]

    import asyncio
    import requests as _requests

    base = issuer.rstrip("/")
    jwks_url = f"{base}/.well-known/jwks.json"
    loop = asyncio.get_event_loop()

    # Best-effort discovery of jwks_uri from the OIDC configuration document.
    try:
        cfg_url = f"{base}/.well-known/openid-configuration"
        cfg_resp = await loop.run_in_executor(
            None, lambda: _requests.get(cfg_url, timeout=5)
        )
        cfg_resp.raise_for_status()
        discovered = cfg_resp.json().get("jwks_uri")
        if discovered:
            jwks_url = discovered
    except Exception:  # noqa: BLE001 - discovery is optional; fall back to default
        pass

    resp = await loop.run_in_executor(None, lambda: _requests.get(jwks_url, timeout=5))
    resp.raise_for_status()
    keys = resp.json().get("keys", [])
    _JWKS_CACHE[issuer] = {"keys": keys, "fetched_at": time.time()}
    return keys


async def _resolve_verifying_key(id_token: str, issuer: str) -> Optional[Any]:
    """Return an RS256 public key for the token, or ``None`` when unavailable.

    ``None`` means the signature cannot be cryptographically verified here —
    PyJWT/cryptography is not installed, or the JWKS could not be fetched, or no
    matching RSA key was found. The caller decides how to treat that per-env.
    """
    try:
        from jwt.algorithms import RSAAlgorithm  # type: ignore[import-not-found]
    except ImportError:
        return None

    try:
        keys = await _fetch_jwks(issuer)
    except Exception as exc:  # noqa: BLE001 - unreachable JWKS -> no key
        logger.warning("OIDC JWKS fetch failed for issuer=%s: %s", issuer, exc)
        return None

    try:
        header = _get_header(id_token)
    except Exception:  # noqa: BLE001
        return None
    kid = header.get("kid")

    matching = [k for k in keys if k.get("kid") == kid and k.get("kty") == "RSA"]
    if not matching:
        matching = [k for k in keys if k.get("kty") == "RSA"]
    if not matching:
        return None
    try:
        return RSAAlgorithm.from_jwk(json.dumps(matching[0]))
    except Exception as exc:  # noqa: BLE001 - malformed JWK
        logger.warning("OIDC JWK parse failed for issuer=%s: %s", issuer, exc)
        return None


def _enforce_expiry(claims: dict) -> None:
    exp = claims.get("exp")
    if exp is None:
        raise OIDCVerificationError("expired", "token missing exp")
    try:
        exp_ts = float(exp)
    except (TypeError, ValueError):
        raise OIDCVerificationError("expired", "token exp is not a timestamp")
    if exp_ts < time.time():
        raise OIDCVerificationError("expired", "token expired")


def _enforce_audience(claims: dict, expected_audience: str) -> None:
    aud = claims.get("aud")
    aud_values = aud if isinstance(aud, (list, tuple, set)) else [aud]
    if expected_audience not in aud_values:
        raise OIDCVerificationError("invalid_audience", "audience mismatch")


async def verify_oidc_id_token(
    *,
    id_token: str,
    issuer_allowlist: list[str],
    expected_audience: str,
    expected_nonce: Optional[str] = None,
) -> dict:
    """Verify a raw OIDC/SSO ID token and return its verified claims.

    Raises :class:`OIDCVerificationError` (a ``ValueError``) on any failure.
    """
    if not id_token or not isinstance(id_token, str):
        raise OIDCVerificationError("malformed", "empty id_token")
    try:
        unverified = _decode_claims(id_token)
    except Exception as exc:  # noqa: BLE001
        raise OIDCVerificationError("malformed", f"cannot decode id_token: {exc}")

    issuer = unverified.get("iss")
    # Enforce the issuer allowlist BEFORE any network fetch — a JWKS document
    # must never be fetched from a non-allowlisted (attacker-chosen) issuer.
    if not issuer or issuer not in issuer_allowlist:
        raise OIDCVerificationError("untrusted_issuer", "issuer not in allowlist")

    key = await _resolve_verifying_key(id_token, issuer)
    if key is not None:
        import jwt as pyjwt  # type: ignore[import-not-found]

        try:
            claims = pyjwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=expected_audience,
                options={"require": ["exp", "iat", "iss"]},
            )
        except pyjwt.ExpiredSignatureError:
            raise OIDCVerificationError("expired", "token expired")
        except pyjwt.InvalidAudienceError:
            raise OIDCVerificationError("invalid_audience", "audience mismatch")
        except pyjwt.InvalidIssuerError:
            raise OIDCVerificationError("untrusted_issuer", "issuer mismatch")
        except Exception as exc:  # noqa: BLE001 - bad signature / malformed token
            raise OIDCVerificationError(
                "signature_unverifiable", f"jwt decode failed: {exc}"
            )
    else:
        # No verifying key: PyJWT/cryptography missing or JWKS unreachable.
        if not _is_local_env():
            raise OIDCVerificationError(
                "signature_unverifiable",
                "cannot verify token signature outside local env",
            )
        logger.warning(
            "OIDC token signature NOT cryptographically verified for issuer=%s "
            "— acceptable in local mode only.",
            issuer,
        )
        claims = _decode_claims(id_token)
        _enforce_expiry(claims)
        _enforce_audience(claims, expected_audience)
        claims["_sig_unverified"] = True

    # Uniform post-checks. The signature path already enforced aud/exp via PyJWT;
    # re-checking here keeps both paths identical and covers the local fallback.
    if claims.get("iss") not in issuer_allowlist:
        raise OIDCVerificationError("untrusted_issuer", "issuer not in allowlist")
    _enforce_audience(claims, expected_audience)
    if expected_nonce is not None and claims.get("nonce") != expected_nonce:
        raise OIDCVerificationError("invalid_nonce", "nonce mismatch")

    return claims


__all__ = ["verify_oidc_id_token", "OIDCVerificationError"]
