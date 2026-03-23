"""
Aether Shared -- Usage Meter

Per-tenant, per-provider usage tracking for billing and monitoring,
persisted durably in the shared repository SQLite store.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from shared.logger.logger import get_logger, metrics
from repositories.repos import BaseRepository

logger = get_logger("aether.providers.meter")


@dataclass
class UsageRecord:
    """Aggregated usage for a tenant / provider / category combination."""

    tenant_id: str
    category: str
    provider_name: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    period_start: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "category": self.category,
            "provider_name": self.provider_name,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "success_rate": round(self.success_rate, 4),
            "period_start": self.period_start,
        }


class UsageMeter:
    """
    Durable usage aggregation per tenant per provider.
    """

    def __init__(self, flush_interval_s: int = 60) -> None:
        self._repo = BaseRepository("provider_usage")
        self._flush_interval = flush_interval_s
        self._last_flush = time.time()

    @staticmethod
    def _usage_key(tenant_id: str, category: str, provider_name: str) -> str:
        return f"{tenant_id}:{category}:{provider_name}"

    async def record(
        self,
        tenant_id: str,
        category: str,
        provider_name: str,
        method: str,
        latency_ms: float,
        success: bool,
    ) -> None:
        """Record a single provider call."""
        key = self._usage_key(tenant_id, category, provider_name)

        existing = await self._repo.find_by_id(key)
        if existing is None:
            rec = UsageRecord(
                tenant_id=tenant_id,
                category=category,
                provider_name=provider_name,
                period_start=time.time(),
            )
        else:
            rec = UsageRecord(
                tenant_id=existing["tenant_id"],
                category=existing["category"],
                provider_name=existing["provider_name"],
                total_requests=existing.get("total_requests", 0),
                successful_requests=existing.get("successful_requests", 0),
                failed_requests=existing.get("failed_requests", 0),
                total_latency_ms=existing.get("total_latency_ms", 0.0),
                period_start=existing.get("period_start", time.time()),
            )
        method_counts = dict((existing or {}).get("method_breakdown", {}))
        rec.total_requests += 1
        rec.total_latency_ms += latency_ms
        if success:
            rec.successful_requests += 1
        else:
            rec.failed_requests += 1

        method_counts[method] = method_counts.get(method, 0) + 1
        payload = rec.to_dict()
        payload["total_latency_ms"] = rec.total_latency_ms
        payload["method_breakdown"] = method_counts
        if existing is None:
            await self._repo.insert(key, payload)
        else:
            await self._repo.update(key, payload)

        metrics.increment("provider_usage", labels={
            "tenant_id": tenant_id,
            "category": category,
            "provider": provider_name,
            "status": "success" if success else "failure",
        })

    async def get_usage(
        self,
        tenant_id: str,
        category: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> list[dict]:
        """Query usage records for a tenant with optional filters."""
        results = []
        filters = {"tenant_id": tenant_id}
        if category:
            filters["category"] = category
        if provider_name:
            filters["provider_name"] = provider_name
        for raw in await self._repo.find_many(filters=filters, limit=10_000):
            entry = {k: v for k, v in raw.items() if k not in {"id", "created_at", "updated_at", "total_latency_ms"}}
            results.append(entry)
        return results

    async def get_tenant_summary(self, tenant_id: str) -> dict:
        """Summarised usage for a tenant across all providers."""
        total = success = failed = 0
        by_category: dict[str, int] = defaultdict(int)
        by_provider: dict[str, int] = defaultdict(int)

        for raw in await self._repo.find_many(filters={"tenant_id": tenant_id}, limit=10_000):
            total += raw.get("total_requests", 0)
            success += raw.get("successful_requests", 0)
            failed += raw.get("failed_requests", 0)
            by_category[raw.get("category", "")] = by_category.get(raw.get("category", ""), 0) + raw.get("total_requests", 0)
            by_provider[raw.get("provider_name", "")] = by_provider.get(raw.get("provider_name", ""), 0) + raw.get("total_requests", 0)

        return {
            "tenant_id": tenant_id,
            "total_requests": total,
            "successful_requests": success,
            "failed_requests": failed,
            "success_rate": round(success / total, 4) if total else 0,
            "by_category": dict(by_category),
            "by_provider": dict(by_provider),
        }

    async def flush(self) -> None:
        """Flush hook retained for compatibility; writes are already durable."""
        self._last_flush = time.time()
        logger.debug("Usage meter flush checkpoint recorded")
