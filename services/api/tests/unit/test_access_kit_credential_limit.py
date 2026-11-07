"""Per-credential, per-capability Access Kit cap (W4)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from middleware import middleware as mw
from shared.rate_limit.access_capability_limit import (
    DEFAULT_LIMIT_RPM,
    AccessCredentialLimiter,
    configured_limit,
    credential_fingerprint,
)


def _request(surface="cli", method="GET", route="/v1/entities"):
    headers = [(b"x-aether-access-surface", surface.encode())] if surface else []
    request = Request({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "https", "path": route, "raw_path": route.encode(),
        "query_string": b"", "headers": headers, "server": ("t", 443), "client": ("1.1.1.1", 1),
    })
    request.state.access_route_template = route
    return request


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(mw, "_access_credential_limiter", None)
    monkeypatch.delenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", raising=False)


def test_limit_default_override_and_disable(monkeypatch):
    assert configured_limit() == DEFAULT_LIMIT_RPM
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "5")
    assert configured_limit() == 5
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "0")
    assert configured_limit() == 0
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "junk")
    assert configured_limit() == DEFAULT_LIMIT_RPM


async def test_one_credential_is_capped_without_affecting_another():
    limiter = AccessCredentialLimiter()
    for _ in range(3):
        assert (await limiter.check("t", "cred-a", "entities.list", limit=3)).allowed
    blocked = await limiter.check("t", "cred-a", "entities.list", limit=3)
    assert blocked.allowed is False and blocked.retry_after >= 1
    assert (await limiter.check("t", "cred-b", "entities.list", limit=3)).allowed
    assert (await limiter.check("t", "cred-a", "entities.get", limit=3)).allowed


async def test_zero_limit_disables_the_cap():
    limiter = AccessCredentialLimiter()
    for _ in range(50):
        assert (await limiter.check("t", "cred-a", "entities.list", limit=0)).allowed


def test_fingerprint_is_stable_and_not_the_secret():
    fingerprint = credential_fingerprint("sk_live_secret")
    assert fingerprint == credential_fingerprint("sk_live_secret")
    assert "secret" not in fingerprint and len(fingerprint) == 16
    assert credential_fingerprint("", "user-1") == credential_fingerprint("user-1")
    assert credential_fingerprint("") == ""


def _bound(request, credential):
    request.state.validated_credential = credential
    return request


async def test_cap_follows_the_authenticated_route_not_the_surface_label(monkeypatch):
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "2")
    context = SimpleNamespace(tenant_id="t", user_id="u", credential_class="legacy")
    registry = SimpleNamespace(rate_limiter=SimpleNamespace(_redis=None))
    # No surface header, and a made-up one, are capped exactly like a real one.
    for surface in ("cli", "", "customer-supplied"):
        monkeypatch.setattr(mw, "_access_credential_limiter", None)
        request = _bound(_request(surface=surface), "key-1")
        assert await mw._access_credential_denial(request, context, registry) is None
        assert await mw._access_credential_denial(request, context, registry) is None
        denied = await mw._access_credential_denial(request, context, registry)
        assert denied is not None and denied.limit == 2


async def test_cap_only_applies_to_named_access_kit_routes(monkeypatch):
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "1")
    context = SimpleNamespace(tenant_id="t", user_id="u", credential_class="legacy")
    registry = SimpleNamespace(rate_limiter=SimpleNamespace(_redis=None))
    other = _bound(_request(route="/v1/other"), "key-1")
    for _ in range(3):
        assert await mw._access_credential_denial(other, context, registry) is None


async def test_a_different_validated_credential_has_its_own_bucket(monkeypatch):
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "1")
    context = SimpleNamespace(tenant_id="t", user_id="u", credential_class="legacy")
    registry = SimpleNamespace(rate_limiter=SimpleNamespace(_redis=None))
    assert await mw._access_credential_denial(_bound(_request(), "key-1"), context, registry) is None
    assert await mw._access_credential_denial(_bound(_request(), "key-1"), context, registry) is not None
    assert await mw._access_credential_denial(_bound(_request(), "key-2"), context, registry) is None


async def test_rotating_unvalidated_headers_cannot_mint_new_buckets(monkeypatch):
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "2")
    context = SimpleNamespace(tenant_id="t", user_id="u", credential_class="human_session")
    registry = SimpleNamespace(rate_limiter=SimpleNamespace(_redis=None))
    results = []
    for index in range(5):
        # Same authenticated session; the client varies Authorization/X-API-Key text.
        request = _request()
        request.scope["headers"] = [
            (b"authorization", f"Bearer junk-{index}".encode()),
            (b"x-api-key-ignored", f"junk-{index}".encode()),
        ]
        request.state.validated_credential = "session-token"
        results.append(await mw._access_credential_denial(request, context, registry))
    assert [r is None for r in results] == [True, True, False, False, False]


async def test_missing_validated_credential_falls_back_to_the_principal_not_headers(monkeypatch):
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "1")
    context = SimpleNamespace(tenant_id="t", user_id="u", credential_class="legacy")
    registry = SimpleNamespace(rate_limiter=SimpleNamespace(_redis=None))
    first, second = _request(), _request()
    first.scope["headers"] = [(b"authorization", b"Bearer a")]
    second.scope["headers"] = [(b"authorization", b"Bearer b")]
    assert await mw._access_credential_denial(first, context, registry) is None
    assert await mw._access_credential_denial(second, context, registry) is not None


async def test_frame_reads_are_capped_per_credential(monkeypatch):
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "1")
    context = SimpleNamespace(tenant_id="t", user_id="u", credential_class="legacy")
    registry = SimpleNamespace(rate_limiter=SimpleNamespace(_redis=None))
    request = _bound(_request(method="POST", route="/v1/experience360/frames"), "k")
    assert await mw._access_credential_denial(request, context, registry) is None
    assert await mw._access_credential_denial(request, context, registry) is not None


async def test_limiter_failure_never_blocks_a_read(monkeypatch):
    class Boom(AccessCredentialLimiter):
        async def check(self, *a, **k):
            raise RuntimeError("redis down")

    monkeypatch.setattr(mw, "_access_credential_limiter", Boom())
    context = SimpleNamespace(tenant_id="t", user_id="u", credential_class="legacy")
    assert await mw._access_credential_denial(_bound(_request(), "k"), context, SimpleNamespace()) is None


class _Validator:
    def __init__(self, valid): self.valid = valid
    async def validate_async(self, key):
        if key not in self.valid:
            raise RuntimeError("invalid")
        return SimpleNamespace(tenant_id="t", user_id=None, credential_class="legacy")


async def test_authenticator_records_the_credential_it_validated():
    request = _request()
    request.scope["headers"] = [(b"x-api-key", b"good-key"), (b"authorization", b"Bearer junk")]
    await mw._authenticate_async(request, None, _Validator({"good-key"}))
    assert request.state.validated_credential == "good-key"

    bearer = _request()
    bearer.scope["headers"] = [(b"authorization", b"Bearer good-token")]
    await mw._authenticate_async(bearer, None, _Validator({"good-token"}))
    assert bearer.state.validated_credential == "good-token"
