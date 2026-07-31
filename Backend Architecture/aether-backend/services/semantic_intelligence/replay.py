"""Semantic replay / historical backfill runner.

Replays durable Bronze SDK events through the semantic pipeline for reprocessing
(new model/taxonomy versions) or historical backfill. Supports dry-run (counts
only, zero writes), tenant / event-family / time filters, and durable progress
with pause / resume / cancel. Reads ONLY Bronze and writes ONLY semantic facts,
so it never contends with live ingestion's Bronze/outbox write path.

Resumability: rows are iterated in a stable ``(received_at, event_id)`` order
and the runner tracks a cursor over that key. The ``semantic.replay`` job
handler (services/semantic_intelligence/jobs.py) persists the cursor into the
durable job payload via the ``checkpoint`` callback, so a worker retry/restart
resumes from the last checkpoint instead of row 0.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from repositories.repos import _IN_MEMORY_STORES, get_pool
from shared.logger.logger import get_logger

from .consumer import SemanticEventConsumer
from .repositories.replay_repo import SemanticReplayJobRepository
from shared.events.events import Event, Topic

logger = get_logger("aether.semantic.replay")

_BRONZE_TABLE = "bronze_sdk_events"
_BATCH = 200

# Async callback invoked with the current Bronze cursor (or None before the
# first processed row) whenever the runner reaches a durable checkpoint.
CheckpointFn = Callable[[Optional[dict[str, Any]]], Awaitable[None]]


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


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    """Stable per-row resume key matching the iteration order."""
    return (str(row.get("received_at") or ""), str(row.get("event_id") or ""))


def _cursor_key(cursor: Optional[dict[str, Any]]) -> Optional[tuple[str, str]]:
    if not cursor:
        return None
    return (str(cursor.get("received_at") or ""), str(cursor.get("event_id") or ""))


def _cursor_dict(key: Optional[tuple[str, str]]) -> Optional[dict[str, str]]:
    if key is None:
        return None
    return {"received_at": key[0], "event_id": key[1]}


async def _iter_bronze(tenant_id: str, filters: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        store = _IN_MEMORY_STORES.setdefault(_BRONZE_TABLE, {})
        rows = [r for r in store.values() if r.get("tenant_id") == tenant_id and _matches(r, filters)]
        rows.sort(key=_row_key)
        for row in rows:
            yield row
        return
    async with pool.acquire() as conn:
        db_rows = await conn.fetch(
            f"SELECT tenant_id, event_id, event_type, event_family, event_timestamp, "
            f"received_at, payload FROM {_BRONZE_TABLE} WHERE tenant_id = $1 "
            "ORDER BY received_at ASC, event_id ASC",
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

    async def run(
        self,
        tenant_id: str,
        job_id: str,
        *,
        cursor: Optional[dict[str, Any]] = None,
        checkpoint: Optional[CheckpointFn] = None,
    ) -> dict[str, Any]:
        job = await self._jobs.get(tenant_id, job_id)
        if job is None:
            raise ValueError(f"replay job not found: {job_id}")
        dry_run = bool(job.get("dry_run", True))
        filters = job.get("filters") or {}
        resume_key = _cursor_key(cursor)
        if resume_key is not None:
            # Resuming after an interruption: keep the durably recorded counts
            # instead of double-counting the already-processed prefix.
            stored = job.get("progress") or {}
            progress = {
                "scanned": int(stored.get("scanned") or 0),
                "replayed": int(stored.get("replayed") or 0),
                "skipped": int(stored.get("skipped") or 0),
            }
        else:
            progress = {"scanned": 0, "replayed": 0, "skipped": 0}
        await self._save(tenant_id, job_id, progress, resume_key, status="running")

        since_check = 0
        last_key = resume_key
        async for row in _iter_bronze(tenant_id, filters):
            row_key = _row_key(row)
            if resume_key is not None and row_key <= resume_key:
                continue  # durably processed before the interruption
            # Honour pause/cancel between batches and persist the cursor so a
            # retry/restart resumes here (durable control + durable progress).
            since_check += 1
            if since_check >= _BATCH:
                since_check = 0
                await self._save(tenant_id, job_id, progress, last_key)
                if checkpoint is not None:
                    await checkpoint(_cursor_dict(last_key))
                current = await self._jobs.get(tenant_id, job_id)
                state = (current or {}).get("status")
                if state in ("paused", "cancelled"):
                    return {**progress, "status": state, "cursor": _cursor_dict(last_key)}

            progress["scanned"] += 1
            if dry_run:
                progress["replayed"] += 1  # would-replay count
                last_key = row_key
                continue
            try:
                await self._consumer.on_validated_event(_event_from_bronze(row))
                progress["replayed"] += 1
            except Exception:
                logger.exception("replay failed for event %s", row.get("event_id"))
                progress["skipped"] += 1
            last_key = row_key

        final_status = "completed"
        await self._save(tenant_id, job_id, progress, last_key, status=final_status)
        if checkpoint is not None:
            await checkpoint(_cursor_dict(last_key))
        return {**progress, "status": final_status, "cursor": _cursor_dict(last_key)}

    async def _save(
        self,
        tenant_id: str,
        job_id: str,
        progress: dict[str, Any],
        cursor_key: Optional[tuple[str, str]],
        status: Optional[str] = None,
    ) -> None:
        """Persist progress (+ Bronze cursor) to the replay-job record."""
        stored = dict(progress)
        cursor = _cursor_dict(cursor_key)
        if cursor is not None:
            stored["cursor"] = cursor
        await self._jobs.update(tenant_id, job_id, status=status, progress=stored)
