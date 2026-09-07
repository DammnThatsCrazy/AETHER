"""Reconciled Control Plane — durable §29 fleet stores (Phase 4).

Direct-SQL repositories over the tables created by the
``20260906_rcp_fleet_update.py`` alembic migration (the migration lands
``SCHEMA_SQL`` verbatim — string-identical, mirroring
``execution_records_repository.py`` and the earlier Phase-1/2/3 repos).

Two repositories in one module (mirroring the two-repo layout of
``schema_mapping_repository.py``):

* ``FleetUpdatePolicyRepository`` — one row per §28/§29 tenant update-channel
  policy (``fleet_update_policies``). A policy names the tenant's channel and
  the §40 delivery-ring ceiling (``max_ring``) the tenant operator set;
  ``create`` raises on a duplicate scope — §29 says a tenant policy is one per
  channel, and the unique index on (tenant_ref, environment_id, channel) makes
  that atomic on the SQL path.
* ``FleetUpgradePlanRepository`` — one row per §29 upgrade plan composed for
  one managed integration (``fleet_upgrade_plans``): the candidate release
  (ref + class), the §30 platform behavior, the eligibility verdict and its
  human-readable reasons, the execution path (automatic / review / action),
  the planned §40 ring ceiling, and ``rollout_ref`` (stamped via
  ``mark_rollout`` when the plan is handed to the §40 rollout engine).

Storage vocabularies are enforced at ``create`` (and at ``list``-filters where
applicable), mirroring the §8.1/§34 vocab enforcement in the sibling repos:

* channel over ``MANAGED_RELEASE_CHANNELS`` (§28/§29),
* ``max_ring``/``planned_ring`` over ``ROLLOUT_RINGS`` (§40),
* ``integration_kind`` over ``MANAGED_INTEGRATION_KINDS`` (§6),
* ``artifact_kind`` over ``ROLLOUT_ARTIFACT_KINDS`` (§40),
* ``behavior`` over ``UPGRADE_BEHAVIOR_VALUES`` (§30),
* ``candidate_class`` and ``execution_path`` over the plan vocabularies this
  module defines below (the §29 candidate classes and §40-shaped execution
  paths). Those two vocabularies have no ``contracts.py`` home yet and the
  engine imports them from here — the repository module is the single write
  path, so it owns the storage vocabulary; the ``fleet_controller`` engine
  consumes the same constants rather than duplicating them.

Every repository keeps the module-local in-memory fallback (``get_pool()``
None under ``AETHER_ENV=local``), so unit tests exercise the same columnar
path the engine uses without a live Postgres. Tenancy is always carried in the
WHERE clause — no cross-tenant read or write is possible through these APIs
(CP-08).
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field
from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

from services.managed_integrations.contracts import (
    MANAGED_INTEGRATION_KINDS,
    MANAGED_RELEASE_CHANNELS,
    ROLLOUT_ARTIFACT_KINDS,
    ROLLOUT_RINGS,
    UPGRADE_BEHAVIOR_VALUES,
    is_managed_integration_kind,
    is_rollout_artifact_kind,
    is_rollout_ring,
    is_upgrade_behavior,
)

# Must stay string-identical to the alembic migration
# ``20260906_rcp_fleet_update.py`` (parity-checked by repo-doctor).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fleet_update_policies (
    policy_id TEXT PRIMARY KEY,
    tenant_ref TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    max_ring TEXT NOT NULL DEFAULT '100%',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_fleet_policy_scope
    ON fleet_update_policies (tenant_ref, environment_id, channel);

CREATE TABLE IF NOT EXISTS fleet_upgrade_plans (
    plan_id TEXT PRIMARY KEY,
    tenant_ref TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    managed_integration_ref TEXT NOT NULL,
    integration_kind TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    candidate_ref TEXT NOT NULL,
    candidate_class TEXT NOT NULL,
    channel TEXT NOT NULL,
    behavior TEXT NOT NULL,
    eligible BOOLEAN NOT NULL DEFAULT false,
    execution_path TEXT NOT NULL,
    eligibility_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    planned_ring TEXT,
    rollout_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fleet_plans_tenant
    ON fleet_upgrade_plans (tenant_ref, created_at);
"""

# ── §29 plan vocabularies (storage single-source) ────────────────────────────

