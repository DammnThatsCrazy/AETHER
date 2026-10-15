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
_CLOCK_SKEW_LEEWAY = 60  # seconds of drift tolerated between this host and Auth0
# The callback is public: without a floor, any forged kid forces a JWKS fetch.
_JWKS_REFRESH_MIN_AGE = 60


class McpOAuthScopeError(ValueError):
    """A valid delegated token lacks the MCP read scope."""


def _b64url_to_int(val: str) -> int:
    padding = 4 - len(val) % 4
    val += "=" * (padding % 4)
    data = base64.urlsafe_b64decode(val)
    return int.from_bytes(data, "big")


async def _fetch_jwks(domain: str, refresh: bool = False) -> list[dict]:
    """Fetch JWKS from Auth0. Cached for 1 hour unless ``refresh`` is set."""
    cached = _JWKS_CACHE.get(domain)
    if cached and not refresh and time.time() - cached["fetched_at"] < _JWKS_TTL:
        return cached["keys"]
    import httpx

    url = f"https://{domain}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url)
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
    header = json.loads(base64.urlsafe_b64decode(parts[0] + "=" * (padding % 4)))
    if not isinstance(header, dict):
        raise ValueError("Malformed token header")
    return header


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
    cached = _JWKS_CACHE.get(domain)
    if not matching and (not cached or time.time() - cached["fetched_at"] >= _JWKS_REFRESH_MIN_AGE):
        # Auth0 rotated its signing key since the cached fetch.
        try:
            jwks = await _fetch_jwks(domain, refresh=True)
        except Exception as e:
            raise ValueError(f"Failed to fetch Auth0 JWKS: {e}")
        matching = [k for k in jwks if k.get("kid") == kid and k.get("kty") == "RSA"]
    if not matching:
        raise ValueError(f"No matching JWKS key for kid={kid!r}")

    # Verify using PyJWT (prefers RS256 from cryptography package)
    try:
        import jwt as pyjwt  # type: ignore[import-not-found]
        from jwt.algorithms import RSAAlgorithm  # type: ignore[import-not-found]
    except ImportError:
        pyjwt = None  # Fall through to manual check

    if pyjwt is not None:
        try:
            public_key = RSAAlgorithm.from_jwk(json.dumps(matching[0]))
            return pyjwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=audience,
                issuer=f"https://{domain}/",
                leeway=_CLOCK_SKEW_LEEWAY,
                options={"require": ["exp", "iat", "sub", "iss"]},
            )
        except pyjwt.PyJWTError as e:
            raise ValueError(f"Token rejected: {e}")

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


async def validate_mcp_oauth_token(token: str) -> dict:
    """Validate a delegated MCP access token for the exact MCP resource.

    Unlike the legacy SSO exchange this never accepts an unsigned/local token
    and never accepts a token minted for the general Aether API audience.
    """
    domain = settings.auth0.domain
    audience = settings.auth0.mcp_audience
    if not domain or not audience or not audience.startswith("https://"):
        raise ValueError("MCP OAuth is not configured")
    if len(token) > 8192:
        raise ValueError("MCP OAuth token is too large")
    try:
        import jwt as pyjwt  # type: ignore[import-not-found]
        from jwt.algorithms import RSAAlgorithm  # type: ignore[import-not-found]

        header = pyjwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError("MCP OAuth token algorithm is invalid")
        matching = [key for key in await _fetch_jwks(domain)
                    if key.get("kid") == header["kid"] and key.get("kty") == "RSA"]
        if len(matching) != 1:
            raise ValueError("MCP OAuth signing key is unknown")
        public_key = RSAAlgorithm.from_jwk(json.dumps(matching[0]))
        claims = pyjwt.decode(
            token, public_key, algorithms=["RS256"], audience=audience,
            issuer=f"https://{domain}/",
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except ImportError as exc:
        raise ValueError("MCP OAuth signature verification is unavailable") from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("MCP OAuth token validation failed") from exc
    scopes = claims.get("scope", "")
    if not isinstance(scopes, str) or "access_kit:read" not in scopes.split():
        raise McpOAuthScopeError("MCP OAuth read scope is missing")
    return claims


async def fetch_auth0_userinfo(token: str) -> dict:
    """Return the verified OIDC profile for an already-validated access token.

    The browser sends an access token for the Aether API audience; with the
    ``openid profile email`` scope Auth0 also grants it the ``/userinfo``
    audience, but the token itself carries no ``email``/``email_verified``
    claims. Call only after :func:`validate_auth0_token` accepted the token.
    Raises ValueError when Auth0 is not configured or the call fails.
    """
    domain = settings.auth0.domain
    if not domain:
        raise ValueError("AUTH0_DOMAIN not configured")
    # httpx is a declared dependency of the backend extra (requests is not).
    import httpx

    url = f"https://{domain}/userinfo"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        profile = resp.json()
    except Exception as e:  # noqa: BLE001 — surfaced as a sign-in failure
        raise ValueError(f"Failed to fetch Auth0 userinfo: {type(e).__name__}")
    if not isinstance(profile, dict):
        raise ValueError("Auth0 userinfo returned an unexpected payload")
    return profile
