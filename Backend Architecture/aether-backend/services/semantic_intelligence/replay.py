"""Semantic replay / historical backfill runner.

Replays durable Bronze SDK events through the semantic pipeline for reprocessing
(new model/taxonomy versions) or historical backfill. Supports dry-run (counts
only, zero writes), tenant / event-family / time filters, and durable progress
with pause / resume / cancel. Reads ONLY Bronze and writes ONLY semantic facts,
so it never contends with live ingestion's Bronze/outbox write path.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from repositories.repos import _IN_MEMORY_STORES, get_pool
from shared.logger.logger import get_logger

from .consumer import SemanticEventConsumer
from .repositories.replay_repo import SemanticReplayJobRepository
from shared.events.events import Event, Topic

logger = get_logger("aether.semantic.replay")

_BRONZE_TABLE = "bronze_sdk_events"
_BATCH = 200


def _matches(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    families = filters.get("families")
    if families and row.get("event_family") not in families:
        return False
    from_time = filters.get("from_time")
    to_time = filters.get("to_time")
    ts = str(row.get("received_at") or row.get("event_timestamp") or "")
    if from_time and ts and ts < str(from_time):
        return False
    if to_time and ts and ts > str(to_time):
        return False
    return True


async def _iter_bronze(tenant_id: str, filters: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        store = _IN_MEMORY_STORES.setdefault(_BRONZE_TABLE, {})
        rows = [r for r in store.values() if r.get("tenant_id") == tenant_id and _matches(r, filters)]
        rows.sort(key=lambda r: str(r.get("received_at", "")))
        for row in rows:
            yield row
        return
    async with pool.acquire() as conn:
        db_rows = await conn.fetch(
            f"SELECT tenant_id, event_id, event_type, event_family, event_timestamp, "
            f"received_at, payload FROM {_BRONZE_TABLE} WHERE tenant_id = $1 "
            "ORDER BY received_at ASC",
            tenant_id,
        )
    for r in db_rows:
        row = dict(r)
        payload = row.get("payload")
        row["payload"] = payload if isinstance(payload, dict) else (json.loads(payload) if payload else {})
        if _matches(row, filters):
            yield row


def _event_from_bronze(row: dict[str, Any]) -> Event:
    payload = row.get("payload") or {}
    if "event_type" not in payload and row.get("event_type"):
        payload = {**payload, "event_type": row["event_type"]}
    return Event(topic=Topic.SDK_EVENTS_VALIDATED, tenant_id=row.get("tenant_id", ""), payload=payload)


class SemanticReplayRunner:
    """Executes a single replay job against durable Bronze events."""

    def __init__(self, jobs: Optional[SemanticReplayJobRepository] = None) -> None:
        self._jobs = jobs or SemanticReplayJobRepository()
        self._consumer = SemanticEventConsumer()

    async def run(self, tenant_id: str, job_id: str) -> dict[str, Any]:
        job = await self._jobs.get(tenant_id, job_id)
        if job is None:
            raise ValueError(f"replay job not found: {job_id}")
        dry_run = bool(job.get("dry_run", True))
        filters = job.get("filters") or {}
        progress = {"scanned": 0, "replayed": 0, "skipped": 0}
        await self._jobs.update(tenant_id, job_id, status="running", progress=progress)

        since_check = 0
        async for row in _iter_bronze(tenant_id, filters):
            # Honour pause/cancel between batches (durable control).
            since_check += 1
            if since_check >= _BATCH:
                since_check = 0
                current = await self._jobs.get(tenant_id, job_id)
                state = (current or {}).get("status")
                if state == "paused":
                    await self._jobs.update(tenant_id, job_id, progress=progress)
                    return {**progress, "status": "paused"}
                if state == "cancelled":
                    await self._jobs.update(tenant_id, job_id, progress=progress)
                    return {**progress, "status": "cancelled"}

            progress["scanned"] += 1
            if dry_run:
                progress["replayed"] += 1  # would-replay count
                continue
            try:
                await self._consumer.on_validated_event(_event_from_bronze(row))
                progress["replayed"] += 1
            except Exception:
                logger.exception("replay failed for event %s", row.get("event_id"))
                progress["skipped"] += 1

        final_status = "completed"
        await self._jobs.update(tenant_id, job_id, status=final_status, progress=progress)
        return {**progress, "status": final_status}
