"""Per-provider rate-limit coordination.

Honors the :class:`RateLimitInfo` carried on adapter results. This coordinator
is deliberately thin: it records a rate-limit signal and exposes the provider's
requested ``retry_after_ms`` for the retry coordinator / scheduler to honor.
It does NOT enforce a parallel budget — ``shared/rate_limit`` owns Aether's own
per-plan request budgets (burst RPM against our API), which is a different axis
from a provider throttling us, and there is no per-provider budget primitive
there to reuse. Keeping this thin avoids inventing a parallel mechanism.
"""

from __future__ import annotations

from typing import Any

from shared.integration_contracts.results import RateLimitInfo


class RateLimitCoordinator:
    """Honors RateLimitInfo from adapter results; per-provider budget via shared/rate_limit."""

    def __init__(self) -> None:
        # In-memory record of rate-limit signals observed for a provider. Useful
        # for observability and tests; not a durable store (that is Team D's
        # concern via the raw store / health signals).
        self._signals: list[dict[str, Any]] = []

    async def on_rate_limited(
        self,
        *,
        tenant_id: str,
        identity_key: str,
        info: RateLimitInfo | None,
    ) -> None:
        """Record rate-limit signal. When info.retry_after_ms is set, the caller
        (retry coordinator) uses it."""
        self._signals.append({
            "tenant_id": tenant_id,
            "identity_key": identity_key,
            "info": info.model_dump() if info is not None else None,
        })

    def retry_after_ms(self, info: RateLimitInfo | None) -> int:
        """info.retry_after_ms if set else 0 (callers fall back to their own backoff)."""
        if info is not None and info.retry_after_ms is not None:
            return int(info.retry_after_ms)
        return 0

    def signal_count(self) -> int:
        """Number of rate-limit signals recorded (observability / tests)."""
        return len(self._signals)


__all__ = ["RateLimitCoordinator"]
