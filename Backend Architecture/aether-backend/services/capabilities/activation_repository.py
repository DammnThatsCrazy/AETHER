"""Durable repository for capability activation states.

Thin ``BaseRepository`` wrapper over ``capability_activation_states`` (JSONB
store; Postgres in production, shared in-memory locally). Rows are append-only
STATE VERSIONS: exactly one non-superseded row exists per
``(tenant_id, provider, environment, capability)`` coordinate (enforced by a
partial-unique index in Postgres and by the CAS advance here). All transition
legality and precondition enforcement live in the lifecycle authority.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now

ACTIVATION_TABLE = "capability_activation_states"


class ActivationStateRepo(BaseRepository):
    TABLE = ACTIVATION_TABLE

    def __init__(self) -> None:
        super().__init__(self.TABLE)

    async def current(
        self, tenant_id: str, provider: str, environment: str, capability: str
    ) -> Optional[dict]:
        rows = await self.find_many(
            filters={
                "tenant_id": tenant_id,
                "provider": provider,
                "environment": environment,
                "capability": capability,
                "superseded": False,
            },
            limit=2,
        )
        return rows[0] if rows else None

    async def history(
        self, tenant_id: str, provider: str, environment: str, capability: str
    ) -> list[dict]:
        rows = await self.find_many(
            filters={
                "tenant_id": tenant_id,
                "provider": provider,
                "environment": environment,
                "capability": capability,
            },
            limit=500,
        )
        return sorted(rows, key=lambda r: int(r.get("state_version", 0)), reverse=True)

    async def current_for_tenant(self, tenant_id: str) -> list[dict]:
        return await self.find_many(
            filters={"tenant_id": tenant_id, "superseded": False}, limit=1000
        )

    async def current_page(
        self, limit: int = 1000, after_id: Optional[str] = None
    ) -> list[dict]:
        """Cross-tenant current states (operator surfaces only), KEYSET-paged.

        Ordered by the row's unique ``id`` ascending, returning rows with
        ``id > after_id``. A keyset cursor (not a numeric offset) keeps paging
        stable while transitions concurrently supersede old rows and insert new
        ones: an offset would duplicate or skip rows as the current-state set
        shifts, and ``created_at`` is not unique for ties. The id is unique and
        immutable, so successive pages neither overlap nor gap.
        """
        pool = await self._ensure_pool()
        if pool is None:
            rows = [
                r for r in self._store.values()
                if not r.get("superseded")
                and (after_id is None or str(r.get("id", "")) > after_id)
            ]
            rows.sort(key=lambda r: str(r.get("id", "")))
            return rows[:limit]

        await self._ensure_table()
        params: list = []
        cond = "(data->>'superseded') = 'false'"
        if after_id:
            cond += " AND id > $1"
            params.append(after_id)
        query = (
            f"SELECT data FROM {self.table_name} WHERE {cond} "
            f"ORDER BY id ASC LIMIT {int(limit)}"
        )
        fetched = await pool.fetch(query, *params)
        return [json.loads(r["data"]) for r in fetched]

    async def advance(self, prior: Optional[dict], new_row: dict) -> dict:
        """Append the next state version, superseding ``prior`` — ATOMICALLY.

        Compare-and-set: refuses when ``prior`` is no longer the current row
        (a concurrent transition won), so histories stay linear.

        The supersede and the insert happen in ONE database transaction, so a
        process/connection interruption between them can never leave the
        coordinate with zero current rows (which would make reads fall back to
        ``credential_waiting`` and silently drop an effective suspended/live
        state and its kill-switch projection). The partial-unique index
        ``uq_capability_activation_states_current`` backstops the CAS: a lost
        race can't insert a second non-superseded row for the coordinate.
        """
        coordinate = {
            k: new_row[k] for k in ("tenant_id", "provider", "environment", "capability")
        }
        row_id = f"cas_{uuid.uuid4().hex}"
        pool = await self._ensure_pool()

        if pool is None:
            # In-memory single-process store: no durability and no crash window
            # between two dict writes, so the sequential CAS is sufficient.
            live = await self.current(**coordinate)
            if (live or {}).get("id") != (prior or {}).get("id"):
                raise ConcurrentTransitionError(
                    f"activation state for {coordinate} changed concurrently"
                )
            if prior is not None:
                await self.update(prior["id"], {"superseded": True})
            return await self.insert(row_id, {**new_row, "superseded": False})

        await self._ensure_table()
        now = utc_now().isoformat()
        new_data = {
            **new_row,
            "superseded": False,
            "id": row_id,
            "created_at": now,
            "updated_at": now,
        }
        tenant_id = new_data.get("tenant_id", "")
        async with pool.acquire() as conn:
            async with conn.transaction():
                if prior is not None:
                    # CAS: only supersede the prior row while it is still the
                    # current (non-superseded) row. A racing transition that
                    # already superseded it leaves 0 rows updated → abort.
                    res = await conn.execute(
                        f"UPDATE {self.table_name} "
                        f"SET data = jsonb_set(data, '{{superseded}}', 'true'::jsonb), "
                        f"    updated_at = NOW() "
                        f"WHERE id = $1 AND (data->>'superseded') = 'false'",
                        prior["id"],
                    )
                    if str(res).split()[-1] == "0":
                        raise ConcurrentTransitionError(
                            f"activation state for {coordinate} changed concurrently"
                        )
                # Insert the new current row. The partial-unique index rejects a
                # second non-superseded row for the coordinate (lost race).
                await conn.execute(
                    f"INSERT INTO {self.table_name} (id, data, tenant_id, created_at, updated_at) "
                    f"VALUES ($1, $2::jsonb, $3, NOW(), NOW())",
                    row_id, json.dumps(new_data, default=str), tenant_id,
                )
        return new_data


class ConcurrentTransitionError(RuntimeError):
    """The coordinate's current state changed while a transition was in flight."""


__all__ = ["ACTIVATION_TABLE", "ActivationStateRepo", "ConcurrentTransitionError"]
