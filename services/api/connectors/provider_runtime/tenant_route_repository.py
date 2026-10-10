"""Durable, tenant-scoped connector writer routes.

This store records which legacy/native path may submit graph-affecting facts for
one tenant integration, provider capability, account, stream and fact family.
The route and its append-only transition receipt change in one SQL transaction.
Local mode uses a module store for focused tests; non-local deployments require
PostgreSQL through ``repositories.repos.get_pool``.

``writer_fence`` holds a PostgreSQL row lock and transaction across an awaited
graph mutation. A route transition takes the same row lock, so it cannot move
the writer generation while a cooperating writer is in flight. This only
protects writers that use the fence; legacy and native graph paths are not yet
wired through it, so tenant cutover remains disabled.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from repositories.repos import get_pool

RouteMode = Literal["legacy_only", "shadow", "new_primary", "legacy_disabled"]
Writer = Literal["legacy", "native"]


# Keep identical to the Alembic migration. The route key is deliberately more
# specific than provider: independent streams and fact families may cut over at
# different times without giving either path blanket graph-writing authority.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tenant_connector_routes (
    route_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    managed_integration_id TEXT NOT NULL,
    provider_identity TEXT NOT NULL,
    account_id TEXT NOT NULL DEFAULT '',
    stream_id TEXT NOT NULL,
    fact_family TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('legacy_only', 'shadow', 'new_primary', 'legacy_disabled')),
    legacy_connection_ref TEXT NOT NULL,
    native_connection_ref TEXT,
    shadow_namespace TEXT,
    writer_generation BIGINT NOT NULL CHECK (writer_generation > 0),
    revision BIGINT NOT NULL CHECK (revision > 0),
    evidence_bundle_ref TEXT,
    rollback_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tenant_connector_route_scope
    ON tenant_connector_routes (tenant_id, environment_id, managed_integration_id, provider_identity, account_id, stream_id, fact_family);
CREATE TABLE IF NOT EXISTS tenant_connector_route_transitions (
    transition_id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES tenant_connector_routes(route_id) ON DELETE RESTRICT,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    previous_mode TEXT,
    next_mode TEXT NOT NULL,
    previous_generation BIGINT,
    next_generation BIGINT NOT NULL,
    revision BIGINT NOT NULL,
    actor_ref TEXT NOT NULL,
    decision_ref TEXT NOT NULL,
    evidence_bundle_ref TEXT,
    reason TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tenant_connector_route_transition_revision
    ON tenant_connector_route_transitions (route_id, revision);
CREATE INDEX IF NOT EXISTS ix_tenant_connector_route_transitions_scope
    ON tenant_connector_route_transitions (tenant_id, environment_id, route_id, occurred_at);
"""


class RouteConflict(RuntimeError):
    """A route already exists for the scope or another writer won the CAS."""


class StaleRouteRevision(RouteConflict):
    """The caller's route revision no longer names the current route."""


class RouteNotFound(RuntimeError):
    """No tenant-scoped route exists."""


class RouteAdmissionDenied(RuntimeError):
    """A writer cannot publish for this route/mode/generation."""


