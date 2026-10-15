"""
Aether Shared -- Usage Meter

Per-tenant, per-provider usage tracking for billing and monitoring.

In-memory aggregation with periodic flush to PostgreSQL when available.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.providers.meter")

# Optional asyncpg import for DB flushing
try:
    from repositories.repos import get_pool
    DB_FLUSH_AVAILABLE = True
except ImportError:
    DB_FLUSH_AVAILABLE = False

    async def get_pool() -> None:  # type: ignore[misc]
        return None


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
    In-memory usage aggregation per tenant per provider.
    Production: periodic flush to TimescaleDB.
    """

    def __init__(self, flush_interval_s: int = 60) -> None:
        self._records: dict[str, UsageRecord] = {}
        self._flush_interval = flush_interval_s
        self._last_flush = time.time()
        self._method_counts: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int),
        )

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

        if key not in self._records:
            self._records[key] = UsageRecord(
                tenant_id=tenant_id,
                category=category,
                provider_name=provider_name,
                period_start=time.time(),
            )

        rec = self._records[key]
        rec.total_requests += 1
        rec.total_latency_ms += latency_ms
        if success:
            rec.successful_requests += 1
        else:
            rec.failed_requests += 1

        self._method_counts[key][method] += 1

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
        for key, rec in self._records.items():
            if rec.tenant_id != tenant_id:
                continue
            if category and rec.category != category:
                continue
            if provider_name and rec.provider_name != provider_name:
                continue
            entry = rec.to_dict()
            entry["method_breakdown"] = dict(self._method_counts.get(key, {}))
            results.append(entry)
        return results

    async def get_tenant_summary(self, tenant_id: str) -> dict:
        """Summarised usage for a tenant across all providers."""
        total = success = failed = 0
        by_category: dict[str, int] = defaultdict(int)
        by_provider: dict[str, int] = defaultdict(int)

        for rec in self._records.values():
            if rec.tenant_id != tenant_id:
                continue
            total += rec.total_requests
            success += rec.successful_requests
            failed += rec.failed_requests
            by_category[rec.category] += rec.total_requests
            by_provider[rec.provider_name] += rec.total_requests

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
        """Flush aggregated usage records to PostgreSQL."""
        if not self._records:
            return

        pool = await get_pool() if DB_FLUSH_AVAILABLE else None
        if pool is not None:
            try:
                # Ensure the usage table exists
                await pool.execute("""
                    CREATE TABLE IF NOT EXISTS provider_usage (
                        id SERIAL PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        category TEXT NOT NULL,
                        provider_name TEXT NOT NULL,
                        total_requests INT DEFAULT 0,
                        successful_requests INT DEFAULT 0,
                        failed_requests INT DEFAULT 0,
                        total_latency_ms DOUBLE PRECISION DEFAULT 0,
                        method_breakdown JSONB DEFAULT '{}',
                        period_start DOUBLE PRECISION,
                        flushed_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                # Insert all accumulated records
                for key, rec in self._records.items():
                    methods = dict(self._method_counts.get(key, {}))
                    await pool.execute(
                        """INSERT INTO provider_usage
                           (tenant_id, category, provider_name, total_requests,
                            successful_requests, failed_requests, total_latency_ms,
                            method_breakdown, period_start)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)""",
                        rec.tenant_id, rec.category, rec.provider_name,
                        rec.total_requests, rec.successful_requests,
                        rec.failed_requests, rec.total_latency_ms,
                        json.dumps(methods), rec.period_start,
                    )
                count = len(self._records)
                self._records.clear()
                self._method_counts.clear()
                logger.info(f"Usage meter flushed {count} records to PostgreSQL")
            except Exception as e:
                logger.error(f"Usage meter flush failed: {e} — retaining in-memory records")
        else:
            logger.debug(f"Usage meter: {len(self._records)} records (no DB, retained in memory)")

        self._last_flush = time.time()