# §29 candidate release classes a fleet plan may name. ``latest`` is the
# pseudo-tag §29 warns about — it exists in the vocabulary only so the engine
# and repository can *reject* it explicitly (``managed_stable`` is never
# uncontrolled ``latest``).
CANDIDATE_CLASSES: tuple[str, ...] = (
    "security",
    "patch",
    "compatible",
    "stable",
    "latest",
)


def is_candidate_class(value: str) -> bool:
    return value in CANDIDATE_CLASSES


# Execution paths a composed §29 plan may carry. ``automatic`` means the
# Olympus-driven §40 ring path; ``review`` means operator review is required
# before any delivery; ``action`` means host-mediated/tenant action is
# surfaced (never silently performed).
EXECUTION_PATHS: tuple[str, ...] = ("automatic", "review", "action")

# Storage sentinel for the plan ``behavior`` column when the integration
# kind has no §30 platform-behavior row (the engine's gate-1 review plans:
# "unknown §30 platform behavior for kind ..."). ``contracts.py`` carries no
# "unknown" upgrade-behavior token because §30's table is the closed set of
# *known* behaviors; the plan store admits this one honest sentinel so a
# fail-closed review plan never fabricates a §30 token. All other values are
# enforced against ``UPGRADE_BEHAVIOR_VALUES`` at create.
UNKNOWN_UPGRADE_BEHAVIOR = "unknown"


def is_execution_path(value: str) -> bool:
    return value in EXECUTION_PATHS


def is_release_channel(value: str) -> bool:
    """§28/§29 release-channel guard (no contracts helper exists yet)."""
    return value in MANAGED_RELEASE_CHANNELS


class FleetUpdatePolicyRow(BaseModel):
    """Typed storage row for ``fleet_update_policies`` (§28/§29).

    Mirrors the table columns one-to-one. The channel and §40 ring
    vocabularies are enforced by the repository at ``create``/``update``, not
    by this model, so the model stays a plain column mirror.
    """

    policy_id: str
    tenant_ref: str
    environment_id: str
    channel: str
    max_ring: str = "100%"
    created_at: datetime
    updated_at: datetime


class FleetUpgradePlanRow(BaseModel):
    """Typed storage row for ``fleet_upgrade_plans`` (§29 plan fields).

    Mirrors the table columns one-to-one; vocabularies are enforced by the
    repository at ``create`` (channel §28/§29, behavior §30, artifact_kind
    §40, integration_kind §6, candidate_class + execution_path §29).
    """

    plan_id: str
    tenant_ref: str
    environment_id: str
    managed_integration_ref: str
    integration_kind: str
    artifact_kind: str
    candidate_ref: str
    candidate_class: str
    channel: str
    behavior: str
    eligible: bool = False
    execution_path: str
    eligibility_reasons: list[str] = Field(default_factory=list)
    planned_ring: Optional[str] = None
    rollout_ref: Optional[str] = None
    created_at: datetime


# Module-local in-memory backing stores, shared by every repository instance.
# Keys are the row's primary key (mirrors execution_records_repository.py).
_POLICY_STORE: dict[str, dict] = {}
_PLAN_STORE: dict[str, dict] = {}


def reset_fleet_controller_stores() -> None:
    """Test helper: empty every module-local fleet store."""
    _POLICY_STORE.clear()
    _PLAN_STORE.clear()


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
            return {}
    return value


def _rowcount(result: Any) -> int:
    """Asyncpg ``pool.execute`` returns a command-status *string* — parse the
    trailing count like every other repo."""
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


