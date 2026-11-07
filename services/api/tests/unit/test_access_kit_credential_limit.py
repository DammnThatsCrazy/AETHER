"""Per-credential, per-operation Access Kit cap, built on the existing burst limiter (W4)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from middleware import middleware as mw
from shared.rate_limit.limiter import BurstRateLimiter


def _request(surface="cli", method="GET", route="/v1/entities"):
    headers = [(b"x-aether-access-surface", surface.encode())] if surface else []
    request = Request({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "https", "path": route, "raw_path": route.encode(),
        "query_string": b"", "headers": headers, "server": ("t", 443), "client": ("1.1.1.1", 1),
    })
    request.state.access_route_template = route
    return request


def _bound(request, credential):
    request.state.validated_credential = credential
    return request


def _context(user="u", credential_class="legacy"):
    return SimpleNamespace(tenant_id="t", user_id=user, credential_class=credential_class)


def _registry():
    return SimpleNamespace(rate_limiter=BurstRateLimiter())


@pytest.fixture
def set_cap(monkeypatch):
    def apply(limit):
        monkeypatch.setattr(
            mw, "settings",
            SimpleNamespace(rate_limit=SimpleNamespace(access_kit_credential_rpm=limit)),
        )
    return apply


def test_default_cap_lives_in_the_existing_rate_limit_settings():
    from config.settings import RateLimitConfig

    assert RateLimitConfig().access_kit_credential_rpm == 120


async def test_scoped_check_caps_one_scope_and_leaves_others_alone():
    limiter = BurstRateLimiter()
    for _ in range(3):
        assert (await limiter.check_scoped("a", 3)).allowed
    blocked = await limiter.check_scoped("a", 3)
    assert blocked.allowed is False and blocked.retry_after >= 1
    assert (await limiter.check_scoped("b", 3)).allowed


async def test_scoped_check_with_zero_limit_is_disabled():
    limiter = BurstRateLimiter()
    for _ in range(50):
        assert (await limiter.check_scoped("a", 0)).allowed


async def test_scoped_check_uses_redis_when_present_and_falls_back_on_error():
    class Redis:
        def __init__(self, fail=False): self.fail, self.calls = fail, 0
        async def eval(self, script, numkeys, key, limit, ttl):
            self.calls += 1
            if self.fail:
                raise RuntimeError("down")
            return [0, 9]

    redis = Redis()
    limiter = BurstRateLimiter(redis_client=redis)
    limiter._mode = "redis"
    assert (await limiter.check_scoped("a", 5)).allowed is False and redis.calls == 1
    failing = BurstRateLimiter(redis_client=Redis(fail=True))
    assert (await failing.check_scoped("a", 5)).allowed is True  # memory fallback, not an outage


def test_credential_scope_is_stable_and_never_contains_the_secret():
    scope = BurstRateLimiter.credential_scope("t", "sk_live_secret", "", "entities.list")
    assert scope == BurstRateLimiter.credential_scope("t", "sk_live_secret", "", "entities.list")
    assert "secret" not in scope
    assert scope != BurstRateLimiter.credential_scope("t", "other", "", "entities.list")
    assert scope != BurstRateLimiter.credential_scope("t", "sk_live_secret", "", "entities.get")


async def test_cap_follows_the_authenticated_route_not_the_surface_label(set_cap):
    set_cap(2)
    for surface in ("cli", "", "customer-supplied"):
        registry, context = _registry(), _context()
        request = _bound(_request(surface=surface), "key-1")
        assert await mw._access_credential_denial(request, context, registry) is None
        assert await mw._access_credential_denial(request, context, registry) is None
        denied = await mw._access_credential_denial(request, context, registry)
        assert denied is not None and denied.limit == 2


async def test_cap_only_applies_to_named_access_kit_routes(set_cap):
    set_cap(1)
    registry, context = _registry(), _context()
    other = _bound(_request(route="/v1/other"), "key-1")
    for _ in range(3):
        assert await mw._access_credential_denial(other, context, registry) is None


async def test_a_different_validated_credential_has_its_own_bucket(set_cap):
    set_cap(1)
    registry, context = _registry(), _context()
    assert await mw._access_credential_denial(_bound(_request(), "key-1"), context, registry) is None
    assert await mw._access_credential_denial(_bound(_request(), "key-1"), context, registry) is not None
    assert await mw._access_credential_denial(_bound(_request(), "key-2"), context, registry) is None


async def test_rotating_unvalidated_headers_cannot_mint_new_buckets(set_cap):
    set_cap(2)
    registry, context = _registry(), _context(credential_class="human_session")
    results = []
    for index in range(5):
        request = _request()
        request.scope["headers"] = [(b"authorization", f"Bearer junk-{index}".encode())]
        request.state.validated_credential = "session-token"
        results.append(await mw._access_credential_denial(request, context, registry))
    assert [r is None for r in results] == [True, True, False, False, False]


async def test_missing_validated_credential_falls_back_to_the_principal_not_headers(set_cap):
    set_cap(1)
    registry, context = _registry(), _context()
    first, second = _request(), _request()
    first.scope["headers"] = [(b"authorization", b"Bearer a")]
    second.scope["headers"] = [(b"authorization", b"Bearer b")]
    assert await mw._access_credential_denial(first, context, registry) is None
    assert await mw._access_credential_denial(second, context, registry) is not None


async def test_frame_reads_are_capped_per_credential(set_cap):
    set_cap(1)
    registry, context = _registry(), _context()
    request = _bound(_request(method="POST", route="/v1/experience360/frames"), "k")
    assert await mw._access_credential_denial(request, context, registry) is None
    assert await mw._access_credential_denial(request, context, registry) is not None


async def test_cap_disabled_with_zero(set_cap):
    set_cap(0)
    registry, context = _registry(), _context()
    request = _bound(_request(), "k")
    for _ in range(20):
        assert await mw._access_credential_denial(request, context, registry) is None


async def test_limiter_failure_or_absence_never_blocks_a_read(set_cap):
    set_cap(1)

    class Boom:
        def credential_scope(self, *a): return "x"
        async def check_scoped(self, *a, **k): raise RuntimeError("redis down")

    request = _bound(_request(), "k")
    assert await mw._access_credential_denial(request, _context(), SimpleNamespace(rate_limiter=Boom())) is None
    assert await mw._access_credential_denial(request, _context(), SimpleNamespace()) is None


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
