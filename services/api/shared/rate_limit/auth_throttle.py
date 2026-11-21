"""Modest throttles for the unauthenticated email/password endpoints.

``/v1/auth/login``, ``/register``, ``/verify-email`` and ``/resend-verification``
are public paths, so the tenant burst limiter never sees them. Without a limit
a caller can guess passwords, brute-force the 6-digit verification code, or use
the endpoints to mail codes to arbitrary addresses. These limits are deliberately
small and are constants, not settings: nothing about them needs an operator lever.

Counters are keyed without storing the email address (a digest) and count an attempt
*before* the credential is checked (``enforce_rate``). The count is one atomic increment,
so parallel guesses cannot all slip under the cap, and a successful login or
verification clears it (``AttemptCounter.clear``). Each limit is therefore a cap on
consecutive attempts: the first N get through, the next is refused.

Password attempts are budgeted twice. A small budget per (address, client IP) means
one caller who fails five times locks only themselves out, never the account holder
on another network; a larger ceiling per address bounds guessing spread across many
addresses. Verification codes keep a single small per-address budget: a 6-digit code
is only safe with a hard cap on guesses, whoever makes them.

Counters live in the platform's shared cache (``CacheClient``: Redis or DynamoDB in
deployed environments), so every API process counts against the same budget. Each
window is opened atomically (``set_nx``) and gets its own counter key, so concurrent
hits never reset each other. Bounded process memory is used only when no cache is
given or the cache errors; it is per process, so it is a floor, not a guarantee.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any, Callable, Mapping, Optional

from shared.common.common import RateLimitedError

LOGIN_ATTEMPTS_PER_IP_PER_MINUTE = 10
LOGIN_FAILURES_PER_EMAIL_AND_IP = 5
LOGIN_FAILURES_PER_EMAIL = 25
VERIFY_FAILURES_PER_EMAIL = 5
OTP_SENDS_PER_EMAIL = 5
PUBLIC_AUTH_REQUESTS_PER_IP_PER_MINUTE = 20
MINUTE_SECONDS = 60
FAILURE_WINDOW_SECONDS = 15 * 60


def client_ip(headers: Mapping[str, str], peer: Optional[str]) -> str:
    """The caller's address as the load balancer saw it.

    The ALB *appends* the connecting address to ``X-Forwarded-For``, so the
    right-most entry is the one a client cannot forge; left-most entries are
    whatever the client sent.
    """
    forwarded = headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if hops:
        return hops[-1]
    return peer or "unknown"


def email_digest(email: str) -> str:
    """A stable key for an address that does not put the address in Redis."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:32]


def email_ip_digest(email: str, ip: str) -> str:
    """A stable key for one address as seen from one client, without either in Redis."""
    return hashlib.sha256(f"{email.strip().lower()}|{ip}".encode("utf-8")).hexdigest()[:32]


