"""Durable JSONB fact repository for the semantic Silver/Gold tables.

Imitates ``services/measurement/repositories/activity_repo.py`` (idempotent
``ON CONFLICT DO NOTHING`` against a partial unique index, tenant scoping, and a
``get_pool() is None`` in-memory fallback) but for the generic
``(id, tenant_id, source_event_id, subject_ref, campaign_id, occurred_at,
data JSONB, created_at, updated_at)`` shape shared by every semantic fact table.

A ``fact`` dict passed to :meth:`upsert` must contain: ``id``, ``tenant_id``,
optionally ``source_event_id`` / ``subject_ref`` / ``campaign_id`` /
``occurred_at`` / ``idempotency_key``, and ``data`` (the full model payload).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import _IN_MEMORY_STORES, get_pool
from shared.logger.logger import get_logger

logger = get_logger("aether.semantic.fact_repo")

# Silver fact tables are append-only evidence; Gold state tables are recomputable
# projections (an identity merge / reducer pass re-derives them).
_GOLD_MODE = "gold"
_SILVER_MODE = "silver"


def _reducer_version_of(data: dict[str, Any]) -> Optional[str]:
    """Reducer version lives at data top level or under semantic_delta."""
    value = data.get("reducer_version")
    if value is None:
        delta = data.get("semantic_delta")
        if isinstance(delta, dict):
            value = delta.get("reducer_version")
    return str(value) if value is not None else None


def _reducer_suffix(version: str) -> Optional[tuple[str, int]]:
    """Split 'weighted-reducer.v3' -> ('weighted-reducer', 3); None if unparseable."""
    prefix, sep, tail = version.rpartition(".v")
    if not sep or not tail.isdigit():
        return None
    return prefix, int(tail)


def incoming_supersedes(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """Whether an incoming gold payload may overwrite the persisted one.

    Version-checked upsert: a stale writer (old replay, outdated reducer) must
    not clobber newer state. Rules, checked in order:

    - ``version`` (schema version, int): incoming < existing → refuse.
    - Same/absent ``version``: reducer versions with a shared prefix and a
      numeric ``.vN`` suffix are ordered by suffix; incoming < existing → refuse.
    - Anything not comparable (missing fields, different reducer families,
      unparseable values — i.e. legacy rows) keeps last-write-wins.
    """
    try:
        ev, iv = existing.get("version"), incoming.get("version")
        if isinstance(ev, int) and isinstance(iv, int):
            if iv < ev:
                return False
            if iv > ev:
                return True
        er, ir = _reducer_version_of(existing), _reducer_version_of(incoming)
        if er is not None and ir is not None and er != ir:
            eparsed, iparsed = _reducer_suffix(er), _reducer_suffix(ir)
            if (
                eparsed is not None
                and iparsed is not None
                and eparsed[0] == iparsed[0]
                and iparsed[1] < eparsed[1]
            ):
                return False
    except Exception:  # pragma: no cover — malformed payloads keep LWW
        return True
    return True


class SemanticFactRepository:
    """Idempotent durable storage for one semantic fact table.

    ``mode='silver'`` → ``ON CONFLICT DO NOTHING`` (immutable observations).
    ``mode='gold'``   → ``ON CONFLICT DO UPDATE`` (recomputable aggregate state).
    """

    def __init__(self, table_name: str, *, mode: str = _SILVER_MODE) -> None:
        self.table_name = table_name
        self.mode = mode
        # Share one dict per table so cross-module reads see one consistent view
        # locally (identical to repositories.repos.BaseRepository semantics).
        self._store: dict[str, dict[str, Any]] = _IN_MEMORY_STORES.setdefault(table_name, {})

    async def _pool(self) -> Any:
        return await get_pool()

    # ── writes ────────────────────────────────────────────────────────────────

    async def upsert(self, fact: dict[str, Any]) -> dict[str, Any]:
        """Insert (or, for gold, refresh) one fact row, idempotent on idempotency_key."""
        record_id = str(fact.get("id") or "")
        tenant_id = fact.get("tenant_id")
        idem = _idem_key(fact)
        data = fact.get("data") or {}
        pool = await self._pool()

        if pool is None:
            existing_id = self._find_by_idem(tenant_id, idem)
            if existing_id is not None:
                if self.mode == _GOLD_MODE:
                    existing_data = (self._store[existing_id] or {}).get("data") or {}
                    if not incoming_supersedes(existing_data, data):
                        logger.debug(
                            "semantic_gold_upsert_skipped_stale",
                            extra={"table": self.table_name, "id": existing_id},
                        )
                        return self._store[existing_id]
                    self._store[existing_id] = {**fact}
                    return self._store[existing_id]
                return self._store[existing_id]
            self._store[record_id] = {**fact}
            return self._store[record_id]

        occurred_at = _parse_ts(fact.get("occurred_at"))
        params = (
            record_id,
            tenant_id,
            fact.get("source_event_id"),
            fact.get("subject_ref"),
            fact.get("campaign_id"),
            occurred_at,
            json.dumps(data),
        )
        # The idempotency index is PARTIAL — the ON CONFLICT target MUST repeat the
        # predicate so asyncpg can infer it (see plan Risk #2).
        conflict = (
            "ON CONFLICT (tenant_id, (data->>'idempotency_key')) "
            "WHERE data->>'idempotency_key' IS NOT NULL "
        )
        if self.mode == _GOLD_MODE:
            conflict += (
                "DO UPDATE SET data = EXCLUDED.data, "
                "source_event_id = EXCLUDED.source_event_id, "
                "subject_ref = EXCLUDED.subject_ref, "
                "campaign_id = EXCLUDED.campaign_id, "
                "occurred_at = EXCLUDED.occurred_at, "
                "updated_at = NOW()"
            )
        else:
            conflict += "DO NOTHING"
        sql = (
            f"INSERT INTO {self.table_name} "
            "(id, tenant_id, source_event_id, subject_ref, campaign_id, occurred_at, data) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb) "
            f"{conflict}"
        )
        async with pool.acquire() as conn:
            async with conn.transaction():
                if self.mode == _GOLD_MODE and idem is not None:
                    # Version-checked upsert: lock the row and refuse a stale
                    # overwrite before the ON CONFLICT DO UPDATE can clobber it.
                    # First-insert races fall through to the upsert, which is
                    # idempotent on idempotency_key.
                    existing = await conn.fetchrow(
                        f"SELECT data FROM {self.table_name} "
                        "WHERE tenant_id = $1 AND data->>'idempotency_key' = $2 "
                        "FOR UPDATE",
                        tenant_id,
                        idem,
                    )
                    if existing is not None and not incoming_supersedes(
                        json.loads(existing["data"]), data
                    ):
                        logger.debug(
                            "semantic_gold_upsert_skipped_stale",
                            extra={"table": self.table_name, "tenant_id": tenant_id},
                        )
                        return {
                            "id": record_id,
                            "tenant_id": tenant_id,
                            "data": json.loads(existing["data"]),
                        }
                await conn.execute(sql, *params)
                row = await conn.fetchrow(
                    f"SELECT data FROM {self.table_name} "
                    "WHERE tenant_id = $1 AND data->>'idempotency_key' = $2",
                    tenant_id,
                    idem,
                )
        if row is not None:
            return {"id": record_id, "tenant_id": tenant_id, "data": json.loads(row["data"])}
        return fact

    async def supersede(self, tenant_id: str, idempotency_key: str, superseded_by: str) -> bool:
        """Monotonic status transition classified→superseded + superseded_by ref."""
        pool = await self._pool()
        if pool is None:
            changed = False
            for row in self._store.values():
                data = row.get("data", {})
                if (
                    row.get("tenant_id") == tenant_id
                    and data.get("idempotency_key") == idempotency_key
                    and data.get("status") != "superseded"
                ):
                    data["status"] = "superseded"
                    data["superseded_by"] = superseded_by
                    changed = True
            return changed
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE {self.table_name}
                SET data = jsonb_set(
                        jsonb_set(data, '{{status}}', '"superseded"'),
                        '{{superseded_by}}', to_jsonb($3::text)),
                    updated_at = NOW()
                WHERE tenant_id = $1
                  AND data->>'idempotency_key' = $2
                  AND data->>'status' <> 'superseded'
                """,
                tenant_id,
                idempotency_key,
                superseded_by,
            )
        return result != "UPDATE 0"

    async def tombstone_by_subject(self, tenant_id: str, subject_ref: str) -> int:
        """Consent-restriction: mark a subject's rows consent_restricted (reversible)."""
        return await self._set_status_by_subject(tenant_id, subject_ref, "consent_restricted")

    async def delete_by_subject(self, tenant_id: str, subject_ref: str) -> int:
        """Erasure: hard-delete a subject's rows in this table."""
        pool = await self._pool()
        if pool is None:
            victims = [
                rid
                for rid, row in self._store.items()
                if row.get("tenant_id") == tenant_id and _row_subject(row) == subject_ref
            ]
            for rid in victims:
                del self._store[rid]
            return len(victims)
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {self.table_name} WHERE tenant_id = $1 AND subject_ref = $2",
                tenant_id,
                subject_ref,
            )
        return _rowcount(result)

    async def delete_by_actor(self, tenant_id: str, actor_ref: str) -> int:
        """Erasure: hard-delete rows a subject authored/acted on (data->>'actor_ref')."""
        pool = await self._pool()
        if pool is None:
            victims = [
                rid
                for rid, row in self._store.items()
                if row.get("tenant_id") == tenant_id and _row_actor(row) == actor_ref
            ]
            for rid in victims:
                del self._store[rid]
            return len(victims)
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {self.table_name} "
                "WHERE tenant_id = $1 AND data->>'actor_ref' = $2",
                tenant_id,
                actor_ref,
            )
        return _rowcount(result)

    async def tombstone_by_actor(self, tenant_id: str, actor_ref: str) -> int:
        """Consent-restriction: mark rows a subject acted on consent_restricted."""
        pool = await self._pool()
        if pool is None:
            count = 0
            for row in self._store.values():
                if row.get("tenant_id") == tenant_id and _row_actor(row) == actor_ref:
                    row.setdefault("data", {})["status"] = "consent_restricted"
                    count += 1
            return count
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE {self.table_name}
                SET data = jsonb_set(data, '{{status}}', to_jsonb('consent_restricted'::text)),
                    updated_at = NOW()
                WHERE tenant_id = $1 AND data->>'actor_ref' = $2
                """,
                tenant_id,
                actor_ref,
            )
        return _rowcount(result)

    async def _set_status_by_subject(self, tenant_id: str, subject_ref: str, status: str) -> int:
        pool = await self._pool()
        if pool is None:
            count = 0
            for row in self._store.values():
                if row.get("tenant_id") == tenant_id and _row_subject(row) == subject_ref:
                    row.setdefault("data", {})["status"] = status
                    count += 1
            return count
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE {self.table_name}
                SET data = jsonb_set(data, '{{status}}', to_jsonb($3::text)), updated_at = NOW()
                WHERE tenant_id = $1 AND subject_ref = $2
                """,
                tenant_id,
                subject_ref,
                status,
            )
        return _rowcount(result)

    # ── reads ─────────────────────────────────────────────────────────────────

    async def list_by_tenant(
        self, tenant_id: str, subject: Optional[str] = None, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            rows = [
                row
                for row in self._store.values()
                if row.get("tenant_id") == tenant_id
                and (subject is None or _row_subject(row) == subject)
            ]
            rows.sort(key=lambda r: str((r.get("data") or {}).get("occurred_at", "")))
            return [r.get("data", {}) for r in rows[:limit]]
        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        if subject is not None:
            conditions.append("subject_ref = $2")
            params.append(subject)
        params.append(limit)
        sql = (
            f"SELECT data FROM {self.table_name} WHERE {' AND '.join(conditions)} "
            f"ORDER BY occurred_at ASC NULLS LAST, id ASC LIMIT ${len(params)}"
        )
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [json.loads(r["data"]) for r in rows]

    async def find_by_source_event(
        self, tenant_id: str, source_event_id: str
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            return [
                row.get("data", {})
                for row in self._store.values()
                if row.get("tenant_id") == tenant_id
                and row.get("source_event_id") == source_event_id
            ]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT data FROM {self.table_name} "
                "WHERE tenant_id = $1 AND source_event_id = $2",
                tenant_id,
                source_event_id,
            )
        return [json.loads(r["data"]) for r in rows]

    async def aggregate_counts(self, tenant_id: Optional[str] = None) -> dict[str, Any]:
        """Honest counts for fleet-health: total, tenants, and per-status breakdown."""
        pool = await self._pool()
        if pool is None:
            rows = [
                row
                for row in self._store.values()
                if tenant_id is None or row.get("tenant_id") == tenant_id
            ]
            status_counts: dict[str, int] = {}
            for row in rows:
                status = str((row.get("data") or {}).get("status", "unknown"))
                status_counts[status] = status_counts.get(status, 0) + 1
            return {
                "total": len(rows),
                "tenants": len({r.get("tenant_id") for r in rows}),
                "by_status": status_counts,
            }
        where = "" if tenant_id is None else "WHERE tenant_id = $1"
        args: list[Any] = [] if tenant_id is None else [tenant_id]
        async with pool.acquire() as conn:
            total_row = await conn.fetchrow(
                f"SELECT COUNT(*) AS c, COUNT(DISTINCT tenant_id) AS t "
                f"FROM {self.table_name} {where}",
                *args,
            )
            status_rows = await conn.fetch(
                f"SELECT data->>'status' AS status, COUNT(*) AS c "
                f"FROM {self.table_name} {where} GROUP BY data->>'status'",
                *args,
            )
        return {
            "total": total_row["c"] if total_row else 0,
            "tenants": total_row["t"] if total_row else 0,
            "by_status": {r["status"] or "unknown": r["c"] for r in status_rows},
        }

    # ── in-memory helpers ──────────────────────────────────────────────────────

    def _find_by_idem(self, tenant_id: Any, idem: Optional[str]) -> Optional[str]:
        if not idem:
            return None
        for rid, row in self._store.items():
            if row.get("tenant_id") == tenant_id and _idem_key(row) == idem:
                return rid
        return None


# ── module helpers ──────────────────────────────────────────────────────────────


def _idem_key(fact: dict[str, Any]) -> Optional[str]:
    if fact.get("idempotency_key"):
        return str(fact["idempotency_key"])
    data = fact.get("data") or {}
    return str(data["idempotency_key"]) if data.get("idempotency_key") else None


def _row_subject(row: dict[str, Any]) -> Optional[str]:
    if row.get("subject_ref"):
        return str(row["subject_ref"])
    data = row.get("data") or {}
    return (
        data.get("primary_subject_ref")
        or data.get("target_subject_ref")
        or data.get("subject_ref")
    )


def _row_actor(row: dict[str, Any]) -> Optional[str]:
    data = row.get("data") or {}
    return data.get("actor_ref")


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _rowcount(result: str) -> int:
    try:
        return int(result.split()[-1])
    except (IndexError, ValueError, AttributeError):
        return 0
