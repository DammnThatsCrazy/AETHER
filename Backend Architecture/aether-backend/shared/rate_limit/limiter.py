"""
Aether Shared — @aether/rate_limit
Per-plan burst RPM enforcement (P1-P4) using a Redis sliding-minute window.

Plan limits (from PLAN_CATALOG):
  P1 Hobbyist            -> 100 RPM
  P2 Professional        -> 500 RPM
  P3 Growth Intelligence -> 1,200 RPM
  P4 Protocol Master     -> 3,000 RPM

Key change vs the legacy 3-tier limiter:
  - Scoping is per-tenant (not per-API-key), so multiple keys under a
    tenant share one RPM pool.
  - Tier dimension is PlanTier instead of APIKeyTier.

Backend:
  AETHER_ENV=local -> in-memory sliding window (per-process)
  AETHER_ENV=staging/production -> Redis INCR+EXPIRE (distributed)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from shared.auth.auth import APIKeyTier, PlanTier, legacy_tier_to_plan
from shared.common.common import RateLimitedError
from shared.logger.logger import get_logger, metrics
from shared.plans.catalog import PLAN_CATALOG
from shared.rate_limit.metrics import BURST_REJECTED, BURST_TOTAL

logger = get_logger("aether.rate_limit")

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: float
    retry_after: Optional[int] = None

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(int(self.reset_at)),
        }


class BurstRateLimiter:
    """Per-plan burst RPM limiter.

    Uses an atomic INCR + EXPIRE on a per-minute key. The key is scoped to
    the tenant (not the API key) so all keys under one tenant share a pool.
    """

    def __init__(self, redis_client: Optional[Any] = None) -> None:
        self._buckets: dict[str, dict] = {}
        self._redis: Optional[Any] = redis_client
        self._mode = "in-memory"

    async def connect(self) -> None:
        """Connect to Redis for distributed rate limiting."""
        if self._redis:
            self._mode = "redis"
            return
        redis_host = os.getenv("REDIS_HOST", "")
        if redis_host and REDIS_AVAILABLE:
            port = os.getenv("REDIS_PORT", "6379")
            password = os.getenv("REDIS_PASSWORD", "")
            url = (
                f"redis://:{password}@{redis_host}:{port}/1"
                if password
                else f"redis://{redis_host}:{port}/1"
            )
            try:
                self._redis = aioredis.from_url(  # type: ignore[union-attr]
                    url, decode_responses=True, socket_timeout=5,
                )
                await self._redis.ping()
                self._mode = "redis"
                logger.info(f"BurstRateLimiter connected (Redis: {redis_host})")
            except Exception as e:
                if _is_local_env():
                    logger.warning(
                        f"Redis not reachable for rate limiter ({e}) — in-memory"
                    )
                    self._redis = None
                else:
                    raise RuntimeError(
                        f"Redis required for production rate limiting: {e}"
                    )

    @staticmethod
    def _limit_for(plan_tier: PlanTier) -> int:
        return PLAN_CATALOG[plan_tier].burst_rpm

    @staticmethod
    def _coerce_plan(tier: PlanTier | APIKeyTier | None) -> PlanTier:
        if tier is None:
            return PlanTier.P1_HOBBYIST
        if isinstance(tier, PlanTier):
            return tier
        if isinstance(tier, APIKeyTier):
            return legacy_tier_to_plan(tier)
        return PlanTier.P1_HOBBYIST

    # Lua script: atomic INCR + EXPIRE that prevents TOCTOU races.
    # Returns [allowed (0/1), current_count].
    _RATE_LIMIT_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
end
local limit = tonumber(ARGV[1])
if count > limit then
    return {0, count}
else
    return {1, count}
end
"""

    async def check(
        self,
        tenant_id: str,
        plan_tier: PlanTier | APIKeyTier | None = None,
    ) -> RateLimitResult:
        """Increment the per-tenant minute counter and return the verdict."""
        plan = self._coerce_plan(plan_tier)
        if self._redis:
            return await self._check_redis(tenant_id, plan)
        return self._check_memory(tenant_id, plan)

    # Backward-compatible alias for existing callers.
    async def check_async(
        self,
        identifier: str,
        plan_tier: PlanTier | APIKeyTier | None = None,
    ) -> RateLimitResult:
        return await self.check(identifier, plan_tier)

    async def _check_redis(
        self, tenant_id: str, plan: PlanTier,
    ) -> RateLimitResult:
        now = time.time()
        limit = self._limit_for(plan)
        window = 60
        minute_ts = int(now // window)
        key = f"rl:burst:{tenant_id}:{minute_ts}"
        reset_at = (minute_ts + 1) * window
        try:
            result = await self._redis.eval(
                self._RATE_LIMIT_LUA, 1, key, str(limit), str(window + 60),
            )
            allowed = bool(result[0])
            count = int(result[1])
            remaining = max(0, limit - count)
            self._emit_metrics(tenant_id, plan, allowed)
            if not allowed:
                metrics.increment(
                    "rate_limit_exceeded", labels={"plan": plan.value},
                )
                retry_after = max(1, int(reset_at - now))
                return RateLimitResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    reset_at=reset_at,
                    retry_after=retry_after,
                )
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=remaining,
                reset_at=reset_at,
                retry_after=None,
            )
        except Exception as e:
            logger.error(
                f"Redis rate limit error: {e} — falling back to in-memory",
            )
            return self._check_memory(tenant_id, plan)

    @staticmethod
    def _emit_metrics(tenant_id: str, plan: PlanTier, allowed: bool) -> None:
        status = "allowed" if allowed else "rejected"
        try:
            BURST_TOTAL.labels(
                tenant_id=tenant_id, plan_tier=plan.value, status=status,
            ).inc()
            if not allowed:
                BURST_REJECTED.labels(
                    tenant_id=tenant_id, plan_tier=plan.value,
                ).inc()
        except Exception:
            pass

    def _check_memory(self, tenant_id: str, plan: PlanTier) -> RateLimitResult:
        now = time.time()
        limit = self._limit_for(plan)
        window = 60.0
        bucket = self._buckets.get(tenant_id)
        if bucket is None or (now - bucket["window_start"]) >= window:
            self._buckets[tenant_id] = {"count": 1, "window_start": now}
            self._emit_metrics(tenant_id, plan, allowed=True)
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit - 1,
                reset_at=now + window,
                retry_after=None,
            )
        bucket["count"] += 1
        reset_at = bucket["window_start"] + window
        if bucket["count"] > limit:
            metrics.increment(
                "rate_limit_exceeded", labels={"plan": plan.value},
            )
            self._emit_metrics(tenant_id, plan, allowed=False)
            retry_after = max(1, int(reset_at - now))
            return RateLimitResult(
                allowed=False,
                limit=limit,
                remaining=0,
                reset_at=reset_at,
                retry_after=retry_after,
            )
        self._emit_metrics(tenant_id, plan, allowed=True)
        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=max(0, limit - bucket["count"]),
            reset_at=reset_at,
            retry_after=None,
        )

    def enforce(
        self, tenant_id: str, plan_tier: PlanTier | APIKeyTier | None = None,
    ) -> RateLimitResult:
        """Synchronous in-memory check that raises on exceedance."""
        plan = self._coerce_plan(plan_tier)
        result = self._check_memory(tenant_id, plan)
        if not result.allowed:
            retry_after = result.retry_after or int(result.reset_at - time.time())
            raise RateLimitedError(retry_after=max(1, retry_after))
        return result

    @property
    def mode(self) -> str:
        return self._mode


# Backward-compat alias so existing imports of TokenBucketLimiter continue to
# work. New code should use BurstRateLimiter.
TokenBucketLimiter = BurstRateLimiter
