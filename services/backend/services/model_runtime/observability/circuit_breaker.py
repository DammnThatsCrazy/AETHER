"""Provider/tenant-scoped circuit breaker for the model runtime (ADR-008 D8).

The model runtime calls out to external model providers. A circuit breaker
per provider (and optionally per tenant) gives fail-closed, fast-fail semantics
so that an unhealthy provider does not stall every request or cascade load onto
the runtime.

States
------
CLOSED
    Normal operation; calls are allowed and failures are counted.
OPEN
    The failure threshold was reached. Calls are rejected immediately
    (fail-closed) until the recovery timeout elapses.
HALF_OPEN
    The recovery timeout elapsed. A single probe is allowed through; if it
    succeeds the circuit closes, if it fails the circuit reopens.

Design notes
------------
* Fail-closed: while a breaker is OPEN, callers MUST NOT invoke the provider.
  Callers gate on :meth:`CircuitBreaker.allowed` (or
  :meth:`CircuitRegistry.is_available`) before dispatching.
* No cross-tenant coupling: each ``provider`` / ``provider:tenant`` key owns an
  independent breaker, so one tenant's failures never trip another tenant's
  circuit for the same provider.
* Deterministic time: ``allowed()`` (and the record helpers) accept an
  injectable ``now`` so tests can exercise the recovery timeout without waiting.
* Security: the breaker holds no secrets, and ``tenant_id`` is used only as a
  plain registry key — it is never emitted in log records.

The established pattern lives in ``services/noesis/circuit_breaker.py``
(``NoesisCircuitBreaker``); this is the model-runtime analog with a
sync/thread-safe state machine and an explicit half-open probe policy.
"""

from __future__ import annotations

import enum
import threading
import time
from typing import Dict, Optional

__all__ = [
    "CircuitBreaker",
    "CircuitRegistry",
    "CircuitState",
]


def _resolve_now(now: Optional[float]) -> float:
    """Return *now* if given, otherwise the monotonic clock.

    ``now`` is an injected deterministic clock for tests; production callers
    omit it and use the real monotonic clock.
    """
    return time.monotonic() if now is None else float(now)


