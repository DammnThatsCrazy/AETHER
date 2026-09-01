"""
Aether Repositories — Append-Only Graph Mutation Ledger (WP2.5)

Direct-SQL repository for the ``graph_mutation_ledger``,
``graph_fact_versions`` and ``graph_checkpoints`` tables created by alembic
migration 20260729_graph_mutation_ledger. The ledger needs semantics the
JSONB BaseRepository cannot express: a tenant-scoped partial UNIQUE
idempotency index, a BIGSERIAL total order for replay, and a transactional
close-and-append over the bitemporal version table — hence real columns and
hand-written SQL (the ``bronze_bulk`` transactional style).

Append-only contract
--------------------
Ledger rows are inserted exactly once and never updated or deleted through
this API. Bitemporal supersession happens on ``graph_fact_versions``: a new
version closes the prior open version (``valid_to`` + ``superseded_at``)
inside the same transaction that appends the ledger row.

DDL parity
----------
The alembic ``versions`` directory is not an importable package and
``alembic`` itself is not a runtime backend dependency, so the DDL constants
below are duplicated VERBATIM from
``alembic/versions/20260729_graph_mutation_ledger.py``.
``tests/unit/graph_gateway/test_ledger_ddl_parity.py`` AST-extracts the
migration's constants and asserts exact string equality — when changing
table shape, edit the migration first, then mirror it here.

Backend selection mirrors repositories/repos.py:
- ``get_pool()`` returns None (AETHER_ENV=local without DATABASE_URL) →
  shared in-memory dicts with all-or-nothing apply semantics identical to
  the SQL transaction.
- Otherwise asyncpg over the shared pool.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import parse_iso, utc_now
from shared.graph.mutation_models import MutationRecord
from shared.logger.logger import get_logger

logger = get_logger("aether.repository.graph_mutation_ledger")

# ─────────────────────────────────────────────────────────────────────────────
# DDL — duplicated verbatim from alembic migration
# 20260729_graph_mutation_ledger.py (see module docstring; parity-tested).
# ─────────────────────────────────────────────────────────────────────────────

GRAPH_MUTATION_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS graph_mutation_ledger (
    mutation_id TEXT PRIMARY KEY,
    ledger_offset BIGSERIAL,
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    actor_kind TEXT,
    actor_id TEXT,
    subject_kind TEXT,
    subject_id TEXT,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    correlation_id TEXT,
    causation_id TEXT,
    source_event_id TEXT,
    idempotency_key TEXT,
    reason_code TEXT,
    causality_class TEXT,
    confidence NUMERIC(5, 4),
    evidence_refs JSONB,
    model_refs JSONB,
    policy_refs JSONB,
    consent_refs JSONB,
    before_version_id TEXT,
    after_version_id TEXT,
    change_set_id TEXT,
    rights_decision_id TEXT,
    rights_envelope_id TEXT,
    rights_policy_set_ref TEXT,
    rights_lineage_set_hash TEXT,
    rights_source_grant_refs JSONB,
    schema_version TEXT
)
"""

GRAPH_FACT_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS graph_fact_versions (
    version_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    created_by_mutation_id TEXT
)
"""

GRAPH_CHECKPOINTS_DDL = """
CREATE TABLE IF NOT EXISTS graph_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'tenant',
    mutation_offset BIGINT,
    digest TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

GRAPH_LEDGER_INDEXES = [
    # Replayed mutations dedupe on the tenant-scoped idempotency key.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_graph_mutation_ledger_tenant_idem "
    "ON graph_mutation_ledger (tenant_id, idempotency_key) "
    "WHERE idempotency_key IS NOT NULL",
    # Aggregate history reads (audit, bitemporal reconstruction).
    "CREATE INDEX IF NOT EXISTS ix_graph_mutation_ledger_tenant_aggregate "
    "ON graph_mutation_ledger (tenant_id, aggregate_id, recorded_at)",
    # Tenant-wide ledger scans (replay, export).
    "CREATE INDEX IF NOT EXISTS ix_graph_mutation_ledger_tenant_recorded "
    "ON graph_mutation_ledger (tenant_id, recorded_at)",
    # Current (open) version lookup per aggregate for close-and-append.
    "CREATE INDEX IF NOT EXISTS ix_graph_fact_versions_open "
    "ON graph_fact_versions (tenant_id, aggregate_type, aggregate_id) "
    "WHERE superseded_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_graph_fact_versions_tenant_aggregate "
    "ON graph_fact_versions (tenant_id, aggregate_id, recorded_at)",
    "CREATE INDEX IF NOT EXISTS ix_graph_checkpoints_tenant_created "
    "ON graph_checkpoints (tenant_id, created_at DESC)",
]

