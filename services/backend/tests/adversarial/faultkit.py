"""Shared fault-injection primitives (program sec9 / sec23 cross-cutting).

This module is the CROSS-CUTTING fault-injection harness. Every capability
suite (payment receipts, stablecoin observation, interop scan, reward
reservation, commerce settle, card-linked import, derivatives sequence) drives
the SAME deterministic fault vocabulary through these primitives:

  * ``FaultInjector`` + ``arm`` / ``arm_func`` — monkeypatch seam: make any
    method or callable raise timeout / rate-limit / auth / malformed /
    db-unavailable / broker-unavailable / worker-crash on a chosen call.
  * ``transport_handler`` — ``httpx`` handler factory for provider
    unreachable / timeout / rate limit / auth / malformed / partial responses.
  * ``PlanSource`` — deterministic async-generator stream plan for duplicate /
    replay / out-of-order / stale / partial frames and injected transport drops.
  * ``FaultyStore`` — proxy over a ``shared.store`` object that injects faults
    on configured methods (simulates Redis / DB unavailability at the store
    boundary).
  * ``expect_fault`` — the "failure is distinguishable from empty" invariant:
    an injected fault must raise (never silently succeed as healthy-empty).

NONE of these touch production code. They wrap production seams (transports,
stores, repos, credential backends) with deterministic injectors. There is no
live network, no live credential, no broker — every test runs against the
in-memory backends.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
from typing import Any, Awaitable, Callable, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Fault classification vocabulary
#
# The Phase-0 audit's adversarial matrix: each classification maps onto the
# production error vocabulary of the domain that owns it (connector tokens,
# ReceiptState, CheckpointState, ...). Keeping the tokens here gives every
# suite one shared spelling.
# ─────────────────────────────────────────────────────────────────────────────

PROVIDER_UNREACHABLE = "provider_unreachable"
PROVIDER_TIMEOUT = "provider_timeout"
PROVIDER_RATE_LIMITED = "provider_rate_limited"
PROVIDER_AUTH_FAILURE = "provider_auth_failure"
PROVIDER_MALFORMED = "provider_malformed"
PARTIAL_RESPONSE = "partial_response"
DB_UNAVAILABLE = "db_unavailable"
REDIS_UNAVAILABLE = "redis_unavailable"
BROKER_UNAVAILABLE = "broker_unavailable"
CLICKHOUSE_UNAVAILABLE = "clickhouse_unavailable"
WORKER_CRASH = "worker_crash"
PROCESS_RESTART = "process_restart"
CURSOR_CORRUPTION = "cursor_corruption"
OUTBOX_PUBLISH_FAILURE = "outbox_publish_failure"
DEAD_LETTER = "dead_letter"
CREDENTIAL_EXPIRY = "credential_expiry"
CREDENTIAL_ROTATION = "credential_rotation"
CROSS_TENANT = "cross_tenant"
WRONG_ENV = "wrong_env"
ROLLBACK = "rollback"
REPAIR = "repair"
RECONCILIATION_CONFLICT = "reconciliation_conflict"
DUPLICATE = "duplicate"
REPLAY = "replay"
OUT_OF_ORDER = "out_of_order"
STALE = "stale"

ALL_FAULTS: frozenset[str] = frozenset({
    PROVIDER_UNREACHABLE, PROVIDER_TIMEOUT, PROVIDER_RATE_LIMITED,
    PROVIDER_AUTH_FAILURE, PROVIDER_MALFORMED, PARTIAL_RESPONSE,
    DB_UNAVAILABLE, REDIS_UNAVAILABLE, BROKER_UNAVAILABLE, CLICKHOUSE_UNAVAILABLE,
    WORKER_CRASH, PROCESS_RESTART, CURSOR_CORRUPTION, OUTBOX_PUBLISH_FAILURE,
    DEAD_LETTER, CREDENTIAL_EXPIRY, CREDENTIAL_ROTATION, CROSS_TENANT, WRONG_ENV,
    ROLLBACK, REPAIR, RECONCILIATION_CONFLICT, DUPLICATE, REPLAY,
    OUT_OF_ORDER, STALE,
})


class InjectedFault(Exception):
    """Deterministic injected fault carrying a classification token.

    Every injected failure carries ``classification`` so a test can assert the
    failure surfaced under the EXPECTED token (never a silent healthy-empty).
    """

    def __init__(self, classification: str, message: str = "") -> None:
        super().__init__(message or classification)
        self.classification = classification


def make_fault(classification: str, message: str = "") -> InjectedFault:
    """An ``InjectedFault`` for ``classification`` (with an optional detail)."""
    if classification not in ALL_FAULTS:
        raise ValueError(f"unknown fault classification: {classification!r}")
    return InjectedFault(classification, message)


def classify(exc: BaseException) -> str:
    """The fault classification of an exception (defaults to its type name)."""
    return getattr(exc, "classification", None) or type(exc).__name__


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic fault injector
# ─────────────────────────────────────────────────────────────────────────────

class FaultInjector:
    """Raise ``exc`` on a chosen call, deterministically.

    Modes:
      ``never``      — never raises (healthy baseline).
      ``once``       — raises on the first call only.
      ``always``     — raises on every call.
      ``on_nth``     — raises only on call number ``nth`` (1-indexed).
      ``for_first_n``— raises on calls 1..nth, then passes through.
    """

    def __init__(
        self,
        exc: Optional[BaseException] = None,
        *,
        mode: str = "once",
        nth: int = 1,
    ) -> None:
        if mode not in ("never", "once", "always", "on_nth", "for_first_n"):
            raise ValueError(f"unknown injector mode: {mode!r}")
        self.exc: BaseException = exc if exc is not None else make_fault("injected_fault")
        self.mode = mode
        self.nth = nth
        self.calls = 0
        self.raised = 0

    def maybe_raise(self) -> None:
        """Advance the call counter and raise when this call is armed."""
        self.calls += 1
        should = {
            "never": False,
            "once": self.calls == 1,
            "always": True,
            "on_nth": self.calls == self.nth,
            "for_first_n": self.calls <= self.nth,
        }[self.mode]
        if should:
            self.raised += 1
            raise self.exc


def arm_func(
    fn: Callable[..., Any],
    injector: FaultInjector,
) -> Callable[..., Any]:
    """Wrap ``fn`` (sync or async) so it raises per ``injector`` then delegates."""
    if inspect.iscoroutinefunction(fn):

        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            injector.maybe_raise()
            return await fn(*args, **kwargs)

        return wrapped

    def wrapped_sync(*args: Any, **kwargs: Any) -> Any:
        injector.maybe_raise()
        return fn(*args, **kwargs)

    return wrapped_sync


def arm(
    instance: Any,
    method_name: str,
    injector: FaultInjector,
) -> Callable[[], None]:
    """Monkeypatch ``instance.method_name`` so it raises per ``injector`` then
    delegates to the original. Returns a restore callable.

    Works on any normal class (BaseRepository / TypedTableRepository / store
    object / service). The wrapped method preserves sync/async of the original.
    """
    original = getattr(instance, method_name)
    setattr(instance, method_name, arm_func(original, injector))

    def restore() -> None:
        setattr(instance, method_name, original)

    return restore


# ─────────────────────────────────────────────────────────────────────────────
# httpx transport fault factory
# ─────────────────────────────────────────────────────────────────────────────

def transport_handler(
    fault_kind: str,
    *,
    healthy_response: Optional[Any] = None,
    status: Optional[int] = None,
    after: int = 0,
    retry_after: str = "0",
) -> Callable[[Any], Awaitable[Any]]:
    """Return an async httpx handler that serves ``fault_kind`` then healthy.

    ``after`` healthy requests are served before the fault activates (0 = fail
    immediately). Status-style faults (rate limit 429, auth 401/403) return an
    ``httpx.Response`` with the given status; the rest raise the matching
    transport exception, so the production classifier (e.g.
    ``RestBackfillClient`` / ``StablecoinConnectorError``) sees a realistic
    failure.
    """
    import httpx

    state = {"n": 0}
    healthy = healthy_response if healthy_response is not None else httpx.Response(200, json={})

    async def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] <= after:
            return healthy
        if fault_kind == PROVIDER_TIMEOUT:
            raise httpx.ConnectTimeout("injected provider timeout")
        if fault_kind == PROVIDER_UNREACHABLE:
            raise httpx.ConnectError("injected provider unreachable")
        if fault_kind == BROKER_UNAVAILABLE:
            raise httpx.ConnectError("injected broker unreachable")
        if fault_kind == PROVIDER_RATE_LIMITED:
            return httpx.Response(
                429, headers={"Retry-After": retry_after}, json={"error": "rate_limited"}
            )
        if fault_kind == PROVIDER_AUTH_FAILURE:
            code = status or 401
            return httpx.Response(code, json={"error": "unauthorized"})
        if fault_kind == PROVIDER_MALFORMED:
            return httpx.Response(200, text="not-json{{{")
        if fault_kind == PARTIAL_RESPONSE:
            return httpx.Response(200, json={"items": [], "missing": "cursor"})
        if fault_kind == REDIS_UNAVAILABLE:
            raise httpx.ConnectError("injected redis unreachable")
        return healthy

    return handler


def mock_transport(*, fault_kind: str, **kwargs: Any) -> Any:
    """An ``httpx.MockTransport`` armed with :func:`transport_handler`.

    ``after`` healthy requests first, then the fault — so a retry
    (`initial + bounded retries`) can be observed deterministically.
    """
    import httpx

    return httpx.MockTransport(transport_handler(fault_kind, **kwargs))


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic stream plan
# ─────────────────────────────────────────────────────────────────────────────

class PlanSource:
    """Deterministic async-generator stream source for replay/order faults.

    ``plan`` is a list whose items are either payload dicts (yielded in order)
    or exceptions (raised at that point). The generator awaits ``sleep(0)``
    before each item so a test can interleave cooperatively. ``resume_cursors``
    records every cursor the producer was asked to resume from.
    """

    def __init__(self, plan: list[Any]) -> None:
        self.plan = list(plan)
        self.calls = 0
        self.resume_cursors: list[Any] = []

    async def __call__(self, resume_cursor: Any = None) -> Any:
        self.calls += 1
        self.resume_cursors.append(resume_cursor)
        for item in self.plan:
            await asyncio.sleep(0)
            if isinstance(item, Exception):
                raise item
            yield item


def frame(sequence: int, payload: dict[str, Any]) -> dict[str, Any]:
    """A stream frame: ``{"sequence": n, "payload": {...}}``."""
    return {"sequence": sequence, "payload": payload}


# ─────────────────────────────────────────────────────────────────────────────
# Faulty store proxy (Redis / DB unavailable at the store boundary)
# ─────────────────────────────────────────────────────────────────────────────

class FaultyStore:
    """Proxy over a ``shared.store`` object that injects faults per method.

    ``faults`` maps method name -> ``FaultInjector``. Unlisted methods delegate
    untouched. A repo that owns ``self._store`` (e.g.
    ``ProviderReceiptRepository``) can be pointed at a ``FaultyStore`` to
    simulate Redis / DB / broker unavailability without touching production
    code.
    """

    def __init__(self, store: Any, faults: Optional[dict[str, FaultInjector]] = None) -> None:
        self._store = store
        self._faults = faults or {}

    def __getattr__(self, name: str) -> Any:
        injector = self._faults.get(name)
        target = getattr(self._store, name)
        if injector is None:
            return target
        return arm_func(target, injector)


class CopyStore:
    """Wrap a store object so ``get``/``set`` cross a deep-copy boundary.

    In-memory stores hold live dict references, so a caller that mutates a
    fetched dict mutates the durable state even when its subsequent ``set``
    raises — the in-memory backend is NOT a faithful model of a real DB, which
    serializes on read. ``CopyStore`` restores the real contract: a failed
    write genuinely leaves the durable state untouched, so "a failed write
    must not advance the stage machine" is asserted deterministically.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    async def get(self, key: str) -> Optional[dict]:
        value = await self._store.get(key)
        return copy.deepcopy(value) if value is not None else None

    async def set(self, key: str, value: dict) -> Any:
        return await self._store.set(key, copy.deepcopy(value))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


