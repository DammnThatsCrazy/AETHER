"""Bounded exponential backoff + jitter for provider adapter failures.

Only :attr:`AdapterStatus.RETRYABLE_ERROR` and :attr:`AdapterStatus.RATE_LIMITED`
are retried. ``UNAUTHORIZED``, ``PERMANENT_ERROR``, ``OK`` and ``NOT_SUPPORTED``
are never retried — a retry cannot fix a missing credential or a provider
rejecting us outright.

Delay honors ``RateLimitInfo.retry_after_ms`` when the provider tells us to wait;
otherwise it is ``BASE_DELAY_MS * 2**attempt`` capped at ``MAX_DELAY_MS``.

**Jitter determinism (documented choice):** jitter is injected as a parameter
(``jitter``, default ``0.0``) rather than sampled from ``random`` internally.
Callers that want real jitter pass a small fraction of the base delay; tests
pass ``0`` so expected delays are exact and stable.
"""

from __future__ import annotations

from shared.integration_contracts.results import AdapterStatus, RateLimitInfo


class RetryCoordinator:
    """Bounded exponential backoff + jitter for RETRYABLE_ERROR / RATE_LIMITED.
    NEVER retries UNAUTHORIZED or PERMANENT_ERROR."""

    MAX_RETRIES = 3
    BASE_DELAY_MS = 250
    MAX_DELAY_MS = 8_000

    # Statuses that must never be retried.
    _NON_RETRYABLE = frozenset({
        AdapterStatus.OK,
        AdapterStatus.UNAUTHORIZED,
        AdapterStatus.PERMANENT_ERROR,
        AdapterStatus.NOT_SUPPORTED,
    })

    def should_retry(self, status: AdapterStatus, *, attempt: int) -> bool:
        """False if attempt >= MAX_RETRIES or status in {UNAUTHORIZED, PERMANENT_ERROR, OK, NOT_SUPPORTED};
        True for RETRYABLE_ERROR / RATE_LIMITED."""
        if attempt >= self.MAX_RETRIES:
            return False
        if status in self._NON_RETRYABLE:
            return False
        return status in (AdapterStatus.RETRYABLE_ERROR, AdapterStatus.RATE_LIMITED)

    def delay_ms(
        self,
        attempt: int,
        info: RateLimitInfo | None = None,
        *,
        jitter: float = 0.0,
    ) -> float:
        """info.retry_after_ms if info set and >0 else min(BASE * 2**attempt, MAX) + jitter.

        Jitter is deterministic for tests: pass an explicit ``jitter`` (default 0).
        """
        if info is not None and info.retry_after_ms is not None and info.retry_after_ms > 0:
            return float(info.retry_after_ms)
        capped = min(self.BASE_DELAY_MS * (2 ** max(0, attempt)), self.MAX_DELAY_MS)
        return float(capped) + jitter


__all__ = ["RetryCoordinator"]
