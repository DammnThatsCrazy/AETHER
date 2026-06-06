"""Per-tenant query rate limiting for Noesis.

Uses CacheClient (Redis in production, in-memory in dev) to enforce:
- QPM (queries per minute) limit per tenant, keyed per UTC minute
- Daily quota per tenant, keyed per calendar day

Both limits increment atomically via CacheClient.incr. On any cache
failure the request is allowed through and a warning is logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone

from shared.cache.cache import CacheClient, CacheKey
from shared.common.common import RateLimitedError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.noesis.rate_limiter")

_QPM_TTL = 60        # 1-minute window
_DAILY_TTL = 86400   # 24-hour window


@dataclass(frozen=True)
class RateLimitState:
    limit: int
    remaining: int
    reset_seconds: int


class NoesisRateLimiter:
    """Enforce per-tenant QPM and daily quota limits using CacheClient counters."""

    def __init__(self, cache: CacheClient | None = None) -> None:
        self._cache = cache or CacheClient()
        self._qpm_limit = int(os.getenv("NOESIS_RATE_LIMIT_QPM", "60"))
        self._daily_limit = int(os.getenv("NOESIS_DAILY_QUOTA", "1000"))

    def _qpm_key(self, tenant_id: str) -> str:
        minute = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
        return CacheKey.custom(f"noesis:rl:qpm:{tenant_id}:{minute}")

    def _daily_key(self, tenant_id: str) -> str:
        day = date.today().isoformat()
        return CacheKey.custom(f"noesis:rl:daily:{tenant_id}:{day}")

    async def check_and_increment(self, tenant_id: str) -> RateLimitState:
        """Increment both counters and return current state.

        Raises RateLimitedError when QPM or daily quota is exceeded.
        On any cache failure, allows the request through.
        """
        try:
            qpm_count = await self._cache.incr(self._qpm_key(tenant_id), ttl=_QPM_TTL)
            daily_count = await self._cache.incr(self._daily_key(tenant_id), ttl=_DAILY_TTL)

            if qpm_count > self._qpm_limit:
                logger.warning(
                    "Noesis QPM rate limit exceeded",
                    extra={"tenant_id": tenant_id, "count": qpm_count, "limit": self._qpm_limit},
                )
                metrics.increment("noesis_rate_limited", labels={"scope": "qpm"})
                raise RateLimitedError(retry_after=60)

            if daily_count > self._daily_limit:
                logger.warning(
                    "Noesis daily quota exceeded",
                    extra={"tenant_id": tenant_id, "count": daily_count, "limit": self._daily_limit},
                )
                metrics.increment("noesis_rate_limited", labels={"scope": "daily"})
                raise RateLimitedError(retry_after=86400)

            remaining = max(0, self._qpm_limit - qpm_count)
            return RateLimitState(
                limit=self._qpm_limit,
                remaining=remaining,
                reset_seconds=60,
            )
        except RateLimitedError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Noesis rate limiter check failed, allowing: {exc}")
            return RateLimitState(
                limit=self._qpm_limit,
                remaining=self._qpm_limit,
                reset_seconds=60,
            )
