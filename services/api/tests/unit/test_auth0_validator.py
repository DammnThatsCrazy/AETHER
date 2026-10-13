"""Auth0 access-token validation against real RS256 tokens and a stubbed JWKS."""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from shared.auth import auth0_validator

DOMAIN = "tenant.example.auth0.com"
AUDIENCE = "https://api.aether.test"
ISSUER = f"https://{DOMAIN}/"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(kid: str) -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(_KEY.public_key()))
    jwk.update({"kid": kid, "kty": "RSA", "use": "sig", "alg": "RS256"})
    return jwk


def _token(kid: str = "k1", **overrides) -> str:
    now = int(time.time())
    claims = {"sub": "google-oauth2|123", "aud": AUDIENCE, "iss": ISSUER, "iat": now, "exp": now + 300}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def jwks(monkeypatch):
    """Serve the current JWKS through the real cache; record each fetch."""
    state = {"keys": [_jwk("k1")], "fetches": 0}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": state["keys"]}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            state["fetches"] += 1
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(auth0_validator, "_JWKS_CACHE", {})
    monkeypatch.setattr(
        auth0_validator,
        "settings",
        SimpleNamespace(
            auth0=SimpleNamespace(domain=DOMAIN, api_audience=AUDIENCE),
            env=SimpleNamespace(value="staging"),
        ),
    )
    return state


def _validate(token: str) -> dict:
    return asyncio.run(auth0_validator.validate_auth0_token(token))


def test_valid_token_is_accepted(jwks):
    assert _validate(_token())["sub"] == "google-oauth2|123"


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 600},
        {"aud": "https://other.example"},
        {"iss": "https://evil.example/"},
        {"iss": None},
    ],
    ids=["expired", "wrong-audience", "wrong-issuer", "missing-issuer"],
)
def test_rejected_token_raises_value_error(jwks, overrides):
    with pytest.raises(ValueError):
        _validate(_token(**overrides))


def test_small_clock_skew_is_tolerated(jwks):
    assert _validate(_token(iat=int(time.time()) + 5))["sub"]


def test_unknown_kid_refetches_rotated_keys_once(jwks):
    _validate(_token())
    jwks["keys"] = [_jwk("k2")]
    assert _validate(_token(kid="k2"))["sub"]
    assert jwks["fetches"] == 2

    with pytest.raises(ValueError):
        _validate(_token(kid="k3"))
    assert jwks["fetches"] == 3
