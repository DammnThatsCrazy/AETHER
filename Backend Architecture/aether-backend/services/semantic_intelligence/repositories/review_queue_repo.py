"""Durable review queue for semantic operations.

Replaces the hardcoded empty ``/v1/kyber/semantic/review-queue`` stub with a
real, tenant-scoped, DB-backed queue. Low-confidence subject/campaign
resolutions, sensitive-inference flags, adversarial-content flags and model
disagreements are enqueued here for operator disposition.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from repositories.repos import _IN_MEMORY_STORES, get_pool

_TABLE = "semantic_review_queue"

# Canonical queue types (Kyber operator surfaces).
QUEUE_TYPES = (
    "ambiguous_subject",
    "campaign_mapping",
    "entity_mapping",
    "low_confidence",
    "sensitive_inference",
    "unsupported_language",
    "conflicting_labels",
    "graph_promotion_candidate",
    "cross_tenant_reference",
    "adversarial_content",
    "model_disagreement",
)


class SemanticReviewQueueRepository:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = _IN_MEMORY_STORES.setdefault(_TABLE, {})

    async def _pool(self) -> Any:
        return await get_pool()

    async def enqueue(
        self,
        tenant_id: str,
        queue_type: str,
        *,
        subject_ref: Optional[str] = None,
        source_event_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        item_id = f"srq_{uuid4().hex}"
        now = datetime.now(timezone.utc)
        data = {
            "id": item_id,
            "tenant_id": tenant_id,
            "queue_type": queue_type,
            "subject_ref": subject_ref,
            "source_event_id": source_event_id,
            "status": "open",
            "payload": payload or {},
            "created_at": now.isoformat(),
        }
        pool = await self._pool()
        if pool is None:
            self._store[item_id] = data
            return data
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {_TABLE}
                    (id, tenant_id, queue_type, subject_ref, source_event_id, status, data)
                VALUES ($1, $2, $3, $4, $5, 'open', $6::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                item_id,
                tenant_id,
                queue_type,
                subject_ref,
                source_event_id,
                json.dumps(data),
            )
        return data

    async def list_open(
        self, tenant_id: str, queue_type: Optional[str] = None, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            rows = [
                row
                for row in self._store.values()
                if row.get("tenant_id") == tenant_id
                and row.get("status") == "open"
                and (queue_type is None or row.get("queue_type") == queue_type)
            ]
            rows.sort(key=lambda r: str(r.get("created_at", "")))
            return rows[:limit]
        conditions = ["tenant_id = $1", "status = 'open'"]
        params: list[Any] = [tenant_id]
        if queue_type is not None:
            conditions.append("queue_type = $2")
            params.append(queue_type)
        params.append(limit)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT data FROM {_TABLE} WHERE {' AND '.join(conditions)} "
                f"ORDER BY created_at ASC LIMIT ${len(params)}",
                *params,
            )
        return [json.loads(r["data"]) for r in rows]

    async def resolve(self, tenant_id: str, item_id: str, disposition: str) -> bool:
        pool = await self._pool()
        if pool is None:
            row = self._store.get(item_id)
            if row is None or row.get("tenant_id") != tenant_id:
                return False
            row["status"] = "resolved"
            row["disposition"] = disposition
            return True
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE {_TABLE}
                SET status = 'resolved',
                    data = jsonb_set(data, '{{disposition}}', to_jsonb($3::text)),
                    updated_at = NOW()
                WHERE tenant_id = $1 AND id = $2
                """,
                tenant_id,
                item_id,
                disposition,
            )
        return result != "UPDATE 0"

    async def purge_by_subject(self, tenant_id: str, subject_ref: str) -> int:
        """Delete all review items for a subject (DSR erasure)."""
        pool = await self._pool()
        if pool is None:
            victims = [
                item_id
                for item_id, row in self._store.items()
                if row.get("tenant_id") == tenant_id and row.get("subject_ref") == subject_ref
            ]
            for item_id in victims:
                del self._store[item_id]
            return len(victims)
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {_TABLE} WHERE tenant_id = $1 AND subject_ref = $2",
                tenant_id,
                subject_ref,
            )
        try:
            return int(result.split()[-1])
        except (IndexError, ValueError):
            return 0

    async def counts(self, tenant_id: str) -> dict[str, int]:
        pool = await self._pool()
        if pool is None:
            counts: dict[str, int] = {}
            for row in self._store.values():
                if row.get("tenant_id") == tenant_id and row.get("status") == "open":
                    qt = str(row.get("queue_type", "unknown"))
                    counts[qt] = counts.get(qt, 0) + 1
            return counts
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT queue_type, COUNT(*) AS c FROM {_TABLE} "
                "WHERE tenant_id = $1 AND status = 'open' GROUP BY queue_type",
                tenant_id,
            )
        return {r["queue_type"]: r["c"] for r in rows}
