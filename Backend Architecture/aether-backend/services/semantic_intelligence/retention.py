"""Semantic retention sweep — age out Silver evidence and Gold projections.

Scheduled maintenance worker (WorkerSpec ``semantic_retention``, gated on
``settings.semantic.retention_enabled``) that ages rows past their
``retention_class`` window (``standard_90d`` => 90 days) measured from
``occurred_at``:

  - Silver observation tables are TOMBSTONED (status -> ``expired``) so the
    immutable evidence trail and its provenance survive the sweep;
  - recomputable Gold projections are DELETED — the reducer path rebuilds them
    from surviving Silver evidence if the subject is still active.

Builds on the ``SemanticFactRepository`` age primitives; all flags default OFF
so the worker stays inert until an operator opts a deployment in.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics

from .models import utc_now
from .repositories.base_fact_repo import SemanticFactRepository

logger = get_logger("aether.semantic.retention")

# Retention windows in days, keyed by an observation's retention_class. Only the
# classes enumerated here are swept; an unknown class is left untouched (fail
# safe — never age out evidence under a policy we do not recognise).
RETENTION_WINDOWS: dict[str, int] = {"standard_90d": 90}
_DEFAULT_GOLD_WINDOW_DAYS = RETENTION_WINDOWS["standard_90d"]
_EXPIRED_STATUS = "expired"

# Silver evidence is tombstoned (provenance-preserving); Gold projections are
# recomputable, so they are deleted and rebuilt by the reducer path on demand.
_SILVER_TABLES = ("silver_semantic_observations", "silver_sentiment_observations")
_GOLD_TABLES = ("gold_entity_semantic_state", "gold_entity_sentiment_state")

_RETENTION_INTERVAL_S = int(os.getenv("SEMANTIC_RETENTION_INTERVAL_S", str(24 * 3600)))


async def sweep_tenant(tenant_id: str, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Age out one tenant's Silver (tombstone) and Gold (delete) rows.

    ``now`` is injectable so tests can drive the cutoff deterministically.
    """
    now = now or utc_now()
    tombstoned: dict[str, int] = {}
    deleted: dict[str, int] = {}

    for table in _SILVER_TABLES:
        repo = SemanticFactRepository(table)
        count = 0
        for retention_class, days in RETENTION_WINDOWS.items():
            cutoff = now - timedelta(days=days)
            count += await repo.tombstone_by_age(
                tenant_id, cutoff, retention_class=retention_class, status=_EXPIRED_STATUS
            )
        if count:
            tombstoned[table] = count

    gold_cutoff = now - timedelta(days=_DEFAULT_GOLD_WINDOW_DAYS)
    for table in _GOLD_TABLES:
        repo = SemanticFactRepository(table, mode="gold")
        count = await repo.delete_by_age(tenant_id, gold_cutoff)
        if count:
            deleted[table] = count

    return {
        "tenant_id": tenant_id,
        "tombstoned": tombstoned,
        "deleted": deleted,
        "tombstoned_total": sum(tombstoned.values()),
        "deleted_total": sum(deleted.values()),
    }


async def sweep_once() -> list[dict[str, Any]]:
    """One retention pass across every tenant with Silver evidence."""
    tenants = await SemanticFactRepository(_SILVER_TABLES[0]).distinct_tenants()
    reports: list[dict[str, Any]] = []
    for tenant_id in tenants:
        report = await sweep_tenant(tenant_id)
        if report["tombstoned_total"] or report["deleted_total"]:
            metrics.increment("semantic_retention_tombstoned_total", report["tombstoned_total"])
            metrics.increment("semantic_retention_deleted_total", report["deleted_total"])
            logger.info("semantic retention sweep: %s", report)
        reports.append(report)
    return reports


async def run_semantic_retention_loop(interval_seconds: Optional[int] = None) -> None:
    """Supervised loop: age out Silver/Gold rows on a fixed interval."""
    interval = int(
        interval_seconds if interval_seconds is not None else _RETENTION_INTERVAL_S
    )
    logger.info("semantic retention worker started interval=%ss", interval)
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover — defensive supervision
            metrics.increment("semantic_retention_error_total")
            logger.error("semantic retention sweep failed: %s", exc, exc_info=True)
        await asyncio.sleep(interval)


def build_semantic_retention_coro() -> Any:
    """Zero-arg coroutine factory for the ``semantic_retention`` WorkerSpec."""
    return run_semantic_retention_loop()
