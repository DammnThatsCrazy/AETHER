"""
Aether Shared — @aether/rate_limit
Token bucket algorithm with per-tier limits and standard headers.
Headers: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset

Backend:
- AETHER_ENV=local → in-memory token buckets
- AETHER_ENV=staging/production → Redis INCR+EXPIRE for distributed limiting
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from shared.auth.auth import APIKeyTier
from shared.common.common import RateLimitedError
from shared.logger.logger import get_logger, metrics
from config.settings import settings

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

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(int(self.reset_at)),
        }


class TokenBucketLimiter:
    """
    Rate limiter with per-tier limits.

    Production: Redis INCR+EXPIRE sliding window (distributed).
    Local: in-memory token buckets (per-process).
    """

    _TIER_LIMITS = {
        APIKeyTier.FREE: settings.rate_limit.free_rpm,
        APIKeyTier.PRO: settings.rate_limit.pro_rpm,
        APIKeyTier.ENTERPRISE: settings.rate_limit.enterprise_rpm,
    }

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
            url = f"redis://:{password}@{redis_host}:{port}/1" if password else f"redis://{redis_host}:{port}/1"
            try:
                self._redis = aioredis.from_url(url, decode_responses=True, socket_timeout=5)  # type: ignore[union-attr]
                await self._redis.ping()
                self._mode = "redis"
                logger.info(f"RateLimiter connected (Redis: {redis_host})")
            except Exception as e:
                if _is_local_env():
                    logger.warning(f"Redis not reachable for rate limiter ({e}) — in-memory")
                    self._redis = None
                else:
                    raise RuntimeError(f"Redis required for production rate limiting: {e}")

    def _get_limit(self, tier: APIKeyTier) -> int:
        return self._TIER_LIMITS.get(tier, 60)

    async def check_async(self, api_key: str, tier: APIKeyTier = APIKeyTier.FREE) -> RateLimitResult:
        """Async check — uses Redis if available, else in-memory."""
        if self._redis:
            return await self._check_redis(api_key, tier)
        return self.check(api_key, tier)

    async def _check_redis(self, api_key: str, tier: APIKeyTier) -> RateLimitResult:
        """Redis sliding window using INCR + EXPIRE."""
        now = time.time()
        limit = self._get_limit(tier)
        window = 60
        key = f"aether:ratelimit:{api_key}:{int(now // window)}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window + 1)
            results = await pipe.execute()
            count = results[0]
            remaining = max(0, limit - count)
            reset_at = (int(now // window) + 1) * window
            if count > limit:
                metrics.increment("rate_limit_exceeded", labels={"tier": tier.value})
                return RateLimitResult(allowed=False, limit=limit, remaining=0, reset_at=reset_at)
            return RateLimitResult(allowed=True, limit=limit, remaining=remaining, reset_at=reset_at)
        except Exception as e:
            logger.error(f"Redis rate limit error: {e} — falling back to in-memory")
            return self.check(api_key, tier)

    def check(self, api_key: str, tier: APIKeyTier = APIKeyTier.FREE) -> RateLimitResult:
        """Synchronous in-memory check."""
        now = time.time()
        limit = self._get_limit(tier)
        window = 60.0
        bucket = self._buckets.get(api_key)
        if bucket is None or (now - bucket["last_refill"]) >= window:
            self._buckets[api_key] = {"tokens": limit - 1, "last_refill": now}
            return RateLimitResult(allowed=True, limit=limit, remaining=limit - 1, reset_at=now + window)
        if bucket["tokens"] <= 0:
            reset_at = bucket["last_refill"] + window
            metrics.increment("rate_limit_exceeded", labels={"tier": tier.value})
            return RateLimitResult(allowed=False, limit=limit, remaining=0, reset_at=reset_at)
        bucket["tokens"] -= 1
        return RateLimitResult(allowed=True, limit=limit, remaining=bucket["tokens"], reset_at=bucket["last_refill"] + window)

    def enforce(self, api_key: str, tier: APIKeyTier = APIKeyTier.FREE) -> RateLimitResult:
        """Check rate limit and raise if exceeded."""
        result = self.check(api_key, tier)
        if not result.allowed:
            retry_after = int(result.reset_at - time.time())
            raise RateLimitedError(retry_after=max(1, retry_after))
        return result

    @property
    def mode(self) -> str:
        return self._mode
