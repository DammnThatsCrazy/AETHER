"""Durable repository for canonical data-rights grants and lifecycle events.

The service remains the grant authority. This repository stores its canonical
grant records and append-only create/revoke events in migration-owned tables.
Local mode uses a per-service in-memory store, matching the repository pattern.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional

from services.integrations.data_rights.models import DataRightsGrant, GrantStatus
from repositories.repos import get_pool


class DataRightsGrantRepository:
    """Tenant-scoped storage for canonical grants and their lifecycle events."""

    def __init__(
        self,
        *,
        local_grants: Optional[dict[str, DataRightsGrant]] = None,
        local_events: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self._local_grants = local_grants if local_grants is not None else {}
        self._local_events = local_events if local_events is not None else []

    async def _pool(self) -> Any:
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return None
        return await get_pool()

    async def is_ready(self) -> bool:
        """Return true only when non-local PostgreSQL and both migrated tables work."""
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return False
        try:
            pool = await self._pool()
            if pool is None:
                return False
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT table_name, column_name
                       FROM information_schema.columns
                       WHERE table_schema = current_schema()
                         AND table_name IN ('data_rights_grants', 'data_rights_grant_events')"""
                )
                schema_guards = await conn.fetchrow(
                    """SELECT
                       to_regclass('ix_data_rights_grants_tenant_source') IS NOT NULL AS source_index,
                       to_regclass('ux_data_rights_grants_id_tenant') IS NOT NULL AS tenant_key,
                       EXISTS (SELECT 1 FROM pg_trigger
                               WHERE tgname = 'trg_data_rights_grant_events_immutable'
                                 AND tgrelid = 'data_rights_grant_events'::regclass
                                 AND tgenabled IN ('O', 'A')
                                 AND NOT tgisinternal) AS immutable_event_trigger"""
                )
                privileges = await conn.fetchrow(
                    """SELECT
                       has_table_privilege(current_user, 'data_rights_grants', 'SELECT') AS grant_read,
                       has_table_privilege(current_user, 'data_rights_grants', 'INSERT') AS grant_create,
                       has_table_privilege(current_user, 'data_rights_grants', 'UPDATE') AS grant_revoke,
                       has_table_privilege(current_user, 'data_rights_grant_events', 'SELECT') AS event_read,
                       has_table_privilege(current_user, 'data_rights_grant_events', 'INSERT') AS event_write"""
                )
            columns: dict[str, set[str]] = {}
            for row in rows:
                columns.setdefault(row["table_name"], set()).add(row["column_name"])
            return bool(
                all(schema_guards[key] for key in (
                    "source_index", "tenant_key", "immutable_event_trigger"
                ))
                and all(privileges[key] for key in (
                    "grant_read", "grant_create", "grant_revoke", "event_read", "event_write"
                ))
                and {"id", "data", "tenant_id", "created_at", "updated_at"}
                <= columns.get("data_rights_grants", set())
                and {"event_id", "grant_ref", "tenant_id", "event_type", "actor",
                     "reason", "occurred_at", "data"}
                <= columns.get("data_rights_grant_events", set())
            )
        except Exception:
            return False

    async def create(self, grant: DataRightsGrant, *, actor: str) -> DataRightsGrant:
        body = grant.model_dump(mode="json")
        event = self._event(
            grant=grant,
            event_type="created",
            actor=actor,
            reason=grant.legal_basis,
            occurred_at=grant.granted_at,
            event_id=grant.audit_event_id,
        )
        pool = await self._pool()
        if pool is None:
            self._local_grants[grant.data_rights_grant_id] = grant
            self._local_events.append(event)
            return grant
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO data_rights_grants
                       (id, data, tenant_id, created_at, updated_at)
                       VALUES ($1, $2::jsonb, $3, $4::timestamptz, $4::timestamptz)""",
                    grant.data_rights_grant_id,
                    json.dumps(body), grant.tenant_id, grant.granted_at,
                )
                await self._insert_event(conn, event)
        return grant

    async def get(
        self, grant_id: str, *, tenant_id: Optional[str] = None,
    ) -> Optional[DataRightsGrant]:
        pool = await self._pool()
        if pool is None:
            grant = self._local_grants.get(grant_id)
            if grant is None or (tenant_id is not None and grant.tenant_id != tenant_id):
                return None
            return grant
        async with pool.acquire() as conn:
            if tenant_id is None:
                row = await conn.fetchrow(
                    "SELECT data FROM data_rights_grants WHERE id = $1", grant_id
                )
            else:
                row = await conn.fetchrow(
                    "SELECT data FROM data_rights_grants WHERE id = $1 AND tenant_id = $2",
                    grant_id, tenant_id,
                )
        return self._decode(row["data"]) if row else None

    async def list(
        self,
        *,
        tenant_id: Optional[str] = None,
        connector_id: Optional[str] = None,
        source_id: Optional[str] = None,
        status: Optional[GrantStatus] = None,
    ) -> list[DataRightsGrant]:
        pool = await self._pool()
        if pool is None:
            grants = list(self._local_grants.values())
            return [g for g in grants if
                (tenant_id is None or g.tenant_id == tenant_id)
                and (connector_id is None or g.connector_id == connector_id)
                and (source_id is None or g.source_id == source_id)
                and (status is None or g.status == status)]

        conditions: list[str] = []
        params: list[Any] = []
        for column, value in (("tenant_id", tenant_id),):
            if value is not None:
                params.append(value)
                conditions.append(f"{column} = ${len(params)}")
        for key, value in (("connector_id", connector_id), ("source_id", source_id),
                           ("status", status.value if status is not None else None)):
            if value is not None:
                params.append(value)
                conditions.append(f"data->>'{key}' = ${len(params)}")
        where = " AND ".join(conditions) if conditions else "TRUE"
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT data FROM data_rights_grants WHERE {where} ORDER BY created_at DESC",
                *params,
            )
        return [self._decode(row["data"]) for row in rows]

    async def revoke(
        self,
        grant_id: str,
        *,
        tenant_id: str,
        actor: str,
        reason: str,
        revoked_at: str,
    ) -> Optional[DataRightsGrant]:
        pool = await self._pool()
        if pool is None:
            grant = self._local_grants.get(grant_id)
            if grant is None or grant.tenant_id != tenant_id:
                return None
            if grant.status == GrantStatus.REVOKED:
                return grant
            updated = grant.model_copy(update={
                "status": GrantStatus.REVOKED,
                "revoked_at": revoked_at,
                "revocation_reason": reason,
                "revoked_by_user_id": actor,
                "revocation_event_id": f"dre_{uuid.uuid4().hex}",
            })
            event = self._event(
                grant=updated, event_type="revoked", actor=actor, reason=reason,
                occurred_at=revoked_at, event_id=updated.revocation_event_id,
            )
            self._local_grants[grant_id] = updated
            self._local_events.append(event)
            return updated

        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT data FROM data_rights_grants WHERE id = $1 AND tenant_id = $2 FOR UPDATE",
                    grant_id, tenant_id,
                )
                if row is None:
                    return None
                grant = self._decode(row["data"])
                if grant.status == GrantStatus.REVOKED:
                    return grant
                event_id = f"dre_{uuid.uuid4().hex}"
                updated = grant.model_copy(update={
                    "status": GrantStatus.REVOKED,
                    "revoked_at": revoked_at,
                    "revocation_reason": reason,
                    "revoked_by_user_id": actor,
                    "revocation_event_id": event_id,
                })
                body = updated.model_dump(mode="json")
                await conn.execute(
                    """UPDATE data_rights_grants
                       SET data = $1::jsonb, updated_at = $2::timestamptz
                       WHERE id = $3 AND tenant_id = $4""",
                    json.dumps(body), revoked_at, grant_id, grant.tenant_id,
                )
                await self._insert_event(conn, self._event(
                    grant=updated, event_type="revoked", actor=actor,
                    reason=reason, occurred_at=revoked_at, event_id=event_id,
                ))
                return updated

    async def events_for_grant(
        self, grant_id: str, *, tenant_id: str,
    ) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            if not any(g.data_rights_grant_id == grant_id and g.tenant_id == tenant_id
                       for g in self._local_grants.values()):
                return []
            return [dict(event) for event in self._local_events
                    if event["grant_ref"] == grant_id and event["tenant_id"] == tenant_id]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT data FROM data_rights_grant_events
                   WHERE grant_ref = $1 AND tenant_id = $2 ORDER BY occurred_at""",
                grant_id, tenant_id,
            )
        return [json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
                for row in rows]

    @staticmethod
    def _decode(value: Any) -> DataRightsGrant:
        body = json.loads(value) if isinstance(value, str) else value
        return DataRightsGrant.model_validate(body)

    @staticmethod
    def _event(
        *, grant: DataRightsGrant, event_type: str, actor: str,
        reason: Optional[str], occurred_at: str, event_id: str,
    ) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "grant_ref": grant.data_rights_grant_id,
            "tenant_id": grant.tenant_id,
            "event_type": event_type,
            "actor": actor,
            "reason": reason,
            "occurred_at": occurred_at,
        }

    @staticmethod
    async def _insert_event(conn: Any, event: dict[str, Any]) -> None:
        await conn.execute(
            """INSERT INTO data_rights_grant_events
               (event_id, grant_ref, tenant_id, event_type, actor, reason, occurred_at, data)
               VALUES ($1, $2, $3, $4, $5, $6, $7::timestamptz, $8::jsonb)""",
            event["event_id"], event["grant_ref"], event["tenant_id"],
            event["event_type"], event["actor"], event["reason"],
            event["occurred_at"], json.dumps(event),
        )


__all__ = ["DataRightsGrantRepository"]
