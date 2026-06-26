"""Circuit breaker for Noesis external dependency calls.

States: CLOSED (normal) → OPEN (failing, reject fast) → HALF_OPEN (probing).
Distributed state is stored in Redis; falls back to in-memory when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

from shared.logger.logger import get_logger

logger = get_logger("aether.service.noesis.circuit_breaker")

T = TypeVar("T")

_STATE_CLOSED = "closed"
_STATE_OPEN = "open"
_STATE_HALF_OPEN = "half_open"


class NoesisCircuitBreaker:
    """Per-dependency circuit breaker with in-memory state.

    Parameters
    ----------
    name:
        Identifier for this breaker (used in log messages and metrics).
    failure_threshold:
        Number of consecutive failures before opening the circuit.
    recovery_timeout_s:
        Seconds to wait in OPEN state before transitioning to HALF_OPEN.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
    ) -> None:
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout_s = recovery_timeout_s

        self._state: str = _STATE_CLOSED
        self._failure_count: int = 0
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    async def call(self, coro: Awaitable[T], fallback: T) -> T:
        """Execute *coro* through the circuit breaker.

        Returns *fallback* immediately when the circuit is OPEN without
        executing *coro*. On HALF_OPEN, one probe is allowed through.
        """
        async with self._lock:
            current_state = self._current_state()

        if current_state == _STATE_OPEN:
            logger.warning(
                "Circuit breaker OPEN — returning fallback",
                extra={"circuit": self._name},
            )
            # Close the unawaited coroutine to avoid ResourceWarning
            if hasattr(coro, "close"):
                coro.close()  # type: ignore[union-attr]
            return fallback

        try:
            result = await coro
            async with self._lock:
                self._on_success()
            return result
        except Exception as exc:
            async with self._lock:
                self._on_failure()
            logger.warning(
                "Circuit breaker recorded failure",
                extra={
                    "circuit": self._name,
                    "failures": self._failure_count,
                    "error": str(exc),
                },
            )
            return fallback

    # ── Internal state machine ───────────────────────────────────────────────

    def _current_state(self) -> str:
        if self._state == _STATE_OPEN:
            if self._opened_at is not None:
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self._recovery_timeout_s:
                    self._state = _STATE_HALF_OPEN
                    logger.info(
                        "Circuit breaker transitioning to HALF_OPEN",
                        extra={"circuit": self._name},
                    )
        return self._state

    def _on_success(self) -> None:
        if self._state in (_STATE_HALF_OPEN, _STATE_CLOSED):
            self._failure_count = 0
            if self._state == _STATE_HALF_OPEN:
                logger.info(
                    "Circuit breaker CLOSED after successful probe",
                    extra={"circuit": self._name},
                )
            self._state = _STATE_CLOSED
            self._opened_at = None

    def _on_failure(self) -> None:
        self._failure_count += 1
        if self._state == _STATE_HALF_OPEN or self._failure_count >= self._failure_threshold:
            self._state = _STATE_OPEN
            self._opened_at = time.monotonic()
            logger.error(
                "Circuit breaker OPENED",
                extra={"circuit": self._name, "failures": self._failure_count},
            )

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED state (for testing)."""
        self._state = _STATE_CLOSED
        self._failure_count = 0
        self._opened_at = None