class RouteScope(BaseModel):
    """Full tenant-scoped route key. Empty account means no selected account."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    environment_id: str = Field(min_length=1)
    managed_integration_id: str = Field(min_length=1)
    provider_identity: str = Field(min_length=1)
    account_id: str = ""
    stream_id: str = Field(min_length=1)
    fact_family: str = Field(min_length=1)

    @field_validator(
        "tenant_id",
        "environment_id",
        "managed_integration_id",
        "provider_identity",
        "stream_id",
        "fact_family",
    )
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("route scope values must be nonblank")
        return value

    def key(self) -> tuple[str, ...]:
        return (
            self.tenant_id,
            self.environment_id,
            self.managed_integration_id,
            self.provider_identity,
            self.account_id,
            self.stream_id,
            self.fact_family,
        )


class TenantConnectorRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str
    tenant_id: str
    environment_id: str
    managed_integration_id: str
    provider_identity: str
    account_id: str
    stream_id: str
    fact_family: str
    mode: RouteMode
    legacy_connection_ref: str
    native_connection_ref: str | None = None
    shadow_namespace: str | None = None
    writer_generation: int = Field(gt=0)
    revision: int = Field(gt=0)
    evidence_bundle_ref: str | None = None
    rollback_until: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def scope(self) -> RouteScope:
        return RouteScope(**self.model_dump(include=set(RouteScope.model_fields)))

    @property
    def production_writer(self) -> Writer:
        return "native" if self.mode in ("new_primary", "legacy_disabled") else "legacy"


class RouteDecision(BaseModel):
    """References to the external governance decision; no secrets or PII."""

    model_config = ConfigDict(extra="forbid")

    actor_ref: str = Field(min_length=1)
    decision_ref: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence_bundle_ref: str | None = None

    @field_validator("actor_ref", "decision_ref", "reason")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("route decision values must be nonblank")
        return value


_ROUTES: dict[tuple[str, ...], dict] = {}
_TRANSITIONS: list[dict] = []
_LOCAL_ROUTE_LOCK = asyncio.Lock()


def reset_tenant_route_local_stores() -> None:
    """Test-only reset of the local fallback; never used for live cutover."""
    global _LOCAL_ROUTE_LOCK
    _ROUTES.clear()
    _TRANSITIONS.clear()
    _LOCAL_ROUTE_LOCK = asyncio.Lock()


_ROUTE_FIELDS = (
    "route_id",
    "tenant_id",
    "environment_id",
    "managed_integration_id",
    "provider_identity",
    "account_id",
    "stream_id",
    "fact_family",
    "mode",
    "legacy_connection_ref",
    "native_connection_ref",
    "shadow_namespace",
    "writer_generation",
    "revision",
    "evidence_bundle_ref",
    "rollback_until",
    "created_at",
    "updated_at",
)
_ROUTE_COLUMNS = ", ".join(_ROUTE_FIELDS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _assert_writer_route(
    route: TenantConnectorRoute | None,
    *,
    writer: Writer,
    writer_generation: int,
    connection_ref: str,
) -> TenantConnectorRoute:
    if (
        route is None
        or route.writer_generation != writer_generation
        or route.production_writer != writer
        or not connection_ref
        or connection_ref
        != (route.legacy_connection_ref if writer == "legacy" else route.native_connection_ref)
    ):
        raise RouteAdmissionDenied(
            "connector writer route, connection, or generation is not active"
        )
    return route


def _receipt(
    row: TenantConnectorRoute, previous: TenantConnectorRoute | None, decision: RouteDecision
) -> dict:
    return {
        "transition_id": f"ctrans_{uuid.uuid4().hex}",
        "route_id": row.route_id,
        "tenant_id": row.tenant_id,
        "environment_id": row.environment_id,
        "previous_mode": previous.mode if previous is not None else None,
        "next_mode": row.mode,
        "previous_generation": previous.writer_generation if previous is not None else None,
        "next_generation": row.writer_generation,
        "revision": row.revision,
        "actor_ref": decision.actor_ref,
        "decision_ref": decision.decision_ref,
        "evidence_bundle_ref": decision.evidence_bundle_ref,
        "reason": decision.reason,
        "occurred_at": row.updated_at,
    }


async def _insert_receipt(conn, receipt: dict) -> None:
    await conn.execute(
        "INSERT INTO tenant_connector_route_transitions ("
        "transition_id, route_id, tenant_id, environment_id, previous_mode, "
        "next_mode, previous_generation, next_generation, revision, actor_ref, "
        "decision_ref, evidence_bundle_ref, reason, occurred_at) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)",
        *receipt.values(),
    )


class TenantRouteRepository:
    """Scoped route reads and atomic compare-and-swap transitions."""

    def __init__(self) -> None:
        self._pool = None
        self._table_ensured = False

    async def _ensure(self):
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is None and (
            os.getenv("AETHER_ENV", "local").lower() != "local" or bool(os.getenv("DATABASE_URL"))
        ):
            raise RuntimeError("PostgreSQL is required for tenant connector routes")
        if self._pool is not None and not self._table_ensured:
            # Like BaseRepository's bootstrap, serialize concurrent first-use
            # DDL. PostgreSQL's IF NOT EXISTS alone still races on pg_class
            # when two worker processes create a missing table together.
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                        "aether.tenant_connector_routes.ensure_schema",
                    )
                    await conn.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool

    async def get(self, scope: RouteScope) -> TenantConnectorRoute | None:
        pool = await self._ensure()
        if pool is None:
            row = _ROUTES.get(scope.key())
            return TenantConnectorRoute.model_validate(dict(row)) if row is not None else None
        record = await pool.fetchrow(
            f"SELECT {_ROUTE_COLUMNS} FROM tenant_connector_routes "
            "WHERE tenant_id=$1 AND environment_id=$2 AND managed_integration_id=$3 "
            "AND provider_identity=$4 AND account_id=$5 AND stream_id=$6 AND fact_family=$7",
            *scope.key(),
        )
        return TenantConnectorRoute.model_validate(dict(record)) if record is not None else None

    @asynccontextmanager
    async def writer_fence(
        self,
        scope: RouteScope,
        *,
        writer: Writer,
        writer_generation: int,
        connection_ref: str,
    ):
        """Hold the route row lock through one cooperating graph mutation.

        The generation and connection are checked *after* taking the lock.
        ``compare_and_swap`` takes ``FOR UPDATE`` on the same row, so a route
        transition waits for this context to exit. Do not perform unrelated
        network work while holding the context.
        """
        pool = await self._ensure()
        if pool is None:
            if os.getenv("AETHER_ENV", "local").lower() != "local":
                raise RouteAdmissionDenied("PostgreSQL is required for connector writer fencing")
            async with _LOCAL_ROUTE_LOCK:
                raw = _ROUTES.get(scope.key())
                route = TenantConnectorRoute.model_validate(raw) if raw is not None else None
                yield _assert_writer_route(
                    route,
                    writer=writer,
                    writer_generation=writer_generation,
                    connection_ref=connection_ref,
                )
            return
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Graph projection may use a different backend. Keep this row
                # lock alive while the bounded caller awaits that projection;
                # the pool's ordinary 60-second idle timeout must not release
                # the fence in the middle of an external write.
                await conn.execute("SET LOCAL idle_in_transaction_session_timeout = 0")
                raw = await conn.fetchrow(
                    f"SELECT {_ROUTE_COLUMNS} FROM tenant_connector_routes "
                    "WHERE tenant_id=$1 AND environment_id=$2 AND managed_integration_id=$3 "
                    "AND provider_identity=$4 AND account_id=$5 AND stream_id=$6 "
                    "AND fact_family=$7 FOR UPDATE",
                    *scope.key(),
                )
                route = TenantConnectorRoute.model_validate(dict(raw)) if raw is not None else None
                yield _assert_writer_route(
                    route,
                    writer=writer,
                    writer_generation=writer_generation,
                    connection_ref=connection_ref,
                )

    async def create_legacy(
        self, scope: RouteScope, *, legacy_connection_ref: str, decision: RouteDecision
    ) -> TenantConnectorRoute:
        if not legacy_connection_ref.strip():
            raise ValueError("legacy_connection_ref is required")
        now = _now()
        row = TenantConnectorRoute(
            route_id=f"croute_{uuid.uuid4().hex}",
            **scope.model_dump(),
            mode="legacy_only",
            legacy_connection_ref=legacy_connection_ref,
            writer_generation=1,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        pool = await self._ensure()
        if pool is None:
            async with _LOCAL_ROUTE_LOCK:
                if scope.key() in _ROUTES:
                    raise RouteConflict("route already exists for tenant integration scope")
                _ROUTES[scope.key()] = row.model_dump()
                _TRANSITIONS.append(_receipt(row, None, decision))
                return row
        async with pool.acquire() as conn:
            async with conn.transaction():
                stored = await conn.fetchrow(
                    "INSERT INTO tenant_connector_routes (" + _ROUTE_COLUMNS + ") "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18) "
                    "ON CONFLICT DO NOTHING RETURNING " + _ROUTE_COLUMNS,
                    *(getattr(row, field) for field in _ROUTE_FIELDS),
                )
                if stored is None:
                    raise RouteConflict("route already exists for tenant integration scope")
                await _insert_receipt(conn, _receipt(row, None, decision))
        return row

    async def compare_and_swap(
        self,
        scope: RouteScope,
        *,
        expected_revision: int,
        mode: RouteMode,
        native_connection_ref: str | None,
        shadow_namespace: str | None,
        rollback_until: datetime | None,
        decision: RouteDecision,
    ) -> TenantConnectorRoute:
        """Change writer generation and audit in one transaction.

        Transition policy belongs to ``TenantRouteService``. This primitive
        only accepts full, revision-checked updates so no caller can modify a
        writer route without advancing its fence and appending a receipt.
        """
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        pool = await self._ensure()
        if pool is None:
            async with _LOCAL_ROUTE_LOCK:
                current_raw = _ROUTES.get(scope.key())
                if current_raw is None:
                    raise RouteNotFound("tenant connector route does not exist")
                current = TenantConnectorRoute.model_validate(current_raw)
                if current.revision != expected_revision:
                    raise StaleRouteRevision("route changed since it was read")
                updated = TenantConnectorRoute.model_validate(
                    {
                        **current.model_dump(),
                        **{
                            "mode": mode,
                            "native_connection_ref": native_connection_ref,
                            "shadow_namespace": shadow_namespace,
                            "rollback_until": rollback_until,
                            "evidence_bundle_ref": decision.evidence_bundle_ref,
                            "writer_generation": current.writer_generation + 1,
                            "revision": current.revision + 1,
                            "updated_at": _now(),
                        },
                    }
                )
                _ROUTES[scope.key()] = updated.model_dump()
                _TRANSITIONS.append(_receipt(updated, current, decision))
                return updated

        async with pool.acquire() as conn:
            async with conn.transaction():
                current_raw = await conn.fetchrow(
                    f"SELECT {_ROUTE_COLUMNS} FROM tenant_connector_routes "
                    "WHERE tenant_id=$1 AND environment_id=$2 AND managed_integration_id=$3 "
                    "AND provider_identity=$4 AND account_id=$5 AND stream_id=$6 "
                    "AND fact_family=$7 FOR UPDATE",
                    *scope.key(),
                )
                if current_raw is None:
                    raise RouteNotFound("tenant connector route does not exist")
                current = TenantConnectorRoute.model_validate(dict(current_raw))
                if current.revision != expected_revision:
                    raise StaleRouteRevision("route changed since it was read")
                updated_raw = await conn.fetchrow(
                    f"UPDATE tenant_connector_routes SET mode=$1, native_connection_ref=$2, "
                    "shadow_namespace=$3, rollback_until=$4, evidence_bundle_ref=$5, "
                    "writer_generation=writer_generation+1, revision=revision+1, "
                    "updated_at=$6 WHERE route_id=$7 AND tenant_id=$8 "
                    f"AND environment_id=$9 AND revision=$10 RETURNING {_ROUTE_COLUMNS}",
                    mode,
                    native_connection_ref,
                    shadow_namespace,
                    rollback_until,
                    decision.evidence_bundle_ref,
                    _now(),
                    current.route_id,
                    scope.tenant_id,
                    scope.environment_id,
                    expected_revision,
                )
                if updated_raw is None:
                    raise StaleRouteRevision("route changed since it was read")
                updated = TenantConnectorRoute.model_validate(dict(updated_raw))
                await _insert_receipt(conn, _receipt(updated, current, decision))
        return updated

    async def transition_history(self, scope: RouteScope) -> list[dict]:
        """Read append-only receipts only through the same tenant scope."""
        route = await self.get(scope)
        if route is None:
            return []
        pool = await self._ensure()
        if pool is None:
            return [dict(r) for r in _TRANSITIONS if r["route_id"] == route.route_id]
        records = await pool.fetch(
            "SELECT transition_id, route_id, tenant_id, environment_id, previous_mode, "
            "next_mode, previous_generation, next_generation, revision, actor_ref, "
            "decision_ref, evidence_bundle_ref, reason, occurred_at "
            "FROM tenant_connector_route_transitions WHERE tenant_id=$1 "
            "AND environment_id=$2 AND route_id=$3 ORDER BY revision",
            scope.tenant_id,
            scope.environment_id,
            route.route_id,
        )
        return [dict(r) for r in records]


__all__ = [
    "RouteAdmissionDenied",
    "RouteConflict",
    "RouteDecision",
    "RouteMode",
    "RouteNotFound",
    "RouteScope",
    "SCHEMA_SQL",
    "StaleRouteRevision",
    "TenantConnectorRoute",
    "TenantRouteRepository",
    "Writer",
    "reset_tenant_route_local_stores",
]