class CircuitState(str, enum.Enum):
    """Lifecycle states of a circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Fail-closed circuit breaker for a single provider/tenant key.

    Parameters
    ----------
    failure_threshold:
        Number of consecutive failures before the circuit opens.
    recovery_timeout_s:
        Seconds to remain OPEN before allowing a half-open probe.
    half_open_probe:
        When True (default) exactly one call is allowed through in HALF_OPEN
        state until its success/failure is recorded. When False, all calls are
        allowed through during HALF_OPEN.

    Thread-safety: every state mutation is guarded by an internal
    ``threading.Lock``, so concurrent ``record_*``/``allowed``/``reset`` calls
    are serialized and never corrupt the state machine.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 60.0,
        half_open_probe: bool = True,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if recovery_timeout_s < 0:
            raise ValueError("recovery_timeout_s must be >= 0")
        self._failure_threshold = int(failure_threshold)
        self._recovery_timeout_s = float(recovery_timeout_s)
        self._half_open_probe = bool(half_open_probe)

        self._lock = threading.Lock()
        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._opened_at: Optional[float] = None
        self._probe_in_flight: bool = False

    @property
    def state(self) -> CircuitState:
        """Current :class:`CircuitState` of this breaker."""
        with self._lock:
            return self._state

    def allowed(self, now: Optional[float] = None) -> bool:
        """Return True when a provider call is permitted right now.

        * CLOSED  -> True.
        * OPEN    -> False until ``recovery_timeout_s`` has elapsed since the
          circuit opened; the first post-timeout check transitions to
          HALF_OPEN and (with ``half_open_probe``) grants a single probe.
        * HALF_OPEN -> True for the single probe (or for all calls when
          ``half_open_probe`` is False); other callers are denied until the
          probe settles.

        ``now`` is an injectable deterministic clock; ``None`` uses the real
        monotonic clock.
        """
        with self._lock:
            current = _resolve_now(now)

            if self._state is CircuitState.CLOSED:
                return True

            if self._state is CircuitState.OPEN:
                if self._opened_at is None:
                    return False
                if current - self._opened_at < self._recovery_timeout_s:
                    return False
                # Recovery timeout elapsed: transition to HALF_OPEN.
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = False

            # HALF_OPEN: with probe policy, grant exactly one in-flight probe.
            if self._half_open_probe and self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

    def record_failure(self, now: Optional[float] = None) -> None:
        """Record a failed provider call.

        In CLOSED state, failures are counted and the circuit opens once the
        failure threshold is reached. In HALF_OPEN state, a failed probe trips
        the circuit straight back to OPEN.
        """
        with self._lock:
            self._failure_count += 1
            if self._state is CircuitState.HALF_OPEN:
                # Probe failed -> back to OPEN.
                self._state = CircuitState.OPEN
                self._opened_at = _resolve_now(now)
                self._probe_in_flight = False
            elif (
                self._state is CircuitState.CLOSED
                and self._failure_count >= self._failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = _resolve_now(now)
            # In OPEN state failures are still counted but the circuit stays
            # open until the recovery timeout grants a probe.

    def record_success(self, now: Optional[float] = None) -> None:
        """Record a successful provider call.

        In HALF_OPEN state a successful probe closes the circuit and resets the
        failure count. In CLOSED state the failure count is reset. Success does
        not directly close an OPEN circuit (recovery is timeout-driven).
        """
        # ``now`` is accepted for API symmetry with record_failure; a success
        # only needs it if we ever transition on success in future revisions.
        del now
        with self._lock:
            self._failure_count = 0
            self._probe_in_flight = False
            if self._state is CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._opened_at = None

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED (used by operators/tests)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._probe_in_flight = False


class CircuitRegistry:
    """Registry of per-provider/tenant :class:`CircuitBreaker` instances.

    Keys are deterministic: ``provider`` for the global (tenant-less) breaker
    and ``provider:tenant_id`` for a tenant-scoped breaker. Breakers are created
    lazily on first access and reused thereafter, so state is shared per key but
    never across keys (no cross-tenant coupling).

    Security: ``tenant_id`` is a plain registry key and is never logged.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 60.0,
    ) -> None:
        self._failure_threshold = int(failure_threshold)
        self._recovery_timeout_s = float(recovery_timeout_s)
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(provider: str, tenant_id: Optional[str]) -> str:
        if tenant_id is None:
            return provider
        return f"{provider}:{tenant_id}"

    def get(
        self,
        provider: str,
        tenant_id: Optional[str] = None,
    ) -> CircuitBreaker:
        """Return the breaker for *provider* (and *tenant_id*, if given).

        The breaker is created on first access and cached under the key
        ``provider`` or ``provider:tenant_id``.
        """
        key = self._key(provider, tenant_id)
        with self._lock:
            breaker = self._breakers.get(key)
            if breaker is None:
                breaker = CircuitBreaker(
                    failure_threshold=self._failure_threshold,
                    recovery_timeout_s=self._recovery_timeout_s,
                )
                self._breakers[key] = breaker
            return breaker

    def all(self) -> Dict[str, CircuitBreaker]:
        """Return a copy of the registry mapping (key -> breaker)."""
        with self._lock:
            return dict(self._breakers)

    def is_available(self, name: str) -> bool:
        """Return True when the breaker under registry key *name* is not OPEN.

        Fail-closed helper: while a breaker is OPEN the provider must not be
        invoked, so this reports unavailable; a missing key is assumed
        available. The check is clock-free and side-effect free (it does not
        transition OPEN -> HALF_OPEN nor consume a probe) — the authoritative
        gate for a specific call remains :meth:`CircuitBreaker.allowed`.
        """
        with self._lock:
            breaker = self._breakers.get(name)
        if breaker is None:
            return True
        return breaker.state is not CircuitState.OPEN
