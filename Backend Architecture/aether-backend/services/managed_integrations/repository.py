"""Reconciled Control Plane — durable stores (Phase 0).

Direct-SQL repositories over the ``managed_integrations`` and ``reconcile_runs``
tables created by the ``20260906_rcp_managed_integrations.py`` alembic migration
(the migration lands ``SCHEMA_SQL`` verbatim — string-identical, parity-checked
by repo-doctor, mirroring ``services/data_exchange/saved_mappings.py``).

No foreign key links ``reconcile_runs`` to ``managed_integrations`` on purpose:
the reconciler must be able to record an *evidence-backed* ``unknown``/``missing``
run for an integration that has never been registered (a durable registration
row is itself a fact Phase 0 does not auto-create). Tenancy is always carried in
the WHERE clause — no cross-tenant read is possible through this API.

Both repositories keep the data-exchange module-local in-memory fallback
(``get_pool()`` None under ``AETHER_ENV=local``), so unit tests exercise the
same columnar path the operator surface uses without a live Postgres.
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

from services.managed_integrations.contracts import ReconcileRunView

# Must stay string-identical to the alembic migration
# ``20260906_rcp_managed_integrations.py`` (parity-checked by repo-doctor).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS managed_integrations (
    managed_integration_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    integration_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    provider_ref TEXT,
    source_origin TEXT NOT NULL,
    source_owner TEXT NOT NULL,
    release_channel TEXT NOT NULL DEFAULT 'managed_stable',
    health_state TEXT NOT NULL DEFAULT 'unknown',
    lifecycle_state TEXT NOT NULL DEFAULT 'unknown',
    schema_fingerprint TEXT,
    desired_state_ref TEXT,
    observed_state_ref TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_reconcile_at TIMESTAMPTZ,
    last_reconcile_result TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_managed_integrations_tenant_env_kind
    ON managed_integrations (tenant_id, environment_id, integration_kind);
CREATE TABLE IF NOT EXISTS reconcile_runs (
    reconcile_id TEXT PRIMARY KEY,
    managed_integration_id TEXT NOT NULL,
    desired_state_ref TEXT,
    observed_state_ref TEXT,
    desired_revision TEXT NOT NULL,
    observed_revision TEXT,
    freshness_ok BOOLEAN NOT NULL,
    result TEXT NOT NULL,
    note TEXT,
    drift_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_reconcile_runs_integration_created
    ON reconcile_runs (managed_integration_id, created_at);
"""

# Module-local in-memory backing stores, shared by every repository instance
# (mirrors repositories/data_artifacts.py / services/data_exchange/saved_mappings.py).
_LOCAL_STORE: dict[str, dict] = {}  # managed_integration_id -> row
_RUN_STORE: dict[str, dict] = {}  # reconcile_id -> row


def reset_managed_integration_in_memory_store() -> None:
    """Test helper: empty the module-local in-memory managed-integration stores."""
    _LOCAL_STORE.clear()
    _RUN_STORE.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, datetime):
        return coerce_utc_lenient(raw) or raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _iso(raw: Any) -> Optional[str]:
    dt = _parse_ts(raw)
    return dt.isoformat() if dt is not None else None