# ─────────────────────────────────────────────────────────────────────────────
# Assertions
# ─────────────────────────────────────────────────────────────────────────────

async def expect_fault(
    awaitable: Awaitable[Any],
    classification: Optional[str] = None,
) -> BaseException:
    """Await ``awaitable`` asserting an injected fault raises.

    The core adversarial invariant: a fault is ALWAYS distinguishable from an
    empty-but-healthy result. If nothing raises, the test fails loudly.
    Returns the raised exception (so callers can assert detail).
    """
    try:
        await awaitable
    except BaseException as exc:  # noqa: BLE001 - asserting the fault surface
        if classification is not None:
            got = classify(exc)
            assert classification in got, (
                f"expected classification {classification!r}, got {got!r} ({exc!r})"
            )
        return exc
    raise AssertionError(
        f"expected fault {classification!r} but the callable completed without raising"
    )


def distinct_by(rows: list[dict], key: str) -> list[dict]:
    """Rows with unique ``key`` values, first occurrence wins (duplicate check)."""
    seen: dict[Any, dict] = {}
    for row in rows:
        seen.setdefault(row.get(key), row)
    return list(seen.values())


def assert_no_duplicates(rows: list[dict], key: str, *, label: str) -> None:
    """Assert every row carries a distinct ``key`` (no authoritative duplication)."""
    seen: set[Any] = set()
    for row in rows:
        value = row.get(key)
        assert value not in seen, (
            f"duplicate {label} {key!r}={value!r}: {row}"
        )
        seen.add(value)


