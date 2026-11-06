"""Reconciled Control Plane — durable production activation authority (Program B).

Direct-SQL repository over the two additive tables created by
``20261029_rcp_activation_authority.py`` (the migration lands ``SCHEMA_SQL``
verbatim — string-identical, parity-checked by repo-doctor, mirroring the
Phase-0/3/4 RCP repositories).

* ``rcp_control_plane_activation_states`` — one row per activation scope
  (global or tenant/environment, region-aware). ``state`` is the durable
  operational authority; environment flags can only lower the *effective*
  state and are never persisted here.
* ``rcp_control_plane_activation_transitions`` — append-only evidence for every
  advance/freeze/resume attempt that changed state, including the readiness
  snapshot reference and actor.

The update path is compare-and-set on ``revision``: two concurrent transitions
can never both win, and a stale caller receives ``None`` instead of silently
overwriting the newer authority. Tenancy is carried in the WHERE clause; a
tenant/environment-scoped row is never readable from another scope.

The module keeps the module-local in-memory fallback (``get_pool()`` None under
``AETHER_ENV=local``), so unit tests exercise the same columnar path without a
live Postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from shared.temporal.instant import coerce_utc_lenient

# Must stay string-identical to the alembic migration
# ``20261029_rcp_activation_authority.py`` (parity-checked by repo-doctor).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rcp_control_plane_activation_states (
    activation_id TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL,
    tenant_id TEXT,
    environment_id TEXT,
    region TEXT NOT NULL DEFAULT 'global',
    state TEXT NOT NULL DEFAULT 'shadow',
    previous_state TEXT,
    frozen_from_state TEXT,
    revision BIGINT NOT NULL DEFAULT 0,
    readiness_ref TEXT,
    readiness_ready BOOLEAN NOT NULL DEFAULT false,
    reason TEXT,
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (scope_kind IN ('global', 'tenant_environment')),
    CHECK (state IN ('shadow', 'detect', 'plan', 'r0', 'r1', 'r2',
                     'fully_managed', 'emergency_frozen')),
    CHECK (frozen_from_state IS NULL OR frozen_from_state IN
           ('shadow', 'detect', 'plan', 'r0', 'r1', 'r2', 'fully_managed'))
);
CREATE INDEX IF NOT EXISTS ix_rcp_activation_scope
    ON rcp_control_plane_activation_states
       (scope_kind, region, tenant_id, environment_id);
CREATE TABLE IF NOT EXISTS rcp_control_plane_activation_transitions (
    transition_id TEXT PRIMARY KEY,
    activation_id TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    transition TEXT NOT NULL,
    readiness_ref TEXT,
    readiness_ready BOOLEAN NOT NULL DEFAULT false,
    reason TEXT,
    actor TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (transition IN ('advance', 'freeze', 'resume'))
);
CREATE INDEX IF NOT EXISTS ix_rcp_activation_transition_history
    ON rcp_control_plane_activation_transitions (activation_id, created_at);
"""

# Module-local in-memory backing stores, shared by every repository instance
# (mirrors the Phase-0/3/4 RCP repositories).
_ACTIVATION_STORE: dict[str, dict] = {}
_TRANSITION_STORE: dict[str, dict] = {}


def reset_activation_stores() -> None:
    """Test helper: empty the module-local activation stores."""
    _ACTIVATION_STORE.clear()
    _TRANSITION_STORE.clear()


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


