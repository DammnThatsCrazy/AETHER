"""Throttles on the unauthenticated email/password endpoints.

The counter is tested with a fake clock and a fake shared cache; the endpoints are
tested by calling the handlers with a fake request, the way
``tests/unit/test_trust_containment.py`` does.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.common.common import BadRequestError, RateLimitedError  # noqa: E402
from shared.rate_limit import auth_throttle as at  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class FakeCache:
    """The shared CacheClient surface the counters use (set_nx/get/incr_by/delete)."""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def set_nx(self, key, value, ttl=0):
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=0):
        self.values[key] = value

    async def incr_by(self, key, amount, ttl=0):
        self.values[key] = int(self.values.get(key, 0)) + amount
        return self.values[key]

    async def delete(self, key):
        self.values.pop(key, None)

    def counts(self):
        return {k: v for k, v in self.values.items() if not k.endswith(":window")}


class BrokenCache:
    async def set_nx(self, *args, **kwargs):
        raise ConnectionError("cache down")

    get = delete = incr_by = set_nx


# ── the counter ──────────────────────────────────────────────────────────


def test_a_window_opens_at_the_first_event_and_closes_after_its_length():
    clock = Clock()
    counter = at.AttemptCounter("t", 60, clock=clock)
    assert _run(counter.hit("k")) == (1, 60)
    clock.now += 20
    assert _run(counter.hit("k")) == (2, 40)
    clock.now += 41
    assert _run(counter.hit("k")) == (1, 60)  # a fresh window


def test_clear_forgets_the_count():
    counter = at.AttemptCounter("t", 60, clock=Clock())
    _run(counter.hit("k"))
    _run(counter.clear("k"))
    assert _run(counter.hit("k")) == (1, 60)


def test_memory_fallback_is_bounded_and_drops_the_window_closing_soonest():
    clock = Clock()
    counter = at.AttemptCounter("t", 60, clock=clock)
    counter._MAX_MEMORY_KEYS = 3
    for i in range(3):
        clock.now += 1
        _run(counter.hit(f"k{i}"))
    _run(counter.hit("k3"))
    assert len(counter._memory) == 3
    assert "k0" not in counter._memory and "k3" in counter._memory


def test_the_shared_cache_counts_and_clears():
    cache = FakeCache()
    counter = at.AttemptCounter("t", 900, clock=Clock())
    assert _run(counter.hit("k", cache)) == (1, 900)
    assert _run(counter.hit("k", cache))[0] == 2
    _run(counter.clear("k", cache))
    assert not cache.values
    assert _run(counter.hit("k", cache)) == (1, 900)


def test_the_shared_window_closes_after_its_length_and_starts_a_fresh_count():
    clock, cache = Clock(), FakeCache()
    counter = at.AttemptCounter("t", 60, clock=clock)
    assert _run(counter.hit("k", cache)) == (1, 60)
    clock.now += 20
    assert _run(counter.hit("k", cache)) == (2, 40)
    # The cache expires the window key at its TTL; a new window means a new counter key.
    cache.values.pop("auththrottle:t:k:window")
    clock.now += 41
    assert _run(counter.hit("k", cache)) == (1, 60)


def test_two_processes_share_one_budget():
    """Separate counters (one per process) count against the same shared cache."""
    cache = FakeCache()
    first, second = at.AttemptCounter("t", 900, clock=Clock()), at.AttemptCounter("t", 900, clock=Clock())
    for _ in range(3):
        _run(first.hit("k", cache))
    assert _run(second.hit("k", cache))[0] == 4


def test_a_cache_outage_falls_back_to_the_local_window():
    counter = at.AttemptCounter("t", 60, clock=Clock())
    assert _run(counter.hit("k", BrokenCache()))[0] == 1
    assert _run(counter.hit("k", BrokenCache()))[0] == 2


# ── the limits ───────────────────────────────────────────────────────────


def test_a_rate_refuses_the_request_after_the_limit_with_a_retry_hint():
    counter = at.AttemptCounter("t", 60, clock=Clock())
    for _ in range(3):
        _run(at.enforce_rate(counter, "ip", 3))
    with pytest.raises(RateLimitedError) as caught:
        _run(at.enforce_rate(counter, "ip", 3))
    assert caught.value.details["retry_after_seconds"] == 60
    assert caught.value.details["limiter"] == "t"  # the kind of limit that refused the request
    _run(at.enforce_rate(counter, "other-ip", 3))


def test_parallel_attempts_cannot_all_slip_under_the_cap():
    # Each attempt is one atomic increment, so six simultaneous attempts against a
    # cap of five admit exactly five, however they interleave.
    counter = at.AttemptCounter("t", 900, clock=Clock())

    async def burst():
        results = await asyncio.gather(
            *[at.enforce_rate(counter, "e", 5) for _ in range(6)], return_exceptions=True
        )
        return [isinstance(r, RateLimitedError) for r in results]

    refused = _run(burst())
    assert refused.count(True) == 1 and refused.count(False) == 5


def test_a_refunded_event_no_longer_counts():
    counter = at.AttemptCounter("t", 60, clock=Clock())
    cache = FakeCache()
    _run(counter.hit("k"))
    _run(counter.hit("k"))
    _run(counter.refund("k"))
    assert _run(counter.hit("k"))[0] == 2
    _run(counter.hit("r", cache))
    _run(counter.hit("r", cache))
    _run(counter.refund("r", cache))
    assert _run(counter.hit("r", cache))[0] == 2
    # A refund can only undo a counted event: never below zero, in memory or in the shared
    # cache (a decrement racing a clear would otherwise create -1 and admit an extra attempt).
    _run(counter.refund("never-hit", cache))
    _run(counter.refund("never-hit"))
    assert all(int(v) >= 0 for v in cache.counts().values())
    assert _run(counter.hit("never-hit"))[0] == 1
    assert _run(counter.hit("never-hit", cache))[0] == 1


def test_a_refund_racing_a_clear_never_leaves_a_negative_count():
    counter = at.AttemptCounter("t", 60, clock=Clock())
    cache = FakeCache()
    _run(counter.hit("k", cache))
    window = cache.values["auththrottle:t:k:window"]
    cache.values[f"auththrottle:t:k:{window}"] = 0  # a concurrent success zeroed it
    _run(counter.refund("k", cache))
    assert cache.values[f"auththrottle:t:k:{window}"] == 0


def test_the_client_ip_is_the_address_the_load_balancer_appended():
    headers = {"x-forwarded-for": "198.51.100.7, 203.0.113.9"}  # the caller claimed .7
    assert at.client_ip(headers, "10.0.0.2") == "203.0.113.9"
    assert at.client_ip({}, "10.0.0.2") == "10.0.0.2"
    assert at.client_ip({}, None) == "unknown"


def test_email_keys_do_not_contain_the_address_and_ignore_case():
    key = at.email_digest(" Alice@Example.com ")
    assert "alice" not in key and key == at.email_digest("alice@example.com")


# ── the endpoints ────────────────────────────────────────────────────────

PASSWORD = "pw12345678"


@pytest.fixture()
def auth(monkeypatch):
    module = importlib.import_module("tenancy.auth.routes")
    for counter in module.throttle.ALL_COUNTERS:
        counter.reset()
    # Each test gets its own shared cache, as a fresh deployment would.
    shared = FakeCache()
    monkeypatch.setattr(module, "_auth_cache", lambda: shared)
    repos = importlib.import_module("repositories.repos")
    repos.reset_in_memory_stores()
    return module


def _request(forwarded: str = "", peer: str = "127.0.0.1"):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return types.SimpleNamespace(headers=headers, client=types.SimpleNamespace(host=peer))


async def _seed(email: str, tenant: str = "t-1") -> None:
    from shared.auth.password import hash_password

    repos = importlib.import_module("repositories.repos")
    await repos.AdminRepository().insert(tenant, {"name": "T", "contact_email": email, "plan_tier": "alpha", "status": "active"})
    await repos.UserRepository().insert(f"user-{tenant}", {
        "user_id": f"user-{tenant}", "tenant_id": tenant, "email": email, "name": "T",
        "password_hash": hash_password(PASSWORD), "status": "active", "auth_method": "password",
    })


def _login(auth, email, password, request=None):
    return _run(auth.login(auth.LoginRequest(email=email, password=password), None, request))


class SlowCache(FakeCache):
    """A shared cache whose every call yields to other requests first, as a network round trip does."""

    async def set_nx(self, key, value, ttl=0):
        await asyncio.sleep(0)
        return await super().set_nx(key, value, ttl)

    async def incr_by(self, key, amount, ttl=0):
        await asyncio.sleep(0)
        return await super().incr_by(key, amount, ttl)

    async def get(self, key):
        await asyncio.sleep(0)
        return await super().get(key)


def test_parallel_wrong_passwords_cannot_all_be_checked_past_the_cap(auth, monkeypatch):
    _run(_seed("p@x.io"))
    cache = SlowCache()  # one shared store, as every worker sees in production
    monkeypatch.setattr(auth, "_auth_cache", lambda: cache)

    async def burst():
        return await asyncio.gather(
            *[
                auth.login(auth.LoginRequest(email="p@x.io", password="wrong-password"), None, _request(peer="192.0.2.5"))
                for _ in range(6)
            ],
            return_exceptions=True,
        )

    outcomes = _run(burst())
    assert sum(isinstance(o, RateLimitedError) for o in outcomes) == 1
    assert sum(isinstance(o, BadRequestError) for o in outcomes) == 5


def test_retrying_during_the_address_wide_lockout_does_not_spend_the_clients_own_budget(auth):
    _run(_seed("w@x.io"))
    for client in range(5):  # trip the address-wide ceiling from five other clients
        for _ in range(5):
            with pytest.raises(BadRequestError):
                _login(auth, "w@x.io", "wrong-password", _request(peer=f"198.51.100.{client}"))
    for _ in range(6):  # the account holder keeps trying from a fresh network meanwhile
        with pytest.raises(RateLimitedError):
            _login(auth, "w@x.io", PASSWORD, _request(peer="203.0.113.7"))
    # The address-wide window ends (its window key expires in the shared cache).
    shared = auth._auth_cache()
    for key in [k for k in shared.values if k.startswith("auththrottle:login-failures:")]:
        shared.values.pop(key)
    assert "data" in _login(auth, "w@x.io", PASSWORD, _request(peer="203.0.113.7"))


def test_the_sixth_wrong_password_from_one_client_is_refused_even_with_the_right_one(auth):
    _run(_seed("a@x.io"))
    for _ in range(5):
        with pytest.raises(BadRequestError):
            _login(auth, "a@x.io", "wrong-password", _request(peer="192.0.2.1"))
    with pytest.raises(RateLimitedError):
        _login(auth, "a@x.io", PASSWORD, _request(peer="192.0.2.1"))


def test_one_clients_failures_do_not_lock_the_account_holder_out(auth):
    _run(_seed("h@x.io"))
    for _ in range(5):
        with pytest.raises(BadRequestError):
            _login(auth, "h@x.io", "wrong-password", _request(peer="192.0.2.1"))
    assert "data" in _login(auth, "h@x.io", PASSWORD, _request(peer="192.0.2.2"))


def test_guessing_spread_over_many_clients_is_stopped_by_the_per_address_ceiling(auth):
    _run(_seed("s@x.io"))
    for client in range(5):  # five clients, each within its own budget of five
        for _ in range(5):
            with pytest.raises(BadRequestError):
                _login(auth, "s@x.io", "wrong-password", _request(peer=f"198.51.100.{client}"))
    with pytest.raises(RateLimitedError):
        _login(auth, "s@x.io", PASSWORD, _request(peer="198.51.100.99"))


def test_an_unknown_address_is_throttled_the_same_way(auth):
    for _ in range(5):
        with pytest.raises(BadRequestError):
            _login(auth, "nobody@x.io", "whatever", _request(peer="192.0.2.1"))
    with pytest.raises(RateLimitedError):
        _login(auth, "nobody@x.io", "whatever", _request(peer="192.0.2.1"))


def test_a_successful_login_clears_the_failure_count(auth):
    _run(_seed("b@x.io"))
    for _ in range(4):
        with pytest.raises(BadRequestError):
            _login(auth, "b@x.io", "wrong-password", _request(peer="192.0.2.1"))
    assert "data" in _login(auth, "b@x.io", PASSWORD, _request(peer="192.0.2.1"))
    for _ in range(4):  # a fresh budget, not 4 + 4
        with pytest.raises(BadRequestError):
            _login(auth, "b@x.io", "wrong-password", _request(peer="192.0.2.1"))


def test_the_eleventh_login_a_minute_from_one_address_is_refused(auth):
    _run(_seed("c@x.io"))
    for _ in range(10):
        _login(auth, "c@x.io", PASSWORD, _request(peer="192.0.2.9"))
    with pytest.raises(RateLimitedError):
        _login(auth, "c@x.io", PASSWORD, _request(peer="192.0.2.9"))
    assert "data" in _login(auth, "c@x.io", PASSWORD, _request(peer="192.0.2.10"))  # another client is unaffected


def test_a_forged_forwarded_for_prefix_does_not_buy_a_fresh_limit(auth):
    _run(_seed("d@x.io"))
    for i in range(10):
        _login(auth, "d@x.io", PASSWORD, _request(forwarded=f"10.9.9.{i}, 203.0.113.50"))
    with pytest.raises(RateLimitedError):
        _login(auth, "d@x.io", PASSWORD, _request(forwarded="10.9.9.200, 203.0.113.50"))


def test_a_direct_call_without_a_request_is_not_counted_per_ip(auth):
    _run(_seed("e@x.io"))
    for _ in range(12):
        assert "data" in _login(auth, "e@x.io", PASSWORD)


def test_the_sixth_wrong_verification_code_is_refused_even_with_the_right_one(auth, monkeypatch):
    ver = importlib.import_module("shared.auth.verification")

    async def only_right_code(email, code, redis=None):
        return code == "123456"

    monkeypatch.setattr(ver, "verify_otp", only_right_code)

    def verify(code):
        return _run(auth.verify_email(auth.VerifyEmailRequest(email="v@x.io", code=code), None, _request()))

    for _ in range(5):
        with pytest.raises(BadRequestError):
            verify("000000")
    with pytest.raises(RateLimitedError):
        verify("123456")


def test_codes_cannot_be_mailed_to_one_address_more_than_five_times_in_a_window(auth):
    for _ in range(5):
        _run(auth.resend_verification(auth.ResendRequest(email="m@x.io"), _request()))
    with pytest.raises(RateLimitedError):
        _run(auth.resend_verification(auth.ResendRequest(email="m@x.io"), _request()))
    _run(auth.resend_verification(auth.ResendRequest(email="other@x.io"), _request()))


# ── emailed codes in the shared cache ────────────────────────────────────


def test_an_emailed_code_issued_by_one_process_verifies_on_another():
    from shared.auth import verification as ver

    cache = FakeCache()
    _run(ver.store_otp("Code@X.io", "123456", cache))
    ver._MEM_STORE.clear()  # another process has nothing in memory
    assert _run(ver.verify_otp("code@x.io", "123456", cache)) is True
    assert _run(ver.verify_otp("code@x.io", "123456", cache)) is False


def test_overlapping_verifies_with_the_right_code_pass_once():
    from shared.auth import verification as ver

    cache = SlowCache()
    _run(ver.store_otp("race@x.io", "654321", cache))

    async def race():
        return await asyncio.gather(*[ver.verify_otp("race@x.io", "654321", cache) for _ in range(3)])

    assert _run(race()).count(True) == 1


def test_a_wrong_code_does_not_spend_the_right_one():
    from shared.auth import verification as ver

    cache = FakeCache()
    _run(ver.store_otp("w@x.io", "111111", cache))
    assert _run(ver.verify_otp("w@x.io", "222222", cache)) is False
    assert _run(ver.verify_otp("w@x.io", "111111", cache)) is True


def test_the_auth_routes_use_the_platform_cache_client():
    from shared.cache.cache import CacheClient

    auth = importlib.import_module("tenancy.auth.routes")
    assert isinstance(auth._auth_cache(), CacheClient)
