"""Durable semantic replay-job repository.

Backs historical reprocessing: tenant-scoped jobs with dry-run, filters and
durable progress. In-memory fallback for local/CI mirrors the other semantic
repositories.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from repositories.repos import _IN_MEMORY_STORES, get_pool

_TABLE = "semantic_replay_jobs"

TERMINAL_STATUSES = frozenset({"completed", "cancelled", "failed"})


class SemanticReplayJobRepository:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = _IN_MEMORY_STORES.setdefault(_TABLE, {})

    async def _pool(self) -> Any:
        return await get_pool()

    async def create(
        self, tenant_id: str, *, dry_run: bool, filters: dict[str, Any]
    ) -> dict[str, Any]:
        job_id = f"srj_{uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        job = {
            "id": job_id,
            "tenant_id": tenant_id,
            "status": "queued",
            "dry_run": dry_run,
            "filters": filters or {},
            "progress": {"scanned": 0, "replayed": 0, "skipped": 0},
            "created_at": now,
            "updated_at": now,
        }
        pool = await self._pool()
        if pool is None:
            self._store[job_id] = job
            return job
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {_TABLE} (id, tenant_id, status, dry_run, filters, progress)
                VALUES ($1, $2, 'queued', $3, $4::jsonb, $5::jsonb)
                """,
                job_id,
                tenant_id,
                dry_run,
                json.dumps(filters or {}),
                json.dumps(job["progress"]),
            )
        return job

    async def get(self, tenant_id: str, job_id: str) -> Optional[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            job = self._store.get(job_id)
            return job if job and job.get("tenant_id") == tenant_id else None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT id, tenant_id, status, dry_run, filters, progress "
                f"FROM {_TABLE} WHERE tenant_id = $1 AND id = $2",
                tenant_id,
                job_id,
            )
        if row is None:
            return None
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "status": row["status"],
            "dry_run": row["dry_run"],
            "filters": _as_dict(row["filters"]),
            "progress": _as_dict(row["progress"]),
        }

    async def list_by_tenant(self, tenant_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            rows = [j for j in self._store.values() if j.get("tenant_id") == tenant_id]
            rows.sort(key=lambda j: str(j.get("created_at", "")), reverse=True)
            return rows[:limit]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT id, tenant_id, status, dry_run, filters, progress FROM {_TABLE} "
                "WHERE tenant_id = $1 ORDER BY created_at DESC LIMIT $2",
                tenant_id,
                limit,
            )
        return [
            {
                "id": r["id"],
                "tenant_id": r["tenant_id"],
                "status": r["status"],
                "dry_run": r["dry_run"],
                "filters": _as_dict(r["filters"]),
                "progress": _as_dict(r["progress"]),
            }
            for r in rows
        ]

    async def update(
        self,
        tenant_id: str,
        job_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[dict[str, Any]] = None,
    ) -> bool:
        pool = await self._pool()
        if pool is None:
            job = self._store.get(job_id)
            if job is None or job.get("tenant_id") != tenant_id:
                return False
            if status is not None:
                job["status"] = status
            if progress is not None:
                job["progress"] = progress
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            return True
        sets = ["updated_at = NOW()"]
        params: list[Any] = [tenant_id, job_id]
        if status is not None:
            sets.append(f"status = ${len(params) + 1}")
            params.append(status)
        if progress is not None:
            sets.append(f"progress = ${len(params) + 1}::jsonb")
            params.append(json.dumps(progress))
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE {_TABLE} SET {', '.join(sets)} WHERE tenant_id = $1 AND id = $2",
                *params,
            )
        return result != "UPDATE 0"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}