def simulate_process_restart(*, name: str, stores_reset: bool = False) -> str:
    """Document/assert the in-memory "process restart" model.

    In-memory stores are module-level and survive a fresh worker/loop instance,
    so a NEW worker over the SAME stores is the deterministic stand-in for a
    process restart (the durable checkpoint / idempotency key is what a real
    restart would read back). Returns a human-readable trace token.
    """
    if stores_reset:
        raise ValueError(
            f"{name}: a process restart must NOT wipe durable state — "
            "resetting stores here would destroy the resume contract under test"
        )
    return f"{name}:restarted-over-durable-state"


__all__ = [
    "ALL_FAULTS",
    "InjectedFault",
    "make_fault",
    "classify",
    "FaultInjector",
    "arm_func",
    "arm",
    "transport_handler",
    "mock_transport",
    "PlanSource",
    "frame",
    "FaultyStore",
    "CopyStore",
    "expect_fault",
    "distinct_by",
    "assert_no_duplicates",
    "simulate_process_restart",
    "PROVIDER_UNREACHABLE",
    "PROVIDER_TIMEOUT",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_AUTH_FAILURE",
    "PROVIDER_MALFORMED",
    "PARTIAL_RESPONSE",
    "DB_UNAVAILABLE",
    "REDIS_UNAVAILABLE",
    "BROKER_UNAVAILABLE",
    "CLICKHOUSE_UNAVAILABLE",
    "WORKER_CRASH",
    "PROCESS_RESTART",
    "CURSOR_CORRUPTION",
    "OUTBOX_PUBLISH_FAILURE",
    "DEAD_LETTER",
    "CREDENTIAL_EXPIRY",
    "CREDENTIAL_ROTATION",
    "CROSS_TENANT",
    "WRONG_ENV",
    "ROLLBACK",
    "REPAIR",
    "RECONCILIATION_CONFLICT",
    "DUPLICATE",
    "REPLAY",
    "OUT_OF_ORDER",
    "STALE",
]