class AttemptCounter:
    """Counts events per key in a window that opens at the first event."""

    _MAX_MEMORY_KEYS = 10_000

    def __init__(self, name: str, window_seconds: int, *, clock: Callable[[], float] = time.time) -> None:
        self._name = name
        self._window = window_seconds
        self._clock = clock
        self._memory: dict[str, list[float]] = {}  # key -> [count, window closes at]

    @property
    def name(self) -> str:
        return self._name

    def _window_key(self, key: str) -> str:
        return f"auththrottle:{self._name}:{key}:window"

    def _count_key(self, key: str, window_id: str) -> str:
        return f"auththrottle:{self._name}:{key}:{window_id}"

    def _live(self, key: str, now: float) -> Optional[list[float]]:
        entry = self._memory.get(key)
        if entry is not None and entry[1] <= now:
            del self._memory[key]
            return None
        return entry

    async def _open_window(self, cache: Any, key: str, now: float) -> tuple[str, float]:
        """The current window for ``key`` as ``(window id, closes at)``, opening one if none.

        ``set_nx`` makes exactly one caller the opener; everyone else reads the window
        it stored. The id is unique per window, so a new window starts a new count.
        """
        wkey = self._window_key(key)
        for _ in range(3):
            closes = now + self._window
            window_id = f"{closes:.6f}-{secrets.token_hex(4)}"
            if await cache.set_nx(wkey, window_id, self._window):
                return window_id, closes
            current = await cache.get(wkey)
            if current:
                return str(current), float(str(current).split("-", 1)[0])
        raise RuntimeError("auth throttle window kept expiring")

    async def hit(self, key: str, cache: Any = None) -> tuple[int, int]:
        """Count one event; return ``(events in the window, seconds until it closes)``."""
        now = self._clock()
        if cache is not None:
            try:
                window_id, closes = await self._open_window(cache, key, now)
                count = int(await cache.incr_by(self._count_key(key, window_id), 1, self._window))
                return count, max(1, int(closes - now))
            except Exception:  # noqa: BLE001 - fall back to the local window
                pass
        entry = self._live(key, now)
        if entry is None:
            if len(self._memory) >= self._MAX_MEMORY_KEYS:
                for stale in [k for k, (_, closes) in self._memory.items() if closes <= now]:
                    del self._memory[stale]
                if len(self._memory) >= self._MAX_MEMORY_KEYS:
                    # An unauthenticated caller cannot grow this without bound: make
                    # room by dropping the window that closes soonest.
                    del self._memory[min(self._memory, key=lambda k: self._memory[k][1])]
            entry = self._memory[key] = [0.0, now + self._window]
        entry[0] += 1
        return int(entry[0]), max(1, int(entry[1] - now))

    async def refund(self, key: str, cache: Any = None) -> None:
        """Give back one counted event, for a request refused by a different limit."""
        if cache is not None:
            try:
                window_id = await cache.get(self._window_key(key))
                if window_id:
                    ckey = self._count_key(key, str(window_id))
                    # Never leave a count below zero (a refund racing a clear, or a
                    # window with no hits yet), so a refund cannot admit an extra
                    # attempt. Counters are only read through incr_by: DynamoDB keeps
                    # them in a separate attribute from get/set values.
                    if int(await cache.incr_by(ckey, -1, self._window)) < 0:
                        await cache.incr_by(ckey, 1, self._window)
            except Exception:  # noqa: BLE001
                pass
        entry = self._memory.get(key)
        if entry is not None and entry[0] > 0:
            entry[0] -= 1

    async def clear(self, key: str, cache: Any = None) -> None:
        if cache is not None:
            try:
                wkey = self._window_key(key)
                window_id = await cache.get(wkey)
                await cache.delete(wkey)
                if window_id:
                    await cache.delete(self._count_key(key, str(window_id)))
            except Exception:  # noqa: BLE001
                pass
        self._memory.pop(key, None)

    def reset(self) -> None:
        """Forget every in-memory count (tests)."""
        self._memory.clear()


async def enforce_rate(counter: AttemptCounter, key: str, limit: int, cache: Any = None) -> None:
    """Count one request and refuse it once ``key`` is over ``limit`` in the window."""
    count, retry_after = await counter.hit(key, cache)
    if count > limit:
        raise RateLimitedError(retry_after=retry_after, limiter=counter.name)


login_ip = AttemptCounter("login-ip", MINUTE_SECONDS)
# The next four count attempts since the last success, i.e. a run of failures.
login_failures = AttemptCounter("login-failures", FAILURE_WINDOW_SECONDS)
login_failures_by_ip = AttemptCounter("login-failures-ip", FAILURE_WINDOW_SECONDS)
verify_failures = AttemptCounter("verify-failures", FAILURE_WINDOW_SECONDS)
otp_sends = AttemptCounter("otp-sends", FAILURE_WINDOW_SECONDS)
public_auth_ip = AttemptCounter("public-auth-ip", MINUTE_SECONDS)

ALL_COUNTERS = (login_ip, login_failures, login_failures_by_ip, verify_failures, otp_sends, public_auth_ip)
