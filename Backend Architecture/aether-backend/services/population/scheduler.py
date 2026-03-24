"""
Population Snapshot Scheduler

Automated scheduled snapshots of population membership counts and composition.
Uses asyncio for scheduling. Integrates with existing population registry.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics
from services.population.registry import population_repo, membership_repo
from repositories.repos import BaseRepository

logger = get_logger("aether.population.scheduler")


class SnapshotRepository(BaseRepository):
    """Stores population snapshots."""

    def __init__(self) -> None:
        super().__init__("population_snapshots")


snapshot_repo = SnapshotRepository()


async def take_snapshot(tenant_id: str) -> dict:
    """Take a point-in-time snapshot of all populations for a tenant."""
    now = utc_now().isoformat()
    populations = await population_repo.query_populations(tenant_id=tenant_id, limit=10000)

    snapshot_records = []
    for pop in populations:
        member_count = await membership_repo.count(filters={"population_id": pop["id"]})
        record = {
            "population_id": pop["id"],
            "population_name": pop.get("name", ""),
            "population_type": pop.get("population_type", ""),
            "member_count": member_count,
            "tenant_id": tenant_id,
            "snapshot_at": now,
        }
        import uuid
        await snapshot_repo.insert(str(uuid.uuid4()), record)
        snapshot_records.append(record)

    metrics.increment("population_snapshot_taken", labels={"tenant_id": tenant_id})
    logger.info(f"Population snapshot: {len(snapshot_records)} groups for tenant {tenant_id}")
    return {"snapshot_at": now, "groups_captured": len(snapshot_records), "records": snapshot_records}


async def snapshot_loop(tenant_id: str, interval_seconds: int = 3600) -> None:
    """Run snapshot on a schedule. Call as asyncio.create_task(snapshot_loop(...))."""
    logger.info(f"Population snapshot scheduler started: interval={interval_seconds}s, tenant={tenant_id}")
    while True:
        try:
            await take_snapshot(tenant_id)
        except Exception as e:
            logger.error(f"Population snapshot failed: {e}")
            metrics.increment("population_snapshot_failed")
        await asyncio.sleep(interval_seconds)