def _state_row(row: dict) -> dict:
    return {
        "activation_id": row.get("activation_id"),
        "scope_kind": row.get("scope_kind") or "global",
        "tenant_id": row.get("tenant_id"),
        "environment_id": row.get("environment_id"),
        "region": row.get("region") or "global",
        "state": row.get("state") or "shadow",
        "previous_state": row.get("previous_state"),
        "frozen_from_state": row.get("frozen_from_state"),
        "revision": int(row.get("revision") or 0),
        "readiness_ref": row.get("readiness_ref"),
        "readiness_ready": bool(row.get("readiness_ready")),
        "reason": row.get("reason"),
        "updated_by": row.get("updated_by"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _transition_row(row: dict) -> dict:
    return {
        "transition_id": row.get("transition_id"),
        "activation_id": row.get("activation_id"),
        "from_state": row.get("from_state"),
        "to_state": row.get("to_state"),
        "transition": row.get("transition"),
        "readiness_ref": row.get("readiness_ref"),
        "readiness_ready": bool(row.get("readiness_ready")),
        "reason": row.get("reason"),
        "actor": row.get("actor"),
        "created_at": _iso(row.get("created_at")),
    }


class ControlPlaneActivationRepository:
    """Durable activation states + append-only transition evidence."""

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

    async def get(self, activation_id: str) -> Optional[dict]:
        pool = await self._ensure()
        if pool is None:
            row = _ACTIVATION_STORE.get(activation_id)
            return _state_row(dict(row)) if row is not None else None
        record = await pool.fetchrow(
            "SELECT * FROM rcp_control_plane_activation_states "
            "WHERE activation_id=$1",
            activation_id,
        )
        return _state_row(dict(record)) if record is not None else None

    async def list(
        self,
        *,
        scope_kind: Optional[str] = None,
        tenant_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        region: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        pool = await self._ensure()
        if pool is None:
            rows = list(_ACTIVATION_STORE.values())
            if scope_kind is not None:
                rows = [r for r in rows if r.get("scope_kind") == scope_kind]
            if tenant_id is not None:
                rows = [r for r in rows if r.get("tenant_id") == tenant_id]
            if environment_id is not None:
                rows = [r for r in rows if r.get("environment_id") == environment_id]
            if region is not None:
                rows = [r for r in rows if (r.get("region") or "global") == region]
            rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
            return [_state_row(dict(r)) for r in rows[offset : offset + limit]]

        clauses: list[str] = []
        params: list[Any] = []
        if scope_kind is not None:
            params.append(scope_kind)
            clauses.append(f"scope_kind=${len(params)}")
        if tenant_id is not None:
            params.append(tenant_id)
            clauses.append(f"tenant_id=${len(params)}")
        if environment_id is not None:
            params.append(environment_id)
            clauses.append(f"environment_id=${len(params)}")
        if region is not None:
            params.append(region)
            clauses.append(f"region=${len(params)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        records = await pool.fetch(
            "SELECT * FROM rcp_control_plane_activation_states "
            f"{where} ORDER BY updated_at DESC, activation_id "
            f"LIMIT ${len(params) - 1} OFFSET ${len(params)}",
            *params,
        )
        return [_state_row(dict(record)) for record in records]

    async def create(self, row: dict) -> Optional[dict]:
        """Insert a first activation row; ``None`` when the key already exists."""
        payload = {
            **_state_row(row),
            "created_at": _iso(row.get("created_at")) or _now().isoformat(),
            "updated_at": _iso(row.get("updated_at")) or _now().isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            if payload["activation_id"] in _ACTIVATION_STORE:
                return None
            _ACTIVATION_STORE[payload["activation_id"]] = dict(payload)
            return _state_row(dict(payload))
        record = await pool.fetchrow(
            "INSERT INTO rcp_control_plane_activation_states "
            "(activation_id, scope_kind, tenant_id, environment_id, region, "
            "state, previous_state, frozen_from_state, revision, readiness_ref, "
            "readiness_ready, reason, updated_by, created_at, updated_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) "
            "ON CONFLICT (activation_id) DO NOTHING RETURNING *",
            payload["activation_id"], payload["scope_kind"], payload["tenant_id"],
            payload["environment_id"], payload["region"], payload["state"],
            payload["previous_state"], payload["frozen_from_state"],
            payload["revision"], payload["readiness_ref"],
            payload["readiness_ready"], payload["reason"], payload["updated_by"],
            _parse_ts(payload["created_at"]), _parse_ts(payload["updated_at"]),
        )
        return _state_row(dict(record)) if record is not None else None

    async def update(
        self,
        activation_id: str,
        *,
        expected_revision: int,
        state: str,
        previous_state: Optional[str],
        frozen_from_state: Optional[str],
        readiness_ref: Optional[str],
        readiness_ready: bool,
        reason: Optional[str],
        updated_by: Optional[str],
    ) -> Optional[dict]:
        """Compare-and-set a state transition on ``revision``.

        Returns the new row, or ``None`` when the expected revision no longer
        matches (a concurrent transition won) or the row is absent.
        """
        now = _now()
        pool = await self._ensure()
        if pool is None:
            row = _ACTIVATION_STORE.get(activation_id)
            if row is None or int(row.get("revision") or 0) != expected_revision:
                return None
            updated = {
                **row,
                "state": state,
                "previous_state": previous_state,
                "frozen_from_state": frozen_from_state,
                "revision": expected_revision + 1,
                "readiness_ref": readiness_ref,
                "readiness_ready": readiness_ready,
                "reason": reason,
                "updated_by": updated_by,
                "updated_at": now.isoformat(),
            }
            _ACTIVATION_STORE[activation_id] = updated
            return _state_row(dict(updated))
        record = await pool.fetchrow(
            "UPDATE rcp_control_plane_activation_states SET "
            "state=$2, previous_state=$3, frozen_from_state=$4, "
            "revision=revision+1, readiness_ref=$5, readiness_ready=$6, "
            "reason=$7, updated_by=$8, updated_at=$9 "
            "WHERE activation_id=$1 AND revision=$10 RETURNING *",
            activation_id, state, previous_state, frozen_from_state,
            readiness_ref, readiness_ready, reason, updated_by, now,
            expected_revision,
        )
        return _state_row(dict(record)) if record is not None else None

    async def apply_transition(
        self,
        *,
        activation_id: str,
        scope_kind: str,
        tenant_id: Optional[str],
        environment_id: Optional[str],
        region: str,
        expected_revision: int,
        state: str,
        previous_state: Optional[str],
        frozen_from_state: Optional[str],
        readiness_ref: Optional[str],
        readiness_ready: bool,
        reason: Optional[str],
        updated_by: Optional[str],
        transition: str,
        transition_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Atomically CAS the state row and append its transition evidence.

        The state write and evidence insert share one database transaction:
        a crash cannot leave a durable state change without its audit row, and
        a lost CAS never appends evidence for a transition that did not happen.
        Returns the updated state row, or ``None`` when the expected revision
        no longer matches (or a first insert lost its race).
        """
        now = _now()
        evidence = {
            "transition_id": transition_id or f"rcpat_{uuid.uuid4().hex}",
            "activation_id": activation_id,
            "from_state": previous_state or state,
            "to_state": state,
            "transition": transition,
            "readiness_ref": readiness_ref,
            "readiness_ready": readiness_ready,
            "reason": reason,
            "actor": updated_by,
            "created_at": now.isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            row = _ACTIVATION_STORE.get(activation_id)
            if row is None:
                if expected_revision != 0:
                    return None
                row = {
                    "activation_id": activation_id,
                    "scope_kind": scope_kind,
                    "tenant_id": tenant_id,
                    "environment_id": environment_id,
                    "region": region or "global",
                    "state": state,
                    "previous_state": previous_state,
                    "frozen_from_state": frozen_from_state,
                    "revision": 0,
                    "readiness_ref": None,
                    "readiness_ready": False,
                    "reason": None,
                    "updated_by": None,
                    "created_at": now.isoformat(),
                }
            elif int(row.get("revision") or 0) != expected_revision:
                return None
            updated = {
                **row,
                "state": state,
                "previous_state": previous_state,
                "frozen_from_state": frozen_from_state,
                "revision": expected_revision + 1,
                "readiness_ref": readiness_ref,
                "readiness_ready": readiness_ready,
                "reason": reason,
                "updated_by": updated_by,
                "updated_at": now.isoformat(),
            }
            _ACTIVATION_STORE[activation_id] = updated
            _TRANSITION_STORE[evidence["transition_id"]] = dict(evidence)
            return _state_row(dict(updated))

        parameters = (
            activation_id,
            scope_kind,
            tenant_id,
            environment_id,
            region or "global",
            state,
            previous_state,
            frozen_from_state,
            readiness_ref,
            readiness_ready,
            reason,
            updated_by,
            now,
        )
        async with pool.acquire() as conn:
            async with conn.transaction():
                record = None
                if expected_revision == 0:
                    record = await conn.fetchrow(
                        "INSERT INTO rcp_control_plane_activation_states "
                        "(activation_id, scope_kind, tenant_id, environment_id, "
                        "region, state, previous_state, frozen_from_state, "
                        "revision, readiness_ref, readiness_ready, reason, "
                        "updated_by, created_at, updated_at) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,1,$9,$10,$11,$12,$13,$13) "
                        "ON CONFLICT (activation_id) DO NOTHING RETURNING *",
                        *parameters,
                    )
                if record is None:
                    record = await conn.fetchrow(
                        "UPDATE rcp_control_plane_activation_states SET "
                        "state=$2, previous_state=$3, frozen_from_state=$4, "
                        "revision=revision+1, readiness_ref=$5, "
                        "readiness_ready=$6, reason=$7, updated_by=$8, "
                        "updated_at=$9 "
                        "WHERE activation_id=$1 AND revision=$10 RETURNING *",
                        activation_id,
                        state,
                        previous_state,
                        frozen_from_state,
                        readiness_ref,
                        readiness_ready,
                        reason,
                        updated_by,
                        now,
                        expected_revision,
                    )
                if record is None:
                    return None
                await conn.execute(
                    "INSERT INTO rcp_control_plane_activation_transitions "
                    "(transition_id, activation_id, from_state, to_state, "
                    "transition, readiness_ref, readiness_ready, reason, actor, "
                    "created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                    evidence["transition_id"],
                    evidence["activation_id"],
                    evidence["from_state"],
                    evidence["to_state"],
                    evidence["transition"],
                    evidence["readiness_ref"],
                    evidence["readiness_ready"],
                    evidence["reason"],
                    evidence["actor"],
                    _parse_ts(evidence["created_at"]),
                )
        return _state_row(dict(record))

    async def record_transition(
        self,
        *,
        activation_id: str,
        from_state: str,
        to_state: str,
        transition: str,
        readiness_ref: Optional[str],
        readiness_ready: bool,
        reason: Optional[str],
        actor: Optional[str],
        transition_id: Optional[str] = None,
    ) -> dict:
        row = {
            "transition_id": transition_id or f"rcpat_{uuid.uuid4().hex}",
            "activation_id": activation_id,
            "from_state": from_state,
            "to_state": to_state,
            "transition": transition,
            "readiness_ref": readiness_ref,
            "readiness_ready": readiness_ready,
            "reason": reason,
            "actor": actor,
            "created_at": _now().isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            _TRANSITION_STORE[row["transition_id"]] = dict(row)
            return _transition_row(dict(row))
        await pool.execute(
            "INSERT INTO rcp_control_plane_activation_transitions "
            "(transition_id, activation_id, from_state, to_state, transition, "
            "readiness_ref, readiness_ready, reason, actor, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            row["transition_id"], row["activation_id"], row["from_state"],
            row["to_state"], row["transition"], row["readiness_ref"],
            row["readiness_ready"], row["reason"], row["actor"],
            _parse_ts(row["created_at"]),
        )
        return _transition_row(row)

    async def list_transitions(
        self,
        *,
        activation_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        pool = await self._ensure()
        if pool is None:
            rows = [
                r for r in _TRANSITION_STORE.values()
                if r.get("activation_id") == activation_id
            ]
            rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
            return [_transition_row(dict(r)) for r in rows[offset : offset + limit]]
        records = await pool.fetch(
            "SELECT * FROM rcp_control_plane_activation_transitions "
            "WHERE activation_id=$1 ORDER BY created_at DESC, transition_id "
            "LIMIT $2 OFFSET $3",
            activation_id, limit, offset,
        )
        return [_transition_row(dict(record)) for record in records]


_REPOSITORY: Optional[ControlPlaneActivationRepository] = None


def get_activation_repository() -> ControlPlaneActivationRepository:
    """Process-wide repository (routes and engines share one in-memory mirror)."""
    global _REPOSITORY
    if _REPOSITORY is None:
        _REPOSITORY = ControlPlaneActivationRepository()
    return _REPOSITORY


__all__ = [
    "ControlPlaneActivationRepository",
    "SCHEMA_SQL",
    "get_activation_repository",
    "reset_activation_stores",
]