# ─────────────────────────────────────────────────────────────────────────────
# In-memory backing stores (local mode). Shared across repository instances so
# the gateway, workers and tests observe one consistent view — mirroring
# repositories/repos.py::_IN_MEMORY_STORES.
# ─────────────────────────────────────────────────────────────────────────────

_MEM_LEDGER: dict[str, dict] = {}          # mutation_id → ledger row
_MEM_VERSIONS: dict[str, dict] = {}        # version_id → version row
_MEM_CHECKPOINTS: dict[str, dict] = {}     # checkpoint_id → checkpoint row
_MEM_IDEM: dict[tuple[str, str], str] = {}  # (tenant_id, idempotency_key) → mutation_id
_MEM_STATE: dict[str, int] = {"offset": 0}


def reset_graph_ledger_memory() -> None:
    """Test helper: clear every in-memory ledger store."""
    _MEM_LEDGER.clear()
    _MEM_VERSIONS.clear()
    _MEM_CHECKPOINTS.clear()
    _MEM_IDEM.clear()
    _MEM_STATE["offset"] = 0


# ─────────────────────────────────────────────────────────────────────────────
# Value normalization — rows come back as plain dicts with ISO-8601 timestamp
# strings and parsed JSON refs on BOTH backends.
# ─────────────────────────────────────────────────────────────────────────────

_TS_FIELDS = ("valid_from", "valid_to", "recorded_at", "superseded_at")
_REF_FIELDS = (
    "evidence_refs", "model_refs", "policy_refs", "consent_refs",
    "rights_source_grant_refs",
)


def _to_dt(value: Any) -> Optional[datetime]:
    """Coerce ISO string / datetime / None to a tz-aware datetime (via parse_iso)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return parse_iso(str(value))


def _iso(value: Any) -> Optional[str]:
    dt = _to_dt(value)
    return dt.isoformat() if dt is not None else None


def _json_load(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _normalize_row(row: dict) -> dict:
    out = dict(row)
    for f in _TS_FIELDS:
        if f in out:
            out[f] = _iso(out[f])
    for f in _REF_FIELDS:
        if f in out:
            out[f] = _json_load(out[f])
    if "payload" in out:
        out["payload"] = _json_load(out["payload"])
    if out.get("confidence") is not None:
        out["confidence"] = float(out["confidence"])
    if out.get("ledger_offset") is not None:
        out["ledger_offset"] = int(out["ledger_offset"])
    return out


def _record_row(record: MutationRecord) -> dict:
    """Column dict for a MutationRecord (bitemporal names preserved verbatim)."""
    row = record.model_dump()
    return row


# ─────────────────────────────────────────────────────────────────────────────
# Outcome
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LedgerAppendOutcome:
    """Result of one append: inserted or deduplicated on the idempotency key."""

    inserted: bool
    mutation_id: str
    ledger_offset: Optional[int] = None
    before_version_id: Optional[str] = None
    after_version_id: Optional[str] = None


class _DuplicateMutation(Exception):
    """Internal: idempotency-key conflict detected inside the transaction."""


# ─────────────────────────────────────────────────────────────────────────────
# Repository
# ─────────────────────────────────────────────────────────────────────────────

_LEDGER_INSERT_SQL = """
INSERT INTO graph_mutation_ledger (
    mutation_id, tenant_id, aggregate_type, aggregate_id, operation,
    actor_kind, actor_id, subject_kind, subject_id,
    valid_from, valid_to, recorded_at, superseded_at,
    correlation_id, causation_id, source_event_id, idempotency_key,
    reason_code, causality_class, confidence,
    evidence_refs, model_refs, policy_refs, consent_refs,
    before_version_id, after_version_id, change_set_id,
    rights_decision_id, rights_envelope_id, rights_policy_set_ref,
    rights_lineage_set_hash, rights_source_grant_refs, schema_version
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
    $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27,
    $28, $29, $30, $31, $32, $33
)
ON CONFLICT (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL
DO NOTHING
RETURNING ledger_offset
"""

_VERSION_INSERT_SQL = """
INSERT INTO graph_fact_versions (
    version_id, tenant_id, aggregate_type, aggregate_id, payload,
    valid_from, valid_to, recorded_at, superseded_at, created_by_mutation_id
) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, NULL, $9)
"""

_OPEN_VERSION_SQL = """
SELECT version_id, valid_from, valid_to, recorded_at, payload
FROM graph_fact_versions
WHERE tenant_id = $1 AND aggregate_type = $2 AND aggregate_id = $3
  AND superseded_at IS NULL
