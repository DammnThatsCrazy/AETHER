"""
Aether Shared — Distributed Multi-Identity Budget Engine

Redis-backed budget enforcement across multiple axes (API key, tenant, IP,
device fingerprint, identity cluster, graph cluster, model family, endpoint).

Replaces in-memory per-key-only throttling with cluster-aware distributed
budgets that detect multi-key evasion.

Backend:
- AETHER_ENV=local → in-memory counters (no Redis required)
- AETHER_ENV=staging/production → Redis INCR+EXPIRE
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.scoring.extraction_models import (
    ExtractionIdentity,
    get_model_tier,
)
from shared.rate_limit.budget_keys import (
    BudgetAxis,
    BudgetWindow,
    WINDOW_SECONDS,
    budget_key,
    budget_key_ttl,
    model_enumeration_key,
)
from shared.rate_limit.budget_policies import (
    get_tier_policy,
)

logger = get_logger("aether.rate_limit.distributed_budget")

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


# ═══════════════════════════════════════════════════════════════════════════
# BUDGET CHECK RESULT
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BudgetCheckResult:
    """Result of a multi-axis budget check."""
    allowed: bool = True
    exceeded_axis: Optional[BudgetAxis] = None
    exceeded_window: Optional[BudgetWindow] = None
    current_count: int = 0
    limit: int = 0
    retry_after_seconds: int = 0
    checked_axes: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        if self.allowed:
            return ""
        return (
            f"Budget exceeded on {self.exceeded_axis.value if self.exceeded_axis else '?'} "
            f"({self.exceeded_window.value if self.exceeded_window else '?'}): "
            f"{self.current_count}/{self.limit}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# DISTRIBUTED BUDGET ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class DistributedBudgetEngine:
    """
    Redis-backed multi-axis budget enforcement.

    Checks and increments counters across all available identity dimensions.
    Falls back to in-memory counters for local development.
    """

    def __init__(self, redis_client: Optional[Any] = None) -> None:
        self._redis: Optional[Any] = redis_client
        self._mode = "uninitialized"
        # In-memory fallback
        self._mem_counters: dict[str, int] = {}
        self._mem_expiry: dict[str, float] = {}

    async def connect(self) -> None:
        """Connect to Redis for distributed budget enforcement."""
        if self._redis:
            self._mode = "redis"
            return
        redis_host = os.getenv("REDIS_HOST", "")
        if redis_host and REDIS_AVAILABLE:
            port = os.getenv("REDIS_PORT", "6379")
            password = os.getenv("REDIS_PASSWORD", "")
            url = (
                f"redis://:{password}@{redis_host}:{port}/2"
                if password
                else f"redis://{redis_host}:{port}/2"
            )
            try:
                self._redis = aioredis.from_url(url, decode_responses=True, socket_timeout=5)
                await self._redis.ping()
                self._mode = "redis"
                logger.info(f"DistributedBudgetEngine connected (Redis: {redis_host})")
            except Exception as e:
                if _is_local_env():
                    logger.warning(f"Redis not reachable for budget engine ({e}) — in-memory")
                    self._redis = None
                    self._mode = "in-memory"
                else:
                    raise RuntimeError(f"Redis required for production budget engine: {e}")
        else:
            self._mode = "in-memory"
            if not _is_local_env():
                logger.warning("Budget engine running in-memory (non-local env)")

    async def check_and_increment(
        self,
        identity: ExtractionIdentity,
        model_name: str,
        batch_size: int = 1,
    ) -> BudgetCheckResult:
        """
        Check all applicable budget axes and increment counters atomically.

        Returns immediately on the first exceeded budget.
        """
        tier = get_model_tier(model_name)
        policy = get_tier_policy(tier)
        now = time.time()
        cost = max(1, batch_size)
        checked: list[str] = []

        # Build axis → identifier mapping from available identity dimensions
        axis_map: dict[BudgetAxis, str] = {}
        if identity.api_key_id:
            axis_map[BudgetAxis.API_KEY] = identity.api_key_id
        if identity.tenant_id:
            axis_map[BudgetAxis.TENANT] = identity.tenant_id
        if identity.source_ip:
            axis_map[BudgetAxis.IP] = identity.source_ip
        if identity.ip_prefix:
            axis_map[BudgetAxis.IP_PREFIX] = identity.ip_prefix
        if identity.device_fingerprint:
            axis_map[BudgetAxis.DEVICE] = identity.device_fingerprint
        if identity.identity_cluster_id:
            axis_map[BudgetAxis.IDENTITY_CLUSTER] = identity.identity_cluster_id
        if identity.graph_cluster_id:
            axis_map[BudgetAxis.GRAPH_CLUSTER] = identity.graph_cluster_id

        # Check each limit in policy against available axes
        for budget_limit in policy.limits:
            identifier = axis_map.get(budget_limit.axis)
            if identifier is None:
                continue  # This dimension not available — skip gracefully

            key = budget_key(budget_limit.axis, identifier, budget_limit.window, now)
            checked.append(f"{budget_limit.axis.value}/{budget_limit.window.value}")

            current = await self._incr(key, cost, budget_key_ttl(budget_limit.window))

            if current > budget_limit.max_count:
                metrics.increment(
                    "extraction_budget_exceeded",
                    labels={
                        "axis": budget_limit.axis.value,
                        "window": budget_limit.window.value,
                        "tier": tier.value,
                    },
                )
                retry_after = WINDOW_SECONDS[budget_limit.window] - int(
                    now % WINDOW_SECONDS[budget_limit.window]
                )
                return BudgetCheckResult(
                    allowed=False,
                    exceeded_axis=budget_limit.axis,
                    exceeded_window=budget_limit.window,
                    current_count=current,
                    limit=budget_limit.max_count,
                    retry_after_seconds=max(1, retry_after),
                    checked_axes=checked,
                )

        # Track model enumeration (distinct models queried)
        if identity.api_key_id:
            await self._track_model(identity.api_key_id, model_name)

        # Track feature fingerprints for sweep detection
        # (done asynchronously by the expectation engine)

        metrics.increment("extraction_budget_checked", labels={"tier": tier.value})
        return BudgetCheckResult(allowed=True, checked_axes=checked)

    async def get_usage(
        self,
        axis: BudgetAxis,
        identifier: str,
        window: BudgetWindow,
    ) -> int:
        """Get current usage count for an axis/identifier/window."""
        key = budget_key(axis, identifier, window)
        return await self._get(key)

    async def get_model_count(self, api_key_id: str) -> int:
        """Get number of distinct models queried by this API key."""
        key = model_enumeration_key(BudgetAxis.API_KEY, api_key_id)
        if self._redis:
            try:
                return await self._redis.scard(key)
            except Exception:
                return 0
        return len(self._mem_counters.get(key, set()) if isinstance(self._mem_counters.get(key), set) else [])

    # ── Internal helpers ─────────────────────────────────────────────

    async def _incr(self, key: str, amount: int, ttl: int) -> int:
        """Increment a counter atomically. Returns new value."""
        if self._redis:
            try:
                pipe = self._redis.pipeline()
                pipe.incrby(key, amount)
                pipe.expire(key, ttl)
                results = await pipe.execute()
                return results[0]
            except Exception as e:
                logger.error(f"Redis budget incr error: {e}")
                return self._mem_incr(key, amount, ttl)
        return self._mem_incr(key, amount, ttl)

    async def _get(self, key: str) -> int:
        if self._redis:
            try:
                val = await self._redis.get(key)
                return int(val) if val else 0
            except Exception:
                return self._mem_counters.get(key, 0)
        return self._mem_counters.get(key, 0)

    async def _track_model(self, api_key_id: str, model_name: str) -> None:
        key = model_enumeration_key(BudgetAxis.API_KEY, api_key_id)
        if self._redis:
            try:
                pipe = self._redis.pipeline()
                pipe.sadd(key, model_name)
                pipe.expire(key, 86400)
                await pipe.execute()
            except Exception as e:
                logger.debug(f"Redis model tracking error: {e}")
        else:
            if key not in self._mem_counters:
                self._mem_counters[key] = set()
            if isinstance(self._mem_counters[key], set):
                self._mem_counters[key].add(model_name)

    def _mem_incr(self, key: str, amount: int, ttl: int) -> int:
        """In-memory counter increment with expiry."""
        now = time.time()
        # Clean expired keys
        if key in self._mem_expiry and self._mem_expiry[key] < now:
            del self._mem_counters[key]
            del self._mem_expiry[key]

        if key not in self._mem_counters or not isinstance(self._mem_counters[key], int):
            self._mem_counters[key] = 0
        self._mem_counters[key] += amount
        self._mem_expiry[key] = now + ttl
        return self._mem_counters[key]

    @property
    def mode(self) -> str:
        return self._mode
