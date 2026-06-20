"""
Aether Security — Query Rate Limiter

Sliding-window rate limiter with per-API-key AND per-IP tracking.
Uses a bucketed counter approach for O(1) check/increment operations.

Unlike the existing token-bucket limiter, this module:
  - Tracks both API key and IP address independently
  - Uses a true sliding window (not fixed 60s reset)
  - Supports configurable minute/hour/day windows
  - Accounts for batch request cost (1 token per instance)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Optional

from .config import RateLimiterConfig

logger = logging.getLogger("aether.security.rate_limiter")


@dataclass
class RateLimitCheck:
    """Result of a rate limit check."""

    allowed: bool
    source: str  # "api_key" or "ip"
    limit: int
    remaining: int
    window: str  # "minute", "hour", "day"
    retry_after_seconds: int = 0


class SlidingWindowCounter:
    """
    Sliding window counter using sub-buckets.

    Each window is divided into N buckets (1 bucket per `bucket_width` seconds).
    On each check, expired buckets are purged and the current count is the sum
    of all active buckets.
    """

    def __init__(self, window_seconds: int, max_count: int, bucket_width: int = 1):
        self.window_seconds = window_seconds
        self.max_count = max_count
        self.bucket_width = bucket_width
        self._buckets: dict[int, int] = {}
        self._lock = Lock()

    def _current_bucket(self) -> int:
        return int(time.time()) // self.bucket_width

    def _purge_expired(self, now_bucket: int) -> None:
        cutoff = now_bucket - (self.window_seconds // self.bucket_width)
        expired = [b for b in self._buckets if b < cutoff]
        for b in expired:
            del self._buckets[b]

    def count(self) -> int:
        """Return the current count within the sliding window."""
        now_bucket = self._current_bucket()
        with self._lock:
            self._purge_expired(now_bucket)
            return sum(self._buckets.values())

    def check_and_increment(self, cost: int = 1) -> tuple[bool, int]:
        """
        Check if adding `cost` tokens would exceed the limit.
        If allowed, increment the counter and return (True, remaining).
        Otherwise return (False, 0).
        """
        now_bucket = self._current_bucket()
        with self._lock:
            self._purge_expired(now_bucket)
            current = sum(self._buckets.values())
            if current + cost > self.max_count:
                return False, max(0, self.max_count - current)
            self._buckets[now_bucket] = self._buckets.get(now_bucket, 0) + cost
            return True, max(0, self.max_count - current - cost)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


class ClientWindows:
    """Three sliding windows (minute/hour/day) for a single client identifier."""

    def __init__(self, limits: tuple[int, int, int], bucket_width: int = 1):
        self.minute = SlidingWindowCounter(60, limits[0], bucket_width)
        self.hour = SlidingWindowCounter(3600, limits[1], bucket_width)
        self.day = SlidingWindowCounter(86400, limits[2], bucket_width)

    def check(self, cost: int = 1) -> Optional[RateLimitCheck]:
        """
        Check all three windows. Returns a denial RateLimitCheck for the
        first window that would be exceeded, or None if all pass.
        """
        for window, name, secs in [
            (self.minute, "minute", 60),
            (self.hour, "hour", 3600),
            (self.day, "day", 86400),
        ]:
            current = window.count()
            if current + cost > window.max_count:
                return RateLimitCheck(
                    allowed=False,
                    source="",
                    limit=window.max_count,
                    remaining=0,
                    window=name,
                    retry_after_seconds=secs // 10,  # heuristic backoff
                )
        # All windows pass — increment all
        self.minute.check_and_increment(cost)
        self.hour.check_and_increment(cost)
        self.day.check_and_increment(cost)
        return None


class QueryRateLimiter:
    """
    Dual-axis rate limiter: tracks both API key and IP address.

    A request is denied if EITHER axis exceeds its limit. This prevents
    multi-key attacks from a single IP and single-key attacks from
    distributed IPs.
    """

    def __init__(self, config: Optional[RateLimiterConfig] = None):
        self.config = config or RateLimiterConfig()
        self._key_windows: dict[str, ClientWindows] = {}
        self._ip_windows: dict[str, ClientWindows] = {}
        self._lock = Lock()

    def _get_key_windows(self, api_key: str) -> ClientWindows:
        if api_key not in self._key_windows:
            self._key_windows[api_key] = ClientWindows(
                limits=(
                    self.config.key_max_per_minute,
                    self.config.key_max_per_hour,
                    self.config.key_max_per_day,
                ),
                bucket_width=self.config.bucket_width_seconds,
            )
        return self._key_windows[api_key]

    def _get_ip_windows(self, ip: str) -> ClientWindows:
        if ip not in self._ip_windows:
            self._ip_windows[ip] = ClientWindows(
                limits=(
                    self.config.ip_max_per_minute,
                    self.config.ip_max_per_hour,
                    self.config.ip_max_per_day,
                ),
                bucket_width=self.config.bucket_width_seconds,
            )
        return self._ip_windows[ip]

    def check(
        self,
        api_key: str,
        ip_address: str,
        cost: int = 1,
    ) -> RateLimitCheck:
        """
        Check rate limits for both API key and IP.
        Returns RateLimitCheck with allowed=True if both pass.
        """
        with self._lock:
            # Check API key windows
            key_windows = self._get_key_windows(api_key)
            key_denial = key_windows.check(cost)
            if key_denial is not None:
                key_denial.source = "api_key"
                logger.warning(
                    "Rate limit exceeded for API key %s (window=%s)",
                    api_key[:8] + "...",
                    key_denial.window,
                )
                return key_denial

            # Check IP windows
            ip_windows = self._get_ip_windows(ip_address)
            ip_denial = ip_windows.check(cost)
            if ip_denial is not None:
                ip_denial.source = "ip"
                logger.warning(
                    "Rate limit exceeded for IP %s (window=%s)",
                    ip_address,
                    ip_denial.window,
                )
                return ip_denial

        # Both axes pass
        key_min_remaining = min(
            key_windows.minute.count(),
            key_windows.hour.count(),
            key_windows.day.count(),
        )
        return RateLimitCheck(
            allowed=True,
            source="ok",
            limit=self.config.key_max_per_minute,
            remaining=max(0, self.config.key_max_per_minute - key_windows.minute.count()),
            window="minute",
        )

    def get_query_velocity(self, api_key: str) -> dict[str, int]:
        """Return current query counts per window for a given API key."""
        if api_key not in self._key_windows:
            return {"minute": 0, "hour": 0, "day": 0}
        w = self._key_windows[api_key]
        return {
            "minute": w.minute.count(),
            "hour": w.hour.count(),
            "day": w.day.count(),
        }

    def cleanup_expired(self) -> int:
        """Remove client entries with zero counts across all windows. Returns count removed."""
        removed = 0
        with self._lock:
            for store in (self._key_windows, self._ip_windows):
                expired_keys = []
                for key, windows in store.items():
                    if (
                        windows.minute.count() == 0
                        and windows.hour.count() == 0
                        and windows.day.count() == 0
                    ):
                        expired_keys.append(key)
                for k in expired_keys:
                    del store[k]
                    removed += 1
        return removed


class RedisRateLimiter:
    """
    Redis-backed sliding-window rate limiter for multi-replica deployments.

    Uses a sorted-set per (axis, identifier, window) key where each member is
    a unique timestamp token and the score is the epoch-ms timestamp.
    Expired tokens are pruned on each check with ZREMRANGEBYSCORE.

    Drop-in replacement for QueryRateLimiter: same check() / get_query_velocity()
    / cleanup_expired() interface, same RateLimitCheck return type.
    """

    _WINDOWS = (
        ("minute", 60),
        ("hour", 3600),
        ("day", 86400),
    )

    def __init__(self, redis_client: Any, config: Optional[RateLimiterConfig] = None):
        self._redis = redis_client
        self.config = config or RateLimiterConfig()

    def _rkey(self, axis: str, identifier: str, window: str) -> str:
        return f"aether:rl:{axis}:{identifier}:{window}"

    def _count_window(self, axis: str, identifier: str, window_name: str, window_secs: int) -> int:
        now_ms = time.time() * 1000
        cutoff_ms = now_ms - window_secs * 1000
        key = self._rkey(axis, identifier, window_name)
        pipe = self._redis.pipeline(transaction=False)
        pipe.zremrangebyscore(key, "-inf", cutoff_ms)
        pipe.zcard(key)
        results = pipe.execute()
        return int(results[1])

    def _record(self, axis: str, identifier: str, cost: int) -> None:
        now_ms = time.time() * 1000
        token_base = os.urandom(4).hex()
        for window_name, window_secs in self._WINDOWS:
            key = self._rkey(axis, identifier, window_name)
            pipe = self._redis.pipeline(transaction=False)
            for i in range(cost):
                pipe.zadd(key, {f"{now_ms:.3f}:{token_base}:{i}": now_ms})
            pipe.expire(key, window_secs + 60)
            pipe.execute()

    def check(self, api_key: str, ip_address: str, cost: int = 1) -> RateLimitCheck:
        """Check rate limits for both API key and IP axes. Returns allowed=True if both pass."""
        axes = [
            ("key", api_key, (
                self.config.key_max_per_minute,
                self.config.key_max_per_hour,
                self.config.key_max_per_day,
            ), "api_key"),
            ("ip", ip_address, (
                self.config.ip_max_per_minute,
                self.config.ip_max_per_hour,
                self.config.ip_max_per_day,
            ), "ip"),
        ]
        for axis, identifier, limits, source_name in axes:
            for (window_name, window_secs), max_count in zip(self._WINDOWS, limits):
                current = self._count_window(axis, identifier, window_name, window_secs)
                if current + cost > max_count:
                    logger.warning(
                        "Redis rate limit exceeded for %s (window=%s axis=%s)",
                        identifier[:8] + "...",
                        window_name,
                        axis,
                    )
                    return RateLimitCheck(
                        allowed=False,
                        source=source_name,
                        limit=max_count,
                        remaining=0,
                        window=window_name,
                        retry_after_seconds=window_secs // 10,
                    )

        # All windows and axes passed — record the cost
        for axis, identifier, _, _ in axes:
            self._record(axis, identifier, cost)

        return RateLimitCheck(
            allowed=True,
            source="ok",
            limit=self.config.key_max_per_minute,
            remaining=max(0, self.config.key_max_per_minute - self._count_window("key", api_key, "minute", 60)),
            window="minute",
        )

    def get_query_velocity(self, api_key: str) -> dict[str, int]:
        """Return current query counts per window for a given API key."""
        return {
            window_name: self._count_window("key", api_key, window_name, window_secs)
            for window_name, window_secs in self._WINDOWS
        }

    def cleanup_expired(self) -> int:
        """No-op — Redis keys expire automatically via TTL set in _record()."""
        return 0