def _parse_json(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            return _json.loads(value)
        except ValueError:
            return []
    return value


def _rowcount(result: Any) -> int:
    """Asyncpg ``pool.execute`` returns a command-status *string* with no
    ``.rowcount`` — parse the trailing count like every other repo."""
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


_MANAGED_INTEGRATION_COLUMNS = (
    "managed_integration_id, tenant_id, environment_id, integration_kind, "
    "source_ref, provider_ref, source_origin, source_owner, release_channel, "
    "health_state, lifecycle_state, schema_fingerprint, desired_state_ref, "
    "observed_state_ref, first_seen_at, last_seen_at, last_reconcile_at, "
    "last_reconcile_result, created_at, updated_at"
)


def _mi_from(row: dict) -> dict:
    return {
        "managed_integration_id": row.get("managed_integration_id"),
        "tenant_id": row.get("tenant_id"),
        "environment_id": row.get("environment_id"),
        "integration_kind": row.get("integration_kind"),
        "source_ref": row.get("source_ref"),
        "provider_ref": row.get("provider_ref"),
        "source_origin": row.get("source_origin"),
        "source_owner": row.get("source_owner"),
        "release_channel": row.get("release_channel") or "managed_stable",
        "health_state": row.get("health_state") or "unknown",
        "lifecycle_state": row.get("lifecycle_state") or "unknown",
        "schema_fingerprint": row.get("schema_fingerprint"),
        "desired_state_ref": row.get("desired_state_ref"),
        "observed_state_ref": row.get("observed_state_ref"),
        "first_seen_at": _iso(row.get("first_seen_at")),
        "last_seen_at": _iso(row.get("last_seen_at")),
        "last_reconcile_at": _iso(row.get("last_reconcile_at")),
        "last_reconcile_result": row.get("last_reconcile_result"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


_MI_INSERT_COLUMNS = (
    "managed_integration_id, tenant_id, environment_id, integration_kind, "
    "source_ref, provider_ref, source_origin, source_owner, release_channel, "
    "health_state, lifecycle_state, schema_fingerprint, desired_state_ref, "
    "observed_state_ref, first_seen_at, last_seen_at, last_reconcile_at, "
    "last_reconcile_result, created_at, updated_at"
)


_RECONCILE_RUN_COLUMNS = (
    "reconcile_id, managed_integration_id, desired_state_ref, observed_state_ref, "
    "desired_revision, observed_revision, freshness_ok, result, note, "
    "drift_summary, created_at"
)


def _rr_from(row: dict) -> dict:
    return {
        "reconcile_id": row.get("reconcile_id"),
        "managed_integration_ref": row.get("managed_integration_id"),
        "desired_state_ref": row.get("desired_state_ref"),
        "observed_state_ref": row.get("observed_state_ref"),
        "desired_revision": row.get("desired_revision"),
        "observed_revision": row.get("observed_revision"),
        "freshness_ok": bool(row.get("freshness_ok")),
        "result": row.get("result"),
        "note": row.get("note"),
        "drift": _parse_json(row.get("drift_summary")),
        "created_at": _iso(row.get("created_at")),
    }


class ManagedIntegrationRepository:
    """Tenant-scoped durable ``managed_integrations`` store.

    Writes exist so a later phase can register integrations and stamp
    ``last_reconcile_*``; Phase-0 routes are read-only and use ``get``/``list``.
    """

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    @property
    def _store(self) -> dict[str, dict]:
        return _LOCAL_STORE

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool

    # ── writes (used by tests / later phases) ─────────────────────────────

    async def register(
        self,
        *,
        managed_integration_id: str,
        tenant_id: str,
        environment_id: str,
        integration_kind: str,
        source_ref: str,
        source_origin: str,
        source_owner: str,
        provider_ref: Optional[str] = None,
        release_channel: str = "managed_stable",
        health_state: str = "unknown",
        lifecycle_state: str = "unknown",
        schema_fingerprint: Optional[str] = None,
        desired_state_ref: Optional[str] = None,
        observed_state_ref: Optional[str] = None,
        last_reconcile_at: Optional[datetime] = None,
        last_reconcile_result: Optional[str] = None,
    ) -> dict:
        """Create-or-refresh one managed-integration registration row.

        Idempotent by ``managed_integration_id``: an existing row keeps its
        ``first_seen_at``/``created_at`` and is refreshed with the newest
        observed facts. ``managed_integration_id`` is supplied by the caller
        (the canonical integration key the observer authorities already use).
        """
        now = _now()
        pool = await self._ensure()
        if pool is None:
            existing = self._store.get(managed_integration_id)
            row = {
                "managed_integration_id": managed_integration_id,
                "tenant_id": tenant_id,
                "environment_id": environment_id,
                "integration_kind": integration_kind,
                "source_ref": source_ref,
                "provider_ref": provider_ref,
                "source_origin": source_origin,
                "source_owner": source_owner,
                "release_channel": release_channel,
                "health_state": health_state,
                "lifecycle_state": lifecycle_state,
                "schema_fingerprint": schema_fingerprint,
                "desired_state_ref": desired_state_ref,
                "observed_state_ref": observed_state_ref,
                "first_seen_at": (
                    existing.get("first_seen_at") if existing else now.isoformat()
                ),
                "last_seen_at": now.isoformat(),
                "last_reconcile_at": _iso(last_reconcile_at),
                "last_reconcile_result": last_reconcile_result,
                "created_at": (
                    existing.get("created_at") if existing else now.isoformat()
                ),
                "updated_at": now.isoformat(),
            }
            self._store[managed_integration_id] = dict(row)
            return _mi_from(row)

        existing = await pool.fetchrow(
            "SELECT first_seen_at, created_at FROM managed_integrations "
            "WHERE tenant_id = $1 AND managed_integration_id = $2",
            tenant_id,
            managed_integration_id,
        )
        first_seen = existing["first_seen_at"] if existing else now
        created_at = existing["created_at"] if existing else now
        if existing is None:
            await pool.execute(
                f"INSERT INTO managed_integrations ({_MI_INSERT_COLUMNS}) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,"
                "$15,$16,$17,$18,$19,$20)",
                managed_integration_id,
                tenant_id,
                environment_id,
                integration_kind,
                source_ref,
                provider_ref,
                source_origin,
                source_owner,
                release_channel,
                health_state,
                lifecycle_state,
                schema_fingerprint,
                desired_state_ref,
                observed_state_ref,
                now,  # first_seen_at
                now,  # last_seen_at
                last_reconcile_at,
                last_reconcile_result,
                now,  # created_at
                now,  # updated_at
            )
        else:
            await pool.execute(
                "UPDATE managed_integrations SET environment_id=$1, "
                "integration_kind=$2, source_ref=$3, provider_ref=$4, "
                "source_origin=$5, source_owner=$6, release_channel=$7, "
                "health_state=$8, lifecycle_state=$9, schema_fingerprint=$10, "
                "desired_state_ref=$11, observed_state_ref=$12, last_seen_at=$13, "
                "last_reconcile_at=$14, last_reconcile_result=$15, updated_at=$13 "
                "WHERE tenant_id=$16 AND managed_integration_id=$17",
                environment_id,
                integration_kind,
                source_ref,
                provider_ref,
                source_origin,
                source_owner,
                release_channel,
                health_state,
                lifecycle_state,
                schema_fingerprint,
                desired_state_ref,
                observed_state_ref,
                now,
                last_reconcile_at,
                last_reconcile_result,
                tenant_id,
                managed_integration_id,
            )
        # Reconstruct what the row looks like now (fresh timestamps when new).
        return _mi_from(
            {
                "managed_integration_id": managed_integration_id,
                "tenant_id": tenant_id,
                "environment_id": environment_id,
                "integration_kind": integration_kind,
                "source_ref": source_ref,
                "provider_ref": provider_ref,
                "source_origin": source_origin,
                "source_owner": source_owner,
                "release_channel": release_channel,
                "health_state": health_state,
                "lifecycle_state": lifecycle_state,
                "schema_fingerprint": schema_fingerprint,
                "desired_state_ref": desired_state_ref,
                "observed_state_ref": observed_state_ref,
                "first_seen_at": first_seen,
                "last_seen_at": now,
                "last_reconcile_at": last_reconcile_at,
                "last_reconcile_result": last_reconcile_result,
                "created_at": created_at,
                "updated_at": now,
            }
        )

    async def mark_reconciled(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        managed_integration_id: str,
        result: str,
        observed_state_ref: Optional[str] = None,
        at: Optional[datetime] = None,
    ) -> bool:
        """Stamp ``last_reconcile_*`` after a reconcile run (False when absent)."""
        at = at or _now()
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(managed_integration_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return False
            row["last_reconcile_at"] = at.isoformat()
            row["last_reconcile_result"] = result
            if observed_state_ref:
                row["observed_state_ref"] = observed_state_ref
            row["updated_at"] = at.isoformat()
            return True
        status = await pool.execute(
            "UPDATE managed_integrations SET last_reconcile_at=$5, "
            "last_reconcile_result=$6, "
            "observed_state_ref=COALESCE($4, observed_state_ref), updated_at=$5 "
            "WHERE tenant_id=$1 AND environment_id=$2 AND managed_integration_id=$3",
            tenant_id,
            environment_id,
            managed_integration_id,
            observed_state_ref,
            at,
            result,
        )
        return _rowcount(status) > 0

    # ── reads ─────────────────────────────────────────────────────────────

    async def get(
        self, tenant_id: str, environment_id: str, managed_integration_id: str
    ) -> Optional[dict]:
        """Return one registration (None when absent); refuses cross-scope reads."""
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(managed_integration_id)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("environment_id") != environment_id
            ):
                return None
            return _mi_from(row)
        record = await pool.fetchrow(
            f"SELECT {_MANAGED_INTEGRATION_COLUMNS} FROM managed_integrations "
            "WHERE tenant_id = $1 AND environment_id = $2 AND "
            "managed_integration_id = $3",
            tenant_id,
            environment_id,
            managed_integration_id,
        )
        return _mi_from(dict(record)) if record is not None else None

    async def get_by_key(self, managed_integration_id: str) -> Optional[dict]:
        """Return one registration by its global primary key.

        Intended for the *operator aggregate* surface only: the caller (a Kyber
        operator exercising ``reconciled_control.read``) may read any tenant's
        row. Tenant-scoped reads should use :meth:`get`, which refuses
        cross-scope rows.
        """
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(managed_integration_id)
            return _mi_from(dict(row)) if row is not None else None
        record = await pool.fetchrow(
            f"SELECT {_MANAGED_INTEGRATION_COLUMNS} FROM managed_integrations "
            "WHERE managed_integration_id = $1",
            managed_integration_id,
        )
        return _mi_from(dict(record)) if record is not None else None

    async def list(
        self,
        *,
        tenant_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        integration_kind: Optional[str] = None,
        last_reconcile_result: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """Registered integrations, newest-last-seen first, optional ANDed filters.

        ``None`` filters are not applied. An operator may scope to one tenant or
        aggregate across tenants (the route owns that authorization decision).
        """
        limit = max(0, int(limit))
        offset = max(0, int(offset))
        pool = await self._ensure()

        def _matches(row: dict) -> bool:
            return (
                (tenant_id is None or row.get("tenant_id") == tenant_id)
                and (
                    environment_id is None
                    or row.get("environment_id") == environment_id
                )
                and (
                    integration_kind is None
                    or row.get("integration_kind") == integration_kind
                )
                and (
                    last_reconcile_result is None
                    or row.get("last_reconcile_result") == last_reconcile_result
                )
            )

        if pool is None:
            rows = [r for r in self._store.values() if _matches(r)]
            rows.sort(key=lambda r: r.get("last_seen_at") or "", reverse=True)
            return [_mi_from(r) for r in rows[offset : offset + limit]]

        clauses: list[str] = []
        args: list[Any] = []
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if environment_id is not None:
            args.append(environment_id)
            clauses.append(f"environment_id = ${len(args)}")
        if integration_kind is not None:
            args.append(integration_kind)
            clauses.append(f"integration_kind = ${len(args)}")
        if last_reconcile_result is not None:
            args.append(last_reconcile_result)
            clauses.append(f"last_reconcile_result = ${len(args)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(limit)
        args.append(offset)
        records = await pool.fetch(
            f"SELECT {_MANAGED_INTEGRATION_COLUMNS} FROM managed_integrations "
            f"{where} ORDER BY last_seen_at DESC LIMIT ${len(args) - 1} "
            f"OFFSET ${len(args)}",
            *args,
        )
        return [_mi_from(dict(r)) for r in records]


class ReconcileRunRepository:
    """Tenant-scoped durable ``reconcile_runs`` store (evidence, not state)."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    @property
    def _store(self) -> dict[str, dict]:
        return _RUN_STORE

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool

    # ── write ─────────────────────────────────────────────────────────────

    async def create(self, view: ReconcileRunView) -> dict:
        """Persist one reconcile run (its drift JSON is evidence-only)."""
        pool = await self._ensure()
        drift = [d.model_dump(mode="json") for d in view.drift]
        # In-memory row keeps the columnar key (`drift_summary`) so `_rr_from`
        # round-trips drift identically on both paths.
        row = {
            "reconcile_id": view.reconcile_id,
            "managed_integration_id": view.managed_integration_ref,
            "desired_state_ref": view.desired_state_ref,
            "observed_state_ref": view.observed_state_ref,
            "desired_revision": view.desired_revision,
            "observed_revision": view.observed_revision,
            "freshness_ok": bool(view.freshness_ok),
            "result": view.result,
            "note": view.note,
            "drift_summary": drift,
            "created_at": view.created_at.isoformat(),
        }
        if pool is None:
            self._store[view.reconcile_id] = dict(row)
        else:
            await pool.execute(
                "INSERT INTO reconcile_runs (reconcile_id, managed_integration_id, "
                "desired_state_ref, observed_state_ref, desired_revision, "
                "observed_revision, freshness_ok, result, note, drift_summary, "
                "created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11)",
                view.reconcile_id,
                view.managed_integration_ref,
                view.desired_state_ref,
                view.observed_state_ref,
                view.desired_revision,
                view.observed_revision,
                bool(view.freshness_ok),
                view.result,
                view.note,
                _json.dumps(drift, default=str),
                view.created_at,
            )
        return _rr_from(row)

    # ── reads ─────────────────────────────────────────────────────────────

    async def latest_for_integration(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        managed_integration_id: str,
    ) -> Optional[dict]:
        """Newest reconcile run for one integration (None when none recorded)."""
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("managed_integration_id") == managed_integration_id
            ]
            if not rows:
                return None
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return _rr_from(rows[0])
        record = await pool.fetchrow(
            f"SELECT {_RECONCILE_RUN_COLUMNS} FROM reconcile_runs "
            "WHERE managed_integration_id = $1 ORDER BY created_at DESC LIMIT 1",
            managed_integration_id,
        )
        return _rr_from(dict(record)) if record is not None else None

    async def list_for_integration(
        self,
        *,
        tenant_id: str,
        environment_id: str,
        managed_integration_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """Reconcile runs for one integration, newest first."""
        limit = max(0, int(limit))
        offset = max(0, int(offset))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("managed_integration_id") == managed_integration_id
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [_rr_from(r) for r in rows[offset : offset + limit]]
        records = await pool.fetch(
            f"SELECT {_RECONCILE_RUN_COLUMNS} FROM reconcile_runs "
            "WHERE managed_integration_id = $1 ORDER BY created_at DESC "
            "LIMIT $2 OFFSET $3",
            managed_integration_id,
            limit,
            offset,
        )
        return [_rr_from(dict(r)) for r in records]


_mi_repo: Optional[ManagedIntegrationRepository] = None
_rr_repo: Optional[ReconcileRunRepository] = None


def get_managed_integration_repository() -> ManagedIntegrationRepository:
    """Module singleton mirroring ``get_data_exchange_saved_mappings_repository()``."""
    global _mi_repo
    if _mi_repo is None:
        _mi_repo = ManagedIntegrationRepository()
    return _mi_repo


def get_reconcile_run_repository() -> ReconcileRunRepository:
    """Module singleton mirroring the managed-integration repository singleton."""
    global _rr_repo
    if _rr_repo is None:
        _rr_repo = ReconcileRunRepository()
    return _rr_repo