class _FleetRepo:
    """Shared pool/ensure plumbing for the fleet repositories."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool


# ── §28/§29 tenant update-channel policies ───────────────────────────────────


class FleetUpdatePolicyRepository(_FleetRepo):
    """One §28/§29 tenant update-channel policy per (tenant, env, channel).

    ``create`` enforces the channel vocabularies (§28 channels over
    ``MANAGED_RELEASE_CHANNELS``, §40 ``max_ring`` over ``ROLLOUT_RINGS``) and
    raises on a duplicate scope — §29 says a tenant update policy is one per
    channel. Callers that want create-or-update semantics use the engine's
    ``set_policy`` (a read-modify-write over this repository); this repository
    itself stays plain create/read/update_max_ring.
    """

    def __init__(self) -> None:
        super().__init__()
        self._store = _POLICY_STORE

    async def create(self, view: FleetUpdatePolicyRow) -> dict:
        if not is_release_channel(view.channel):
            raise ValueError(
                f"unknown §28/§29 release channel {view.channel!r} — expected "
                f"one of {MANAGED_RELEASE_CHANNELS}"
            )
        if not is_rollout_ring(view.max_ring):
            raise ValueError(
                f"unknown §40 rollout ring {view.max_ring!r} — expected one "
                f"of {ROLLOUT_RINGS}"
            )
        row = view.model_dump(mode="json")
        pool = await self._ensure()
        if pool is None:
            if self._find_scope(view.tenant_ref, view.environment_id, view.channel):
                raise ValueError(
                    f"§29 tenant update policy is one per channel — a policy "
                    f"already exists for (tenant_ref={view.tenant_ref!r}, "
                    f"environment_id={view.environment_id!r}, "
                    f"channel={view.channel!r})"
                )
            self._store[view.policy_id] = dict(row)
            return dict(row)
        existing = await pool.fetchrow(
            "SELECT policy_id FROM fleet_update_policies "
            "WHERE tenant_ref=$1 AND environment_id=$2 AND channel=$3",
            view.tenant_ref, view.environment_id, view.channel,
        )
        if existing is not None:
            raise ValueError(
                f"§29 tenant update policy is one per channel — a policy "
                f"already exists for (tenant_ref={view.tenant_ref!r}, "
                f"environment_id={view.environment_id!r}, "
                f"channel={view.channel!r})"
            )
        await pool.execute(
            "INSERT INTO fleet_update_policies (policy_id, tenant_ref, "
            "environment_id, channel, max_ring, created_at, updated_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7)",
            view.policy_id, view.tenant_ref, view.environment_id, view.channel,
            view.max_ring, view.created_at, view.updated_at,
        )
        return row

    def _find_scope(
        self, tenant_ref: str, environment_id: str, channel: str
    ) -> Optional[dict]:
        for row in self._store.values():
            if (
                row.get("tenant_ref") == tenant_ref
                and row.get("environment_id") == environment_id
                and row.get("channel") == channel
            ):
                return row
        return None

    async def get(
        self,
        *,
        tenant_ref: str,
        environment_id: str,
        channel: str,
    ) -> Optional[dict]:
        if not is_release_channel(channel):
            raise ValueError(
                f"unknown §28/§29 release channel {channel!r} — expected one "
                f"of {MANAGED_RELEASE_CHANNELS}"
            )
        pool = await self._ensure()
        if pool is None:
            row = self._find_scope(tenant_ref, environment_id, channel)
            return dict(row) if row is not None else None
        record = await pool.fetchrow(
            "SELECT * FROM fleet_update_policies "
            "WHERE tenant_ref=$1 AND environment_id=$2 AND channel=$3",
            tenant_ref, environment_id, channel,
        )
        return _policy_row(dict(record)) if record is not None else None

    async def list(
        self,
        *,
        tenant_ref: Optional[str] = None,
        environment_id: Optional[str] = None,
        channel: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        if channel is not None and not is_release_channel(channel):
            raise ValueError(
                f"unknown §28/§29 release channel {channel!r} — expected one "
                f"of {MANAGED_RELEASE_CHANNELS}"
            )
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if (tenant_ref is None or r.get("tenant_ref") == tenant_ref)
                and (environment_id is None
                     or r.get("environment_id") == environment_id)
                and (channel is None or r.get("channel") == channel)
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [dict(r) for r in rows[:limit]]
        where: list[str] = []
        args: list[Any] = []
        for col, value in (
            ("tenant_ref", tenant_ref),
            ("environment_id", environment_id),
            ("channel", channel),
        ):
            if value is not None:
                args.append(value)
                where.append(f"{col} = ${len(args)}")
        sql_where = f"WHERE {' AND '.join(where)}" if where else ""
        args.append(limit)
        records = await pool.fetch(
            f"SELECT * FROM fleet_update_policies {sql_where} "
            f"ORDER BY created_at DESC LIMIT ${len(args)}",
            *args,
        )
        return [_policy_row(dict(r)) for r in records]

    async def update_max_ring(
        self,
        *,
        tenant_ref: str,
        environment_id: str,
        channel: str,
        max_ring: str,
        at: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Raise/lower the §40 ring ceiling of one policy (None when absent).

        Stamps ``updated_at``. The §40 ring vocabulary is enforced here too —
        an unknown ring can never be persisted as a ceiling.
        """
        if not is_release_channel(channel):
            raise ValueError(
                f"unknown §28/§29 release channel {channel!r} — expected one "
                f"of {MANAGED_RELEASE_CHANNELS}"
            )
        if not is_rollout_ring(max_ring):
            raise ValueError(
                f"unknown §40 rollout ring {max_ring!r} — expected one of "
                f"{ROLLOUT_RINGS}"
            )
        at = at or datetime.now(timezone.utc)
        pool = await self._ensure()
        if pool is None:
            row = self._find_scope(tenant_ref, environment_id, channel)
            if row is None:
                return None
            row["max_ring"] = max_ring
            row["updated_at"] = at.isoformat()
            return dict(row)
        result = await pool.execute(
            "UPDATE fleet_update_policies SET max_ring=$4, updated_at=$5 "
            "WHERE tenant_ref=$1 AND environment_id=$2 AND channel=$3",
            tenant_ref, environment_id, channel, max_ring, at,
        )
        if _rowcount(result) == 0:
            return None
        record = await pool.fetchrow(
            "SELECT * FROM fleet_update_policies "
            "WHERE tenant_ref=$1 AND environment_id=$2 AND channel=$3",
            tenant_ref, environment_id, channel,
        )
        return _policy_row(dict(record)) if record is not None else None


