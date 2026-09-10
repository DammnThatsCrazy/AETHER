"""Immutable exploration-result snapshots and deterministic comparison helpers.

Snapshots are a read-model of an executed Exploration Fabric envelope.  They
retain the normalized context and returned data so a later comparison can be
made against the *same* query semantics, rather than asking a caller to rebuild
an equivalent graph query.  The repository deliberately exposes create/get/
list only: replacing or mutating a snapshot would make a historical result
untrustworthy.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now


def canonical_digest(value: Any) -> str:
    """Return a stable digest for JSON-compatible result data."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    # BaseRepository owns an operational updated_at column. It is intentionally
    # not part of the immutable exploration snapshot contract.
    return {k: v for k, v in record.items() if k not in {"id", "updated_at"}}


class ExplorationSnapshotRepository(BaseRepository):
    """Tenant-qualified append-only snapshot records."""

    _memory_lock: Optional[asyncio.Lock] = None
    _memory_lock_loop: Any = None

    def __init__(self) -> None:
        super().__init__("exploration_result_snapshots")

    @staticmethod
    def _record_id(tenant_id: str, snapshot_id: str) -> str:
        return f"{tenant_id}:{snapshot_id}"

    @classmethod
    def _lock(cls) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if cls._memory_lock is None or cls._memory_lock_loop is not loop:
            cls._memory_lock = asyncio.Lock()
            cls._memory_lock_loop = loop
        return cls._memory_lock

    async def create(self, tenant_id: str, snapshot_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not tenant_id or not snapshot_id:
            raise ValueError("tenant_id and snapshot_id are required")
        record = {**data, "tenant_id": tenant_id, "snapshot_id": snapshot_id}
        record_id = self._record_id(tenant_id, snapshot_id)
        pool = await self._ensure_pool()
        if pool is None:
            # The check and insert must be one critical section. BaseRepository
            # insert is an upsert, so a check-then-insert race would otherwise
            # silently replace an immutable historical snapshot.
            async with self._lock():
                if await self.find_by_id(record_id) is not None:
                    raise ValueError("exploration snapshot ids are immutable and cannot be reused")
                stored = await self.insert(record_id, record)
                return _public_record(stored)

        await self._ensure_table()
        now = utc_now().isoformat()
        row = await pool.fetchrow(
            f"""INSERT INTO {self.table_name} (id, data, tenant_id, created_at, updated_at)
                VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
                RETURNING data""",
            record_id,
            json.dumps({**record, "id": record_id, "created_at": now, "updated_at": now}, default=str),
            tenant_id,
        )
        if row is None:
            raise ValueError("exploration snapshot ids are immutable and cannot be reused")
        return _public_record(json.loads(row["data"]))

    async def get_scoped(self, tenant_id: str, snapshot_id: str) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(self._record_id(tenant_id, snapshot_id))
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return _public_record(record)

    async def list_scoped(
        self, tenant_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = await self.find_many(
            filters={"tenant_id": tenant_id}, limit=limit, offset=offset
        )
        return [_public_record(row) for row in rows]


def _keyed_records(data: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        return {}
    records: dict[str, dict[str, Any]] = {}
    for item in data[key]:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        records[str(item["id"])] = item
    return records


def compare_result_data(before: Any, after: Any) -> dict[str, Any]:
    """Compare graph-shaped result data without inventing semantics for others.

    Graph node/edge ids are canonical. Property changes are reported as the
    after-value for each changed key. For non-graph payloads, the caller gets a
    digest-only change record rather than a misleading row-level diff.
    """
    before_nodes = _keyed_records(before, "nodes")
    after_nodes = _keyed_records(after, "nodes")
    before_edges = _keyed_records(before, "edges")
    after_edges = _keyed_records(after, "edges")

    def diff(before_rows: dict[str, dict[str, Any]], after_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
        added = sorted(set(after_rows) - set(before_rows))
        removed = sorted(set(before_rows) - set(after_rows))
        changed: list[dict[str, Any]] = []
        unchanged = 0
        for row_id in sorted(set(before_rows) & set(after_rows)):
            old, new = before_rows[row_id], after_rows[row_id]
            keys = (set(old) | set(new)) - {"id"}
            changed_properties = {
                key: new.get(key)
                for key in sorted(keys)
                if old.get(key) != new.get(key)
            }
            if changed_properties:
                changed.append({"id": row_id, "changed_properties": changed_properties})
            else:
                unchanged += 1
        return {
            "added_ids": added,
            "removed_ids": removed,
            "changed": changed,
            "unchanged_count": unchanged,
        }

    if before_nodes or after_nodes or before_edges or after_edges:
        return {
            "kind": "graph",
            "nodes": diff(before_nodes, after_nodes),
            "edges": diff(before_edges, after_edges),
            "changed": canonical_digest(before) != canonical_digest(after),
        }
    return {
        "kind": "opaque",
        "changed": canonical_digest(before) != canonical_digest(after),
        "before_digest": canonical_digest(before),
        "after_digest": canonical_digest(after),
    }


__all__ = ["ExplorationSnapshotRepository", "canonical_digest", "compare_result_data"]
