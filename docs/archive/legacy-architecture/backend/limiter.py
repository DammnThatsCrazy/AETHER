"""
Aether Shared — @aether/rate_limit
Token bucket algorithm with per-tier limits and standard headers.
Headers: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from config.settings import settings
from shared.auth.auth import APIKeyTier
from shared.common.common import RateLimitedError
from shared.logger.logger import get_logger

logger = get_logger("aether.rate_limit")


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: float  # Unix timestamp

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(int(self.reset_at)),
        }


class TokenBucketLimiter:
    """
    In-memory token bucket rate limiter.
    In production, use Redis-backed sliding window (e.g. redis-cell or Lua script).
    """

    # Requests per minute by tier
    _TIER_LIMITS = {
        APIKeyTier.FREE: settings.rate_limit.free_rpm,
        APIKeyTier.PRO: settings.rate_limit.pro_rpm,
        APIKeyTier.ENTERPRISE: settings.rate_limit.enterprise_rpm,
    }

    def __init__(self):
        # {api_key: {"tokens": int, "last_refill": float}}
        self._buckets: dict[str, dict] = {}

    def _get_limit(self, tier: APIKeyTier) -> int:
        return self._TIER_LIMITS.get(tier, 60)

    def check(self, api_key: str, tier: APIKeyTier = APIKeyTier.FREE) -> RateLimitResult:
        """Check and consume a token. Returns limit result with headers."""
        now = time.time()
        limit = self._get_limit(tier)
        window = 60.0  # 1 minute window

        bucket = self._buckets.get(api_key)
        if bucket is None or (now - bucket["last_refill"]) >= window:
            # New window — refill bucket
            self._buckets[api_key] = {
                "tokens": limit - 1,
                "last_refill": now,
            }
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit - 1,
                reset_at=now + window,
            )

        if bucket["tokens"] <= 0:
            reset_at = bucket["last_refill"] + window
            return RateLimitResult(
                allowed=False,
                limit=limit,
                remaining=0,
                reset_at=reset_at,
            )

        bucket["tokens"] -= 1
        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=bucket["tokens"],
            reset_at=bucket["last_refill"] + window,
        )

    def enforce(self, api_key: str, tier: APIKeyTier = APIKeyTier.FREE) -> RateLimitResult:
        """Check rate limit and raise if exceeded."""
        result = self.check(api_key, tier)
        if not result.allowed:
            retry_after = int(result.reset_at - time.time())
            raise RateLimitedError(retry_after=max(1, retry_after))
        return result
