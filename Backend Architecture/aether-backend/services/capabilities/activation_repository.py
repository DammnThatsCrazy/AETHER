"""Durable repository for capability activation states.

Thin ``BaseRepository`` wrapper over ``capability_activation_states`` (JSONB
store; Postgres in production, shared in-memory locally). Rows are append-only
STATE VERSIONS: exactly one non-superseded row exists per
``(tenant_id, provider, environment, capability)`` coordinate (enforced by a
partial-unique index in Postgres and by the CAS advance here). All transition
legality and precondition enforcement live in the lifecycle authority.
"""

from __future__ import annotations

import uuid
from typing import Optional

from repositories.repos import BaseRepository

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

    async def current_all(self, limit: int = 5000) -> list[dict]:
        """Cross-tenant current states (operator surfaces only)."""
        return await self.find_many(filters={"superseded": False}, limit=limit)

    async def advance(self, prior: Optional[dict], new_row: dict) -> dict:
        """Append the next state version, superseding ``prior``.

        Compare-and-set: refuses when ``prior`` is no longer the current row
        (a concurrent transition won), so histories stay linear.
        """
        coordinate = {
            k: new_row[k] for k in ("tenant_id", "provider", "environment", "capability")
        }
        live = await self.current(**coordinate)
        if (live or {}).get("id") != (prior or {}).get("id"):
            raise ConcurrentTransitionError(
                f"activation state for {coordinate} changed concurrently"
            )
        if prior is not None:
            await self.update(prior["id"], {"superseded": True})
        row_id = f"cas_{uuid.uuid4().hex}"
        stored = await self.insert(row_id, {**new_row, "superseded": False})
        return stored


class ConcurrentTransitionError(RuntimeError):
    """The coordinate's current state changed while a transition was in flight."""


__all__ = ["ACTIVATION_TABLE", "ActivationStateRepo", "ConcurrentTransitionError"]
