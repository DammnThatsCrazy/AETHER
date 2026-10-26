"""Communication360FactsRepository — durable access to the Phase-3 canonical
``communication360_facts`` table.

This is the canonical-authority fact store for the read-only ``communication360``
projection (registry row ``communication360``): it persists the Phase-2 ratified
object families (``services/api/journeys/communication360/contracts.py``) as typed JSONB
rows and is consumed read-mostly by the Phase-4 provider and the Phase-5/6
logic (acts extraction, knowledge/context ladders, delegation authority,
provider capability/quality). The shipped message spine stays a typed read-over
of ``silver_comms_facts`` via ``services/api/journeys/comms`` — never duplicated here.

Production: asyncpg against PostgreSQL. Local/test: in-memory module store (same
interface, first-write-wins per ``(tenant_id, idempotency_key)`` mirroring
``ON CONFLICT ... DO NOTHING``), mirroring ``CommsFactsRepository``'s
established pattern. All queries are tenant-scoped; the fact spine is
``(tenant_id, kind, occurred_at)``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from repositories.repos import get_pool

# In-memory fallback (local/test only — production requires a pool). Keyed by
# ``{tenant_id}:{idempotency_key}`` so replay is idempotent just like the
# SQL ``ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`` path.
_local_facts: dict[str, dict[str, Any]] = {}


def reset_local_stores() -> None:
    """Test helper — clears the in-memory fallback store."""
    _local_facts.clear()


_FACT_COLUMNS: tuple[str, ...] = (
    "fact_id", "tenant_id", "kind", "source_event_id", "source_event_type",
    "actor_id", "agent_id", "occurred_at", "received_at", "idempotency_key",
    "run_id", "context_hash", "payload",
)

_JSON_COLUMNS = {"payload"}


class Communication360FactsRepository:
    """Durable storage over the ``communication360_facts`` canonical table."""

    async def _pool(self):
        return await get_pool()

    # ── Write ────────────────────────────────────────────────────────────────

    async def upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert or ignore on ``(tenant_id, idempotency_key)`` conflict — replay safe.

        ``fact_id`` and ``received_at`` are defaulted when the caller omits them
        (mirroring the silver-fact repository); ``payload`` is JSON-encoded for
        the typed JSONB column. First write wins, matching
        ``ON CONFLICT ... DO NOTHING``.
        """
        row.setdefault("fact_id", str(uuid4()))
        row.setdefault("received_at", datetime.now(timezone.utc).isoformat())
        key = f"{row.get('tenant_id')}:{row.get('idempotency_key')}"

        pool = await self._pool()
        if pool is None:
            # Idempotent local write — first write wins, mirroring DO NOTHING.
            _local_facts.setdefault(key, row)
            return _local_facts[key]

        cols = [c for c in _FACT_COLUMNS if c in row]
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
        values = [_bind_fact_column(column, row[column]) for column in cols]
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO communication360_facts ({', '.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                """,
                *values,
            )
        return row

    async def upsert_many(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert a related fact batch atomically with per-row replay keys.

        Participant rosters are validated and resolved as a whole before this
        method is called. A database error must not leave only some roles from
        one roster visible, so PostgreSQL inserts share a transaction. The
        local fallback preserves the existing first-write-wins semantics.
        """
        prepared: list[dict[str, Any]] = []
        for source_row in rows:
            row = dict(source_row)
            row.setdefault("fact_id", str(uuid4()))
            row.setdefault("received_at", datetime.now(timezone.utc).isoformat())
            prepared.append(row)
        if not prepared:
            return []

        pool = await self._pool()
        if pool is None:
            stored: list[dict[str, Any]] = []
            for row in prepared:
                key = f"{row.get('tenant_id')}:{row.get('idempotency_key')}"
                _local_facts.setdefault(key, row)
                stored.append(_local_facts[key])
            return stored

        columns = [column for column in _FACT_COLUMNS if column in prepared[0]]
        if any([column for column in _FACT_COLUMNS if column in row] != columns for row in prepared):
            raise ValueError("all Communication360 fact rows in a batch must share columns")
        placeholders = ", ".join(f"${index + 1}" for index in range(len(columns)))
        sql = f"""
            INSERT INTO communication360_facts ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
        """
        async with pool.acquire() as conn:
            async with conn.transaction():
                for row in prepared:
                    values = [_bind_fact_column(column, row[column]) for column in columns]
                    await conn.execute(sql, *values)
        return prepared

    # ── Read ─────────────────────────────────────────────────────────────────

    async def query(
        self,
        tenant_id: str,
        kind: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Tenant-scoped facts ordered by ``occurred_at`` (ascending).

        Filters compose on ``kind`` and ``occurred_at >= since`` (the Phase-5/6
        consumers scan the canonical spine chronologically); ``limit`` caps the
        page when given.
        """
        pool = await self._pool()
        if pool is None:
            rows = [
                r for r in _local_facts.values()
                if r.get("tenant_id") == tenant_id
                and (kind is None or r.get("kind") == kind)
                and (since is None or str(r.get("occurred_at") or "") >= str(since))
            ]
            rows.sort(key=lambda r: (str(r.get("occurred_at") or ""), str(r.get("fact_id") or "")))
            if limit is not None:
                rows = rows[:limit]
            return rows

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        if kind is not None:
            params.append(kind)
            conditions.append(f"kind = ${len(params)}")
        if since is not None:
            params.append(_parse_ts(since))
            conditions.append(f"occurred_at >= ${len(params)}")
        if limit is not None:
            params.append(int(limit))
            limit_clause = f" LIMIT ${len(params)}"
        else:
            limit_clause = ""
        sql = f"""
            SELECT * FROM communication360_facts
            WHERE {' AND '.join(conditions)}
            ORDER BY occurred_at ASC
            {limit_clause}
        """
        async with pool.acquire() as conn:
            records = await conn.fetch(sql, *params)
        return [dict(r) for r in records]

    async def get(self, tenant_id: str, fact_id: str) -> Optional[dict[str, Any]]:
        """Fetch one fact by its natural ``(tenant_id, fact_id)`` key."""
        pool = await self._pool()
        if pool is None:
            for r in _local_facts.values():
                if r.get("tenant_id") == tenant_id and r.get("fact_id") == fact_id:
                    return r
            return None
        async with pool.acquire() as conn:
            rec = await conn.fetchrow(
                """
                SELECT * FROM communication360_facts
                WHERE tenant_id = $1 AND fact_id = $2
                """,
                tenant_id, fact_id,
            )
        return dict(rec) if rec else None

    async def participant_bindings_for_conversations(
        self,
        tenant_id: str,
        provider: str,
        provider_account_id: str,
        conversation_ids: list[str],
        *,
        limit: int = 500,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Read participant bindings for exact provider conversation scopes.

        This is deliberately narrower than ``query(tenant_id, kind=...)`` so
        consumers can join an already-authorized provider conversation without
        scanning or correlating the tenant's unrelated participant rosters.
        ``complete`` means the bounded store query fit within ``limit``; it is
        not a claim that the provider supplied a complete roster or full history.
        """
        exact_tenant = str(tenant_id or "").strip()
        exact_provider = str(provider or "").strip()
        exact_account = str(provider_account_id or "").strip()
        exact_conversations = sorted(
            {
                str(value).strip()
                for value in conversation_ids
                if isinstance(value, str) and value.strip()
            }
        )
        if not exact_tenant or not exact_provider or not exact_account or not exact_conversations:
            return [], True
        if len(exact_conversations) > 500:
            return [], False
        bounded_limit = min(max(int(limit), 1), 500)

        def _matches(row: dict[str, Any]) -> bool:
            payload = row.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    return False
            return (
                row.get("tenant_id") == exact_tenant
                and row.get("kind") == "participant_binding"
                and isinstance(payload, dict)
                and payload.get("provider") == exact_provider
                and payload.get("provider_account_id") == exact_account
                and payload.get("provider_conversation_id") in exact_conversations
                and payload.get("communication_scope_kind") == "provider_conversation"
                and payload.get("communication_scope") == payload.get("provider_conversation_id")
            )

        pool = await self._pool()
        if pool is None:
            rows = [row for row in _local_facts.values() if _matches(row)]
            rows.sort(
                key=lambda row: (
                    str(row.get("occurred_at") or ""),
                    str(row.get("fact_id") or ""),
                ),
                reverse=True,
            )
            return rows[:bounded_limit], len(rows) <= bounded_limit

        async with pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT * FROM communication360_facts
                WHERE tenant_id = $1
                  AND kind = 'participant_binding'
                  AND payload->>'provider' = $2
                  AND payload->>'provider_account_id' = $3
                  AND payload->>'provider_conversation_id' = ANY($4::text[])
                  AND payload->>'communication_scope_kind' = 'provider_conversation'
                  AND payload->>'communication_scope' = payload->>'provider_conversation_id'
                ORDER BY occurred_at DESC, fact_id DESC
                LIMIT $5
                """,
                exact_tenant,
                exact_provider,
                exact_account,
                exact_conversations,
                bounded_limit + 1,
            )
        fetched = [dict(record) for record in records]
        return fetched[:bounded_limit], len(fetched) <= bounded_limit

    async def facts_for_exact_reference(
        self,
        tenant_id: str,
        reference_kind: str,
        reference_id: str,
        *,
        after: Any = None,
        before: Any = None,
        received_before: Any = None,
        limit: int = 200,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Read facts carrying one exact typed journey or episode reference.

        The relationship is admitted only through the canonical JSONB
        ``journey_id(s)`` / ``episode_id(s)`` fields. This does not match
        arbitrary strings or search payload text. Returned ``complete`` only
        describes this bounded exact-reference query; it is not a claim that a
        communication authority has recorded every real-world conversation.
        """
        exact_tenant = str(tenant_id or "").strip()
        exact_id = str(reference_id or "").strip()
        field_names = {
            "episode": ("episode_id", "episode_ids"),
            "journey": ("journey_id", "journey_ids"),
        }.get(reference_kind)
        if not exact_tenant or not exact_id or field_names is None:
            return [], True
        bounded_limit = min(max(int(limit), 1), 500)
        singular, plural = field_names

        def _timestamp(value: Any) -> Optional[datetime]:
            if isinstance(value, datetime):
                parsed = value
            elif isinstance(value, str):
                parsed = _parse_ts(value)
            else:
                return None
            if parsed is None or parsed.tzinfo is None:
                return None
            return parsed.astimezone(timezone.utc)

        after_ts = _timestamp(after) if after is not None else None
        before_ts = _timestamp(before) if before is not None else None
        received_before_ts = (
            _timestamp(received_before) if received_before is not None else None
        )
        if (
            (after is not None and after_ts is None)
            or (before is not None and before_ts is None)
            or (received_before is not None and received_before_ts is None)
        ):
            return [], False

        def _matches(row: dict[str, Any]) -> bool:
            payload = row.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    return False
            if not isinstance(payload, dict):
                return False
            values = payload.get(plural)
            exact_match = payload.get(singular) == exact_id or (
                isinstance(values, list) and exact_id in values
            )
            if not exact_match:
                return False
            occurred_at = _timestamp(row.get("occurred_at"))
            received_at = _timestamp(row.get("received_at"))
            if after_ts is not None and (occurred_at is None or occurred_at <= after_ts):
                return False
            if before_ts is not None and (occurred_at is None or occurred_at >= before_ts):
                return False
            if received_before_ts is not None and (
                received_at is None or received_at > received_before_ts
            ):
                return False
            return True

        pool = await self._pool()
        if pool is None:
            rows = [
                row
                for row in _local_facts.values()
                if row.get("tenant_id") == exact_tenant and _matches(row)
            ]
            rows.sort(
                key=lambda row: (
                    str(row.get("occurred_at") or ""),
                    str(row.get("fact_id") or ""),
                )
            )
            return rows[:bounded_limit], len(rows) <= bounded_limit

        conditions = [
            "tenant_id = $1",
            f"(payload->>'{singular}' = $2 OR COALESCE(payload->'{plural}', '[]'::jsonb) ? $2)",
        ]
        params: list[Any] = [exact_tenant, exact_id]
        if after is not None:
            params.append(after_ts)
            conditions.append(f"occurred_at > ${len(params)}")
        if before is not None:
            params.append(before_ts)
            conditions.append(f"occurred_at < ${len(params)}")
        if received_before is not None:
            params.append(received_before_ts)
            conditions.append(f"received_at <= ${len(params)}")
        params.append(bounded_limit + 1)
        async with pool.acquire() as conn:
            records = await conn.fetch(
                f"""
                SELECT * FROM communication360_facts
                WHERE {' AND '.join(conditions)}
                ORDER BY occurred_at ASC, fact_id ASC
                LIMIT ${len(params)}
                """,
                *params,
            )
        fetched = [dict(record) for record in records]
        return fetched[:bounded_limit], len(fetched) <= bounded_limit


def _parse_ts(value: Any) -> Any:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value


def _bind_fact_column(column: str, value: Any) -> Any:
    if column in {"occurred_at", "received_at"} and value is not None:
        parsed = _parse_ts(value)
        if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{column} must be a timezone-aware timestamp")
        return parsed.astimezone(timezone.utc)
    if column in _JSON_COLUMNS and value is not None:
        return json.dumps(value)
    return value
