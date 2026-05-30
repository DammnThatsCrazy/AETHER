"""Auth0 RS256 JWT validation.

Fetches JWKS from the Auth0 tenant and validates access tokens. Results are
cached in-process for 1 hour to avoid hammering the JWKS endpoint.

In AETHER_ENV=local with no AUTH0_DOMAIN set, validation is bypassed and a
stub TenantContext is returned so the flow can be exercised without real Auth0.
"""
from __future__ import annotations

import base64
import json
import struct
import time
from typing import Any, Optional

from config.settings import settings
from shared.logger.logger import get_logger

logger = get_logger("aether.auth.auth0")

_JWKS_CACHE: dict[str, Any] = {}      # {domain: {"keys": [...], "fetched_at": float}}
_JWKS_TTL = 3600


def _b64url_to_int(val: str) -> int:
    padding = 4 - len(val) % 4
    val += "=" * (padding % 4)
    data = base64.urlsafe_b64decode(val)
    return int.from_bytes(data, "big")


async def _fetch_jwks(domain: str) -> list[dict]:
    """Fetch JWKS from Auth0. Cached for 1 hour."""
    cached = _JWKS_CACHE.get(domain)
    if cached and time.time() - cached["fetched_at"] < _JWKS_TTL:
        return cached["keys"]
    import asyncio
    import requests as _requests
    url = f"https://{domain}/.well-known/jwks.json"
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(None, lambda: _requests.get(url, timeout=5))
    resp.raise_for_status()
    keys = resp.json().get("keys", [])
    _JWKS_CACHE[domain] = {"keys": keys, "fetched_at": time.time()}
    return keys


def _decode_claims(token: str) -> dict:
    """Decode JWT claims without signature verification (for header/kid)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Not a JWT")
    padding = 4 - len(parts[1]) % 4
    payload = base64.urlsafe_b64decode(parts[1] + "=" * (padding % 4))
    return json.loads(payload)


def _get_header(token: str) -> dict:
    parts = token.split(".")
    padding = 4 - len(parts[0]) % 4
    return json.loads(base64.urlsafe_b64decode(parts[0] + "=" * (padding % 4)))


async def validate_auth0_token(token: str) -> dict:
    """Validate an Auth0 access token. Returns verified claims dict.

    Raises ValueError with a descriptive message on any failure.
    In local mode without AUTH0_DOMAIN, returns unverified claims with a
    'local_mode' flag so the callback endpoint can exercise the flow.
    """
    domain = settings.auth0.domain
    audience = settings.auth0.api_audience

    if not domain:
        if settings.env.value == "local":
            # Permissive local mode: decode without verification
            try:
                claims = _decode_claims(token)
                claims["_local_mode"] = True
                return claims
            except Exception as e:
                raise ValueError(f"Cannot decode token: {e}")
        raise ValueError("AUTH0_DOMAIN not configured")

    # Fetch JWKS and find matching key
    try:
        jwks = await _fetch_jwks(domain)
    except Exception as e:
        raise ValueError(f"Failed to fetch Auth0 JWKS: {e}")

    header = _get_header(token)
    kid = header.get("kid")
    alg = header.get("alg", "RS256")

    matching = [k for k in jwks if k.get("kid") == kid and k.get("kty") == "RSA"]
    if not matching:
        raise ValueError(f"No matching JWKS key for kid={kid!r}")

    # Verify using PyJWT (prefers RS256 from cryptography package)
    try:
        import jwt as pyjwt  # type: ignore[import-not-found]
        from jwt.algorithms import RSAAlgorithm  # type: ignore[import-not-found]
        import json as _json
        public_key = RSAAlgorithm.from_jwk(_json.dumps(matching[0]))
        claims = pyjwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=audience,
            options={"require": ["exp", "iat", "sub"]},
        )
        return claims
    except ImportError:
        pass  # Fall through to manual check

    # PyJWT/cryptography is unavailable — refuse to accept tokens without
    # signature verification in non-local environments.
    import os as _os
    if _os.getenv("AETHER_ENV", "local").lower() != "local":
        raise RuntimeError(
            "Auth0 token signature verification is unavailable: PyJWT or "
            "cryptography package is not installed. Install production "
            "dependencies before starting in non-local environments."
        )
    logger.warning(
        "Auth0 token signature NOT cryptographically verified — "
        "PyJWT/cryptography unavailable. Acceptable in local mode only."
    )
    claims = _decode_claims(token)
    now = time.time()
    if claims.get("exp", 0) < now:
        raise ValueError("Token expired")
    if audience and claims.get("aud") != audience and audience not in (claims.get("aud") or []):
        raise ValueError(f"Token audience mismatch: {claims.get('aud')!r} != {audience!r}")
    expected_iss = f"https://{domain}/"
    if claims.get("iss") != expected_iss:
        raise ValueError(f"Token issuer mismatch: {claims.get('iss')!r}")
    claims["_sig_unverified"] = True
    return claims
