"""Aether Shared — Monthly Quota Engine

Per-tenant pooled monthly request counter (P1=25K, P2=100K, P3=250K,
P4=500K). After the included quota is exhausted, requests are NOT blocked;
they are flagged as "overage" and metered per-service for billing.

Storage:
  Redis (hot path)        — atomic INCR per request
    Counter: rl:quota:{tenant_id}:{YYYY-MM}        (TTL 35 days)
    Overage: rl:overage:{tenant_id}:{YYYY-MM}      (Hash, TTL 35 days)
  PostgreSQL (durable)   — periodic snapshot
    Table:  tenant_usage
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from shared.auth.auth import PlanTier
from shared.logger.logger import get_logger
from shared.plans.catalog import PLAN_CATALOG
from shared.plans.service_catalog import resolve_service
from shared.rate_limit.metrics import (
    OVERAGE_REQUESTS,
    QUOTA_REMAINING,
    QUOTA_USED,
    QUOTA_UTILIZATION,
)

logger = get_logger("aether.quota")

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False


REDIS_TTL_SECONDS = 35 * 86400  # 35 days


@dataclass
class QuotaResult:
    allowed: bool                  # always True in v1 (overage is metered)
    included: bool                 # True within quota, False once in overage
    quota_limit: int
    quota_used: int
    remaining: int
    overage_service: Optional[str] # service name if metered as overage
    reset: str                     # ISO 8601 of next billing period start


def _current_period() -> str:
    """Return the current billing period (UTC) as 'YYYY-MM'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _next_period_start_iso() -> str:
    """Return the next billing period start (UTC) as ISO 8601."""
    now = datetime.now(timezone.utc)
    if now.month == 12:
        nxt = now.replace(
            year=now.year + 1, month=1, day=1,
            hour=0, minute=0, second=0, microsecond=0,
        )
    else:
        nxt = now.replace(
            month=now.month + 1, day=1,
            hour=0, minute=0, second=0, microsecond=0,
        )
    # Format with trailing 'Z' to match the spec example.
    return nxt.strftime("%Y-%m-%dT%H:%M:%SZ")


class QuotaEngine:
    """Monthly pooled quota counter.

    Increments are atomic. The engine never blocks: requests past the quota
    are returned with `included=False` and `overage_service` populated, and
    the caller is expected to honour the request and meter overage billing.
    """

    def __init__(self, redis_client: Optional[Any] = None) -> None:
        self._redis: Optional[Any] = redis_client
        self._memory_quota: dict[str, int] = {}
        self._memory_overage: dict[str, dict[str, int]] = {}
        self._mode = "in-memory"

    async def connect(self) -> None:
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
                logger.info(f"QuotaEngine connected (Redis: {redis_host})")
            except Exception as e:
                logger.warning(
                    f"Redis not reachable for quota engine ({e}) — in-memory",
                )
                self._redis = None

    @staticmethod
    def quota_key(tenant_id: str, period: str) -> str:
        return f"rl:quota:{tenant_id}:{period}"

    @staticmethod
    def overage_key(tenant_id: str, period: str) -> str:
        return f"rl:overage:{tenant_id}:{period}"

    async def check_and_increment(
        self,
        tenant_id: str,
        plan_tier: PlanTier,
        endpoint_path: str,
    ) -> QuotaResult:
        """Atomically increment the tenant's monthly counter.

        If the new count exceeds the plan's monthly quota, the request is
        considered overage and the matching service is incremented in the
        overage hash.
        """
        plan = PLAN_CATALOG[plan_tier]
        period = _current_period()
        qkey = self.quota_key(tenant_id, period)

        # Increment counter
        if self._redis is not None:
            try:
                current = await self._redis.incr(qkey)
                if current == 1:
                    await self._redis.expire(qkey, REDIS_TTL_SECONDS)
            except Exception as e:
                logger.warning(f"Quota INCR failed: {e} — fallback in-memory")
                current = self._memory_increment(qkey)
        else:
            current = self._memory_increment(qkey)

        included = current <= plan.monthly_quota
        remaining = max(0, plan.monthly_quota - current)
        overage_service: Optional[str] = None

        if not included:
            service = resolve_service(endpoint_path)
            if service is not None:
                overage_service = service.name
                okey = self.overage_key(tenant_id, period)
                if self._redis is not None:
                    try:
                        await self._redis.hincrby(okey, service.name, 1)
                        ttl = await self._redis.ttl(okey)
                        if ttl is None or ttl == -1:
                            await self._redis.expire(okey, REDIS_TTL_SECONDS)
                    except Exception as e:
                        logger.warning(f"Overage HINCRBY failed: {e}")
                        self._memory_overage_increment(okey, service.name)
                else:
                    self._memory_overage_increment(okey, service.name)
                try:
                    OVERAGE_REQUESTS.labels(
                        tenant_id=tenant_id,
                        plan_tier=plan_tier.value,
                        service=service.name,
                    ).inc()
                except Exception:
                    pass

        # Update Prometheus gauges (best-effort)
        try:
            QUOTA_USED.labels(
                tenant_id=tenant_id, plan_tier=plan_tier.value,
            ).set(current)
            QUOTA_REMAINING.labels(
                tenant_id=tenant_id, plan_tier=plan_tier.value,
            ).set(remaining)
            ratio = current / plan.monthly_quota if plan.monthly_quota else 0.0
            QUOTA_UTILIZATION.labels(
                tenant_id=tenant_id, plan_tier=plan_tier.value,
            ).set(ratio)
        except Exception:
            pass

        return QuotaResult(
            allowed=True,
            included=included,
            quota_limit=plan.monthly_quota,
            quota_used=current,
            remaining=remaining,
            overage_service=overage_service,
            reset=_next_period_start_iso(),
        )

    def _memory_increment(self, key: str) -> int:
        self._memory_quota[key] = self._memory_quota.get(key, 0) + 1
        return self._memory_quota[key]

    def _memory_overage_increment(self, key: str, service: str) -> None:
        bucket = self._memory_overage.setdefault(key, {})
        bucket[service] = bucket.get(service, 0) + 1

    async def get_overage_counts(
        self, tenant_id: str, period: Optional[str] = None,
    ) -> dict[str, int]:
        """Return per-service overage counts for the given period."""
        period = period or _current_period()
        okey = self.overage_key(tenant_id, period)
        if self._redis is not None:
            try:
                raw = await self._redis.hgetall(okey)
                return {k: int(v) for k, v in (raw or {}).items()}
            except Exception as e:
                logger.warning(f"Overage HGETALL failed: {e}")
        return dict(self._memory_overage.get(okey, {}))

    async def get_total_used(
        self, tenant_id: str, period: Optional[str] = None,
    ) -> int:
        """Return the current period's total request count."""
        period = period or _current_period()
        qkey = self.quota_key(tenant_id, period)
        if self._redis is not None:
            try:
                raw = await self._redis.get(qkey)
                return int(raw) if raw else 0
            except Exception as e:
                logger.warning(f"Quota GET failed: {e}")
        return self._memory_quota.get(qkey, 0)

    @property
    def mode(self) -> str:
        return self._mode