def _policy_row(row: dict) -> dict:
    row = dict(row)
    row["created_at"] = _iso(row.get("created_at"))
    row["updated_at"] = _iso(row.get("updated_at"))
    return row


# ── §29 upgrade plans ────────────────────────────────────────────────────────


class FleetUpgradePlanRepository(_FleetRepo):
    """One row per §29 upgrade plan composed for a managed integration.

    ``create`` enforces the full storage vocabulary: channel (§28/§29),
    behavior (§30), artifact_kind (§40), integration_kind (§6), candidate
    class + execution path (§29), and the §40 ring vocabulary on
    ``planned_ring``. Plans are composed facts — nothing here executes them.
    """

    def __init__(self) -> None:
        super().__init__()
        self._store = _PLAN_STORE

    async def create(self, view: FleetUpgradePlanRow) -> dict:
        if not is_managed_integration_kind(view.integration_kind):
            raise ValueError(
                f"unknown §6 managed integration kind {view.integration_kind!r} "
                f"— expected one of {MANAGED_INTEGRATION_KINDS}"
            )
        if not is_rollout_artifact_kind(view.artifact_kind):
            raise ValueError(
                f"unknown §40 rollout artifact kind {view.artifact_kind!r} — "
                f"expected one of {ROLLOUT_ARTIFACT_KINDS}"
            )
        if not is_release_channel(view.channel):
            raise ValueError(
                f"unknown §28/§29 release channel {view.channel!r} — expected "
                f"one of {MANAGED_RELEASE_CHANNELS}"
            )
        if not is_candidate_class(view.candidate_class):
            raise ValueError(
                f"unknown §29 candidate class {view.candidate_class!r} — "
                f"expected one of {CANDIDATE_CLASSES}"
            )
        if not (
            is_upgrade_behavior(view.behavior)
            or view.behavior == UNKNOWN_UPGRADE_BEHAVIOR
        ):
            raise ValueError(
                f"unknown §30 upgrade behavior {view.behavior!r} — expected "
                f"one of {UPGRADE_BEHAVIOR_VALUES} or "
                f"{UNKNOWN_UPGRADE_BEHAVIOR!r}"
            )
        if not is_execution_path(view.execution_path):
            raise ValueError(
                f"unknown §29 execution path {view.execution_path!r} — "
                f"expected one of {EXECUTION_PATHS}"
            )
        if view.planned_ring is not None and not is_rollout_ring(view.planned_ring):
            raise ValueError(
                f"unknown §40 rollout ring {view.planned_ring!r} — expected "
                f"one of {ROLLOUT_RINGS}"
            )
        row = view.model_dump(mode="json")
        pool = await self._ensure()
        if pool is None:
            self._store[view.plan_id] = dict(row)
            return dict(row)
        await pool.execute(
            "INSERT INTO fleet_upgrade_plans (plan_id, tenant_ref, "
            "environment_id, managed_integration_ref, integration_kind, "
            "artifact_kind, candidate_ref, candidate_class, channel, "
            "behavior, eligible, execution_path, eligibility_reasons, "
            "planned_ring, rollout_ref, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14,"
            "$15,$16)",
            view.plan_id, view.tenant_ref, view.environment_id,
            view.managed_integration_ref, view.integration_kind,
            view.artifact_kind, view.candidate_ref, view.candidate_class,
            view.channel, view.behavior, view.eligible, view.execution_path,
            _json.dumps(view.eligibility_reasons), view.planned_ring,
            view.rollout_ref, view.created_at,
        )
        return row

    async def get(
        self,
        *,
        tenant_ref: str,
        environment_id: str,
        plan_id: str,
    ) -> Optional[dict]:
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(plan_id)
            if (
                row is None
                or row.get("tenant_ref") != tenant_ref
                or row.get("environment_id") != environment_id
            ):
                return None
            return dict(row)
        record = await pool.fetchrow(
            "SELECT * FROM fleet_upgrade_plans "
            "WHERE tenant_ref=$1 AND environment_id=$2 AND plan_id=$3",
            tenant_ref, environment_id, plan_id,
        )
        return _plan_row(dict(record)) if record is not None else None

    async def list_for_tenant(
        self,
        *,
        tenant_ref: str,
        limit: int = 50,
    ) -> list[dict]:
        limit = max(0, int(limit))
        pool = await self._ensure()
        if pool is None:
            rows = [
                r
                for r in self._store.values()
                if r.get("tenant_ref") == tenant_ref
            ]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return [dict(r) for r in rows[:limit]]
        records = await pool.fetch(
            "SELECT * FROM fleet_upgrade_plans WHERE tenant_ref=$1 "
            "ORDER BY created_at DESC LIMIT $2",
            tenant_ref, limit,
        )
        return [_plan_row(dict(r)) for r in records]

    async def mark_rollout(
        self,
        *,
        tenant_ref: str,
        environment_id: str,
        plan_id: str,
        rollout_ref: str,
    ) -> Optional[dict]:
        """Stamp ``rollout_ref`` when the plan is handed to the §40 engine.

        Tenant-scoped (a cross-tenant or absent plan resolves to None); a plan
        keeps its earlier verdict — this only records the delivery fact.
        """
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(plan_id)
            if (
                row is None
                or row.get("tenant_ref") != tenant_ref
                or row.get("environment_id") != environment_id
            ):
                return None
            row["rollout_ref"] = rollout_ref
            return dict(row)
        result = await pool.execute(
            "UPDATE fleet_upgrade_plans SET rollout_ref=$4 "
            "WHERE tenant_ref=$1 AND environment_id=$2 AND plan_id=$3",
            tenant_ref, environment_id, plan_id, rollout_ref,
        )
        if _rowcount(result) == 0:
            return None
        record = await pool.fetchrow(
            "SELECT * FROM fleet_upgrade_plans WHERE plan_id=$1", plan_id
        )
        return _plan_row(dict(record)) if record is not None else None


def _plan_row(row: dict) -> dict:
    row = dict(row)
    row["eligibility_reasons"] = _parse_json(row.get("eligibility_reasons"))
    row["created_at"] = _iso(row.get("created_at"))
    return row


# ── module singletons ────────────────────────────────────────────────────────

_policy_repo: Optional[FleetUpdatePolicyRepository] = None
_plan_repo: Optional[FleetUpgradePlanRepository] = None


def get_fleet_update_policy_repository() -> FleetUpdatePolicyRepository:
    global _policy_repo
    if _policy_repo is None:
        _policy_repo = FleetUpdatePolicyRepository()
    return _policy_repo


def get_fleet_upgrade_plan_repository() -> FleetUpgradePlanRepository:
    global _plan_repo
    if _plan_repo is None:
        _plan_repo = FleetUpgradePlanRepository()
    return _plan_repo
