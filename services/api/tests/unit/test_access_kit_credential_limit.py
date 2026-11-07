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


async def test_middleware_helper_caps_only_attributed_access_kit_calls(monkeypatch):
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "2")
    context = SimpleNamespace(tenant_id="t", user_id="u")
    registry = SimpleNamespace(rate_limiter=SimpleNamespace(_redis=None))
    request = _request()
    assert await mw._access_credential_denial(request, context, "key-1", registry) is None
    assert await mw._access_credential_denial(request, context, "key-1", registry) is None
    denied = await mw._access_credential_denial(request, context, "key-1", registry)
    assert denied is not None and denied.limit == 2
    # Another credential, a non-Access-Kit caller, and an unlisted route are untouched.
    assert await mw._access_credential_denial(request, context, "key-2", registry) is None
    assert await mw._access_credential_denial(_request(surface=""), context, "key-1", registry) is None
    assert await mw._access_credential_denial(_request(route="/v1/other"), context, "key-1", registry) is None
    assert await mw._access_credential_denial(_request(surface="customer-supplied"), context, "key-1", registry) is None


async def test_frame_reads_are_capped_per_credential(monkeypatch):
    monkeypatch.setenv("AETHER_ACCESS_KIT_CREDENTIAL_RPM", "1")
    context = SimpleNamespace(tenant_id="t", user_id="u")
    registry = SimpleNamespace(rate_limiter=SimpleNamespace(_redis=None))
    request = _request(method="POST", route="/v1/experience360/frames")
    assert await mw._access_credential_denial(request, context, "k", registry) is None
    assert await mw._access_credential_denial(request, context, "k", registry) is not None


async def test_limiter_failure_never_blocks_a_read(monkeypatch):
    class Boom(AccessCredentialLimiter):
        async def check(self, *a, **k):
            raise RuntimeError("redis down")

    monkeypatch.setattr(mw, "_access_credential_limiter", Boom())
    context = SimpleNamespace(tenant_id="t", user_id="u")
    assert await mw._access_credential_denial(_request(), context, "k", SimpleNamespace()) is None