ORDER BY recorded_at DESC
LIMIT 1
FOR UPDATE
"""

_CLOSE_VERSION_SQL = """
UPDATE graph_fact_versions
SET valid_to = COALESCE(valid_to, $2), superseded_at = $3
WHERE version_id = $1
"""


class GraphMutationLedgerRepository:
    """Append-only ledger + bitemporal versions + replay checkpoints."""

    def __init__(self) -> None:
        self._schema_ensured = False

    async def _ensure_schema(self, pool: Any) -> None:
        if self._schema_ensured or pool is None:
            self._schema_ensured = True
            return
        for ddl in (GRAPH_MUTATION_LEDGER_DDL, GRAPH_FACT_VERSIONS_DDL, GRAPH_CHECKPOINTS_DDL):
            await pool.execute(ddl)
        for index_ddl in GRAPH_LEDGER_INDEXES:
            await pool.execute(index_ddl)
        self._schema_ensured = True

    # ── Append (transactional close-and-append) ──────────────────────────────

    async def append(
        self,
        record: MutationRecord,
        fact_payload: Optional[dict] = None,
    ) -> LedgerAppendOutcome:
        """Append one mutation; optionally version its aggregate payload.

        In one transaction (all-or-nothing on both backends):

        1. If ``fact_payload`` is provided, the aggregate's current open
           version (``superseded_at IS NULL``) is closed — ``valid_to`` is set
           to the new record's ``valid_from`` (falling back to ``recorded_at``)
           and ``superseded_at`` to the new record's ``recorded_at`` — and a
           new version row is appended.
        2. The ledger row is inserted; a tenant-scoped ``idempotency_key``
           conflict rolls the whole transaction back and reports
           ``inserted=False`` (exactly one ledger row per idempotency key).
        """
        pool = await get_pool()
        if pool is None:
            return self._memory_append(record, fact_payload)
        await self._ensure_schema(pool)
        return await self._pg_append(pool, record, fact_payload)

    def _memory_append(
        self, record: MutationRecord, fact_payload: Optional[dict]
    ) -> LedgerAppendOutcome:
        idem = (record.tenant_id, record.idempotency_key or "")
        if record.idempotency_key and idem in _MEM_IDEM:
            return LedgerAppendOutcome(inserted=False, mutation_id=_MEM_IDEM[idem])

        recorded_at = record.recorded_at or utc_now()
        before_version_id: Optional[str] = None
        after_version_id: Optional[str] = None

        # Stage everything; apply only after all staging succeeded (the
        # in-memory twin of the SQL transaction).
        staged_close: Optional[tuple[str, dict]] = None
        staged_version: Optional[tuple[str, dict]] = None
        if fact_payload is not None:
            prior = self._memory_open_version(
                record.tenant_id, record.aggregate_type, record.aggregate_id
            )
            if prior is not None:
                before_version_id = prior["version_id"]
                closed = dict(prior)
                closed["valid_to"] = closed.get("valid_to") or _iso(
                    record.valid_from or recorded_at
                )
                closed["superseded_at"] = _iso(recorded_at)
                staged_close = (prior["version_id"], closed)
            after_version_id = str(uuid.uuid4())
            staged_version = (
                after_version_id,
                {
                    "version_id": after_version_id,
                    "tenant_id": record.tenant_id,
                    "aggregate_type": record.aggregate_type,
                    "aggregate_id": record.aggregate_id,
                    "payload": dict(fact_payload),
                    "valid_from": _iso(record.valid_from or recorded_at),
                    "valid_to": _iso(record.valid_to),
                    "recorded_at": _iso(recorded_at),
                    "superseded_at": None,
                    "created_by_mutation_id": record.mutation_id,
                },
            )

        row = _record_row(record)
        row["before_version_id"] = before_version_id
        row["after_version_id"] = after_version_id
        for f in _TS_FIELDS:
            row[f] = _iso(row.get(f))
        row["recorded_at"] = row["recorded_at"] or _iso(recorded_at)
        _MEM_STATE["offset"] += 1
        row["ledger_offset"] = _MEM_STATE["offset"]

        if staged_close is not None:
            _MEM_VERSIONS[staged_close[0]] = staged_close[1]
        if staged_version is not None:
            _MEM_VERSIONS[staged_version[0]] = staged_version[1]
        _MEM_LEDGER[record.mutation_id] = row
        if record.idempotency_key:
            _MEM_IDEM[idem] = record.mutation_id
        return LedgerAppendOutcome(
            inserted=True,
            mutation_id=record.mutation_id,
            ledger_offset=row["ledger_offset"],
            before_version_id=before_version_id,
            after_version_id=after_version_id,
        )

    def _memory_open_version(
        self, tenant_id: str, aggregate_type: str, aggregate_id: str
    ) -> Optional[dict]:
        candidates = [
            v
            for v in _MEM_VERSIONS.values()
            if v["tenant_id"] == tenant_id
            and v["aggregate_type"] == aggregate_type
            and v["aggregate_id"] == aggregate_id
            and v.get("superseded_at") is None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda v: (v.get("recorded_at") or "", v["version_id"]))

    async def _pg_append(
        self, pool: Any, record: MutationRecord, fact_payload: Optional[dict]
    ) -> LedgerAppendOutcome:
        recorded_at = _to_dt(record.recorded_at) or utc_now()
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    before_version_id: Optional[str] = None
                    after_version_id: Optional[str] = None
                    if fact_payload is not None:
                        prior = await conn.fetchrow(
                            _OPEN_VERSION_SQL,
                            record.tenant_id,
                            record.aggregate_type,
                            record.aggregate_id,
                        )
                        if prior is not None:
                            before_version_id = prior["version_id"]
                            await conn.execute(
                                _CLOSE_VERSION_SQL,
                                before_version_id,
                                _to_dt(record.valid_from) or recorded_at,
                                recorded_at,
                            )
                        after_version_id = str(uuid.uuid4())
                        await conn.execute(
                            _VERSION_INSERT_SQL,
                            after_version_id,
                            record.tenant_id,
                            record.aggregate_type,
                            record.aggregate_id,
                            json.dumps(fact_payload, default=str),
                            _to_dt(record.valid_from) or recorded_at,
                            _to_dt(record.valid_to),
                            recorded_at,
                            record.mutation_id,
                        )
                    inserted = await conn.fetchrow(
                        _LEDGER_INSERT_SQL,
                        record.mutation_id,
                        record.tenant_id,
                        record.aggregate_type,
                        record.aggregate_id,
                        record.operation,
                        record.actor_kind,
                        record.actor_id,
                        record.subject_kind,
                        record.subject_id,
                        _to_dt(record.valid_from),
                        _to_dt(record.valid_to),
                        recorded_at,
                        _to_dt(record.superseded_at),
                        record.correlation_id,
                        record.causation_id,
                        record.source_event_id,
                        record.idempotency_key,
                        record.reason_code,
                        record.causality_class,
                        record.confidence,
                        json.dumps(record.evidence_refs) if record.evidence_refs is not None else None,
                        json.dumps(record.model_refs) if record.model_refs is not None else None,
                        json.dumps(record.policy_refs) if record.policy_refs is not None else None,
                        json.dumps(record.consent_refs) if record.consent_refs is not None else None,
                        before_version_id,
                        after_version_id,
                        record.change_set_id,
                        record.rights_decision_id,
                        record.rights_envelope_id,
                        record.rights_policy_set_ref,
                        record.rights_lineage_set_hash,
                        json.dumps(record.rights_source_grant_refs)
                        if record.rights_source_grant_refs is not None else None,
                        record.schema_version,
                    )
                    if inserted is None:
                        # Idempotency-key conflict: roll back the version
                        # close/append too — exactly one ledger row per key.
                        raise _DuplicateMutation()
                    return LedgerAppendOutcome(
                        inserted=True,
                        mutation_id=record.mutation_id,
                        ledger_offset=int(inserted["ledger_offset"]),
                        before_version_id=before_version_id,
                        after_version_id=after_version_id,
                    )
        except _DuplicateMutation:
            existing = await pool.fetchrow(
                "SELECT mutation_id FROM graph_mutation_ledger "
                "WHERE tenant_id = $1 AND idempotency_key = $2",
                record.tenant_id,
                record.idempotency_key,
            )
            return LedgerAppendOutcome(
                inserted=False,
                mutation_id=existing["mutation_id"] if existing else record.mutation_id,
            )

    # ── Reads ────────────────────────────────────────────────────────────────

    async def list_records(
        self,
        tenant_id: str,
        aggregate_id: Optional[str] = None,
        limit: int = 1000,
        *,
        since_offset: Optional[int] = None,
    ) -> list[dict]:
        """Ledger rows in ledger order, each joined with its after-version
        ``payload`` (the replay input shape for ``replay_ledger``).

        ``since_offset`` returns only rows *after* that ledger offset. Without
        it a resuming consumer must re-read everything it has already seen and
        discard it client-side, which means the window needed to reach one fresh
        row grows without bound as the ledger does — a consumer past its window
        stops making progress permanently. That is a stall, not a slowdown, and
        it is invisible from the outside because the consumer keeps succeeding.
        """
        pool = await get_pool()
        if pool is None:
            rows = [
                dict(r, payload=(_MEM_VERSIONS.get(r.get("after_version_id") or "") or {}).get("payload"))
                for r in _MEM_LEDGER.values()
                if r["tenant_id"] == tenant_id
                and (aggregate_id is None or r["aggregate_id"] == aggregate_id)
                and (since_offset is None or (r.get("ledger_offset") or 0) > since_offset)
            ]
            rows.sort(key=lambda r: r["ledger_offset"])
            return [_normalize_row(r) for r in rows[:limit]]
        await self._ensure_schema(pool)
        conditions = "l.tenant_id = $1"
        args: list[Any] = [tenant_id]
        if aggregate_id is not None:
            conditions += f" AND l.aggregate_id = ${len(args) + 1}"
            args.append(aggregate_id)
        if since_offset is not None:
            conditions += f" AND l.ledger_offset > ${len(args) + 1}"
            args.append(int(since_offset))
        rows = await pool.fetch(
            f"""
            SELECT l.*, v.payload AS payload
            FROM graph_mutation_ledger l
            LEFT JOIN graph_fact_versions v ON v.version_id = l.after_version_id
            WHERE {conditions}
            ORDER BY l.ledger_offset
            LIMIT {int(limit)}
            """,
            *args,
        )
        return [_normalize_row(dict(r)) for r in rows]

    async def list_fact_versions(
        self,
        tenant_id: str,
        aggregate_id: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        pool = await get_pool()
        if pool is None:
            rows = [
                dict(v)
                for v in _MEM_VERSIONS.values()
                if v["tenant_id"] == tenant_id
                and (aggregate_id is None or v["aggregate_id"] == aggregate_id)
            ]
            rows.sort(key=lambda v: (v.get("recorded_at") or "", v["version_id"]))
            return [_normalize_row(r) for r in rows[:limit]]
        await self._ensure_schema(pool)
        conditions = "tenant_id = $1"
        args: list[Any] = [tenant_id]
        if aggregate_id is not None:
            conditions += " AND aggregate_id = $2"
            args.append(aggregate_id)
        rows = await pool.fetch(
            f"""
            SELECT * FROM graph_fact_versions
            WHERE {conditions}
            ORDER BY recorded_at, version_id
            LIMIT {int(limit)}
            """,
            *args,
        )
        return [_normalize_row(dict(r)) for r in rows]

    async def record_checkpoint(
        self,
        tenant_id: str,
        scope: str,
        digest: str,
        mutation_offset: Optional[int] = None,
    ) -> dict:
        checkpoint_id = str(uuid.uuid4())
        row = {
            "checkpoint_id": checkpoint_id,
            "tenant_id": tenant_id,
            "scope": scope or "tenant",
            "mutation_offset": mutation_offset,
            "digest": digest,
            "created_at": utc_now().isoformat(),
        }
        pool = await get_pool()
        if pool is None:
            _MEM_CHECKPOINTS[checkpoint_id] = row
            return dict(row)
        await self._ensure_schema(pool)
        await pool.execute(
            """
            INSERT INTO graph_checkpoints
                (checkpoint_id, tenant_id, scope, mutation_offset, digest)
            VALUES ($1, $2, $3, $4, $5)
            """,
            checkpoint_id,
            tenant_id,
            row["scope"],
            mutation_offset,
            digest,
        )
        return dict(row)


__all__ = [
    "GRAPH_MUTATION_LEDGER_DDL",
    "GRAPH_FACT_VERSIONS_DDL",
    "GRAPH_CHECKPOINTS_DDL",
    "GRAPH_LEDGER_INDEXES",
    "GraphMutationLedgerRepository",
    "LedgerAppendOutcome",
    "reset_graph_ledger_memory",
]
