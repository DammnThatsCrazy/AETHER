"""Bulk typed-Bronze ingestion + transactional outbox (PR 5 / FT-5-INGESTION-V2).

This is the correctness core of the /v1/batch V2 path. It replaces the V1
per-event write loop (per-event Bronze insert + per-event Redis SET NX +
per-event fire-and-forget identity task + in-request broker publish) with a
single transactional unit of work:

    ONE pool connection, ONE transaction:
      1. bulk-insert Bronze rows      ON CONFLICT (tenant_id, event_id,
                                       schema_version) DO NOTHING
      2. bulk-insert outbox rows      ON CONFLICT (tenant_id, event_id, topic)
                                       DO NOTHING   (only for ACCEPTED events)
      3. commit once
    Roll back BOTH on any failure.

Database uniqueness is the source of truth for idempotency — Redis is not
consulted. The relay worker that drains ``event_outbox`` and publishes to the
bus is a later PR (PR 6); this module only makes the writes durable.

Local / test mode: when ``get_pool()`` returns ``None`` (AETHER_ENV=local, no
asyncpg), an in-memory fallback dedupes by ``(tenant_id, event_id,
schema_version)`` / ``(tenant_id, event_id, topic)`` against the shared
``_IN_MEMORY_STORES`` dicts for the ``bronze_sdk_events`` and ``event_outbox``
tables — so the same behaviour (accept / duplicate / atomic rollback) is
observable without a database.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional, Sequence

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.ingestion.bronze_bulk")

# Outbox lifecycle statuses (mirrors the event_outbox.status CHECK-free column).
OUTBOX_PENDING = "pending"
OUTBOX_CLAIMED = "claimed"
OUTBOX_PUBLISHED = "published"
OUTBOX_RETRY = "retry"
OUTBOX_DEAD_LETTER = "dead_letter"

_BRONZE_TABLE = "bronze_sdk_events"
_OUTBOX_TABLE = "event_outbox"


# ── Input / output dataclasses ───────────────────────────────────────────────

@dataclass(frozen=True)
class BronzeSDKEvent:
    """One typed Bronze SDK event row to persist.

    ``payload`` is the normalized event body (properties + context + envelope);
    it is stored both in the typed ``payload`` JSONB column and, together with
    the typed columns, forms the BaseRepository ``data`` envelope.
    """

    tenant_id: str
    event_id: str
    schema_version: str
    batch_id: str
    event_type: str
    event_family: str
    event_timestamp: str  # ISO8601
    received_at: str  # ISO8601
    session_id: str
    anonymous_id: str
    user_id: Optional[str]
    entity_id: str
    payload: dict
    source: str = "sdk"
    source_tag: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.tenant_id, self.event_id, self.schema_version)


@dataclass(frozen=True)
class OutboxEvent:
    """One transactional-outbox row to enqueue for a later relay publish."""

    tenant_id: str
    event_id: str
    topic: str
    partition_key: str
    payload: dict
    status: str = OUTBOX_PENDING
    available_at: Optional[str] = None  # ISO8601; defaults to now at insert

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.tenant_id, self.event_id, self.topic)


@dataclass
class BulkIngestResult:
    """Outcome of a bulk ingest, with per-record status in INPUT order."""

    statuses: list[str] = field(default_factory=list)  # "accepted" | "duplicate"
    accepted_event_ids: list[str] = field(default_factory=list)
    duplicate_event_ids: list[str] = field(default_factory=list)
    outbox_written: int = 0

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_event_ids)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicate_event_ids)


# ── Deterministic row identity / serialization ───────────────────────────────

def _bronze_id(tenant_id: str, event_id: str, schema_version: str) -> str:
    raw = f"bronze:{tenant_id}:{event_id}:{schema_version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _outbox_id(tenant_id: str, event_id: str, topic: str) -> str:
    raw = f"outbox:{tenant_id}:{event_id}:{topic}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _payload_bytes_and_hash(payload: dict) -> tuple[int, str]:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return len(encoded), hashlib.sha256(encoded).hexdigest()


def _bronze_row(rec: BronzeSDKEvent) -> dict:
    """Full record persisted to the ``data`` JSONB envelope (BaseRepository shape)."""
    payload_bytes, payload_hash = _payload_bytes_and_hash(rec.payload)
    now = utc_now().isoformat()
    return {
        "id": _bronze_id(rec.tenant_id, rec.event_id, rec.schema_version),
        "tenant_id": rec.tenant_id,
        "event_id": rec.event_id,
        "schema_version": rec.schema_version,
        "batch_id": rec.batch_id,
        "event_type": rec.event_type,
        "event_family": rec.event_family,
        "event_timestamp": rec.event_timestamp,
        "received_at": rec.received_at,
        "session_id": rec.session_id,
        "anonymous_id": rec.anonymous_id,
        "user_id": rec.user_id,
        "entity_id": rec.entity_id,
        "payload": rec.payload,
        "payload_bytes": payload_bytes,
        "payload_hash": payload_hash,
        "source": rec.source,
        "source_tag": rec.source_tag,
        "created_at": now,
        "updated_at": now,
    }


def _outbox_row(ob: OutboxEvent) -> dict:
    now = utc_now().isoformat()
    return {
        "id": _outbox_id(ob.tenant_id, ob.event_id, ob.topic),
        "tenant_id": ob.tenant_id,
        "event_id": ob.event_id,
        "topic": ob.topic,
        "partition_key": ob.partition_key,
        "payload": ob.payload,
        "status": ob.status or OUTBOX_PENDING,
        "attempt_count": 0,
        "available_at": ob.available_at or now,
        "claimed_at": None,
        "claim_owner": None,
        "published_at": None,
        "last_error": None,
        "created_at": now,
        "updated_at": now,
    }


# ── Failure-injection hook (in-memory rollback test) ─────────────────────────

def _commit_hook() -> None:
    """No-op commit barrier for the in-memory path.

    Tests monkeypatch this to raise, simulating a mid-commit transaction failure
    so the atomic rollback of BOTH Bronze and outbox can be asserted.
    """
    return None


# ── Public entrypoint ────────────────────────────────────────────────────────

async def ingest_many(
    records: Sequence[BronzeSDKEvent],
    outbox_events: Sequence[OutboxEvent],
) -> BulkIngestResult:
    """Persist Bronze rows + outbox rows for accepted events in one transaction.

    ``records`` and ``outbox_events`` are index-aligned (row ``i`` of each
    describes the same event). Repeated ``(tenant_id, event_id, schema_version)``
    keys within ``records`` are de-duplicated (first occurrence wins); the later
    occurrences are reported as ``duplicate``. An outbox row is written only for
    an ACCEPTED (newly-persisted) Bronze row, so a re-ingested event is never
    re-queued for publish.

    Returns a :class:`BulkIngestResult` whose ``statuses`` list is aligned to the
    INPUT order of ``records``.
    """
    unique, statuses, orig_index = _preprocess(records)

    if not unique:
        # Everything was an intra-batch duplicate — nothing to persist.
        return _finalize(records, statuses)

    from repositories.repos import get_pool

    pool = await get_pool()
    if pool is None:
        persisted = _memory_commit(unique, outbox_events, orig_index)
    else:
        persisted = await _pg_commit(pool, unique, outbox_events, orig_index)

    # Resolve accepted/duplicate for the unique records against what persisted.
    for i, rec in zip(orig_index, unique):
        statuses[i] = "accepted" if rec.key in persisted else "duplicate"

    return _finalize(records, statuses)


def _preprocess(
    records: Sequence[BronzeSDKEvent],
) -> tuple[list[BronzeSDKEvent], list[str], list[int]]:
    """Split input into first-occurrence uniques and intra-batch duplicates.

    Returns (unique_records, statuses, orig_index) where ``statuses`` is
    pre-seeded with ``duplicate`` for intra-batch repeats and a placeholder for
    uniques (resolved later), and ``orig_index[k]`` is the input index of
    ``unique_records[k]``.
    """
    statuses: list[str] = ["duplicate"] * len(records)
    seen: set[tuple[str, str, str]] = set()
    unique: list[BronzeSDKEvent] = []
    orig_index: list[int] = []
    for i, rec in enumerate(records):
        if rec.key in seen:
            statuses[i] = "duplicate"  # intra-request repeat
            continue
        seen.add(rec.key)
        unique.append(rec)
        orig_index.append(i)
    return unique, statuses, orig_index


def _finalize(records: Sequence[BronzeSDKEvent], statuses: list[str]) -> BulkIngestResult:
    result = BulkIngestResult(statuses=list(statuses))
    for rec, status in zip(records, statuses):
        if status == "accepted":
            result.accepted_event_ids.append(rec.event_id)
        else:
            result.duplicate_event_ids.append(rec.event_id)
    result.outbox_written = result.accepted_count
    metrics.increment("ingestion_v2_bronze_accepted_total", value=result.accepted_count)
    metrics.increment("ingestion_v2_bronze_duplicate_total", value=result.duplicate_count)
    return result


# ── In-memory backend (AETHER_ENV=local / no asyncpg) ────────────────────────

def _memory_stores() -> tuple[dict, dict]:
    """Resolve the shared in-memory table dicts lazily.

    Looked up on every call (not cached at import) so that suites which evict
    and re-import ``repositories.repos`` always see the CURRENT module
    generation's stores rather than a detached copy.
    """
    from repositories.repos import _IN_MEMORY_STORES

    bronze = _IN_MEMORY_STORES.setdefault(_BRONZE_TABLE, {})
    outbox = _IN_MEMORY_STORES.setdefault(_OUTBOX_TABLE, {})
    return bronze, outbox


def _memory_commit(
    unique: Sequence[BronzeSDKEvent],
    outbox_events: Sequence[OutboxEvent],
    orig_index: Sequence[int],
) -> set[tuple[str, str, str]]:
    """Atomically persist new Bronze rows + their outbox rows in memory.

    Emulates ON CONFLICT DO NOTHING (skip if the composite key already exists)
    and a single transaction: a failure at the ``_commit_hook`` barrier (or any
    exception while applying) rolls back BOTH tables so nothing is persisted.
    """
    bronze_store, outbox_store = _memory_stores()

    # Stage Bronze rows that are new (not already present under their id).
    staged_bronze: list[tuple[str, dict, tuple[str, str, str]]] = []
    persisted: set[tuple[str, str, str]] = set()
    for rec in unique:
        rid = _bronze_id(rec.tenant_id, rec.event_id, rec.schema_version)
        if rid in bronze_store:
            continue  # already durable (cross-request duplicate)
        staged_bronze.append((rid, _bronze_row(rec), rec.key))
        persisted.add(rec.key)

    # Stage outbox rows only for accepted (newly-persisted) events.
    staged_outbox: list[tuple[str, dict]] = []
    for k, rec in zip(orig_index, unique):
        if rec.key not in persisted:
            continue
        ob = outbox_events[k] if k < len(outbox_events) else None
        if ob is None:
            continue
        oid = _outbox_id(ob.tenant_id, ob.event_id, ob.topic)
        if oid in outbox_store:
            continue
        staged_outbox.append((oid, _outbox_row(ob)))

    # Apply as a single unit; undo on any failure so the write is all-or-nothing.
    applied_bronze: list[str] = []
    applied_outbox: list[str] = []
    try:
        for rid, row, _ in staged_bronze:
            bronze_store[rid] = row
            applied_bronze.append(rid)
        _commit_hook()  # injectable mid-commit failure point
        for oid, row in staged_outbox:
            outbox_store[oid] = row
            applied_outbox.append(oid)
    except Exception:
        for rid in applied_bronze:
            bronze_store.pop(rid, None)
        for oid in applied_outbox:
            outbox_store.pop(oid, None)
        metrics.increment("ingestion_v2_transaction_rollback_total")
        logger.error("bulk ingest rolled back (in-memory) — no rows persisted")
        raise

    return persisted


# ── PostgreSQL backend (asyncpg pool) ────────────────────────────────────────

_BRONZE_INSERT_SQL = """
INSERT INTO bronze_sdk_events (
    id, data, tenant_id, event_id, schema_version, batch_id, event_type,
    event_family, event_timestamp, received_at, session_id, anonymous_id,
    user_id, entity_id, payload, payload_bytes, payload_hash, source,
    source_tag, created_at, updated_at
)
SELECT
    r.id, r.data, r.tenant_id, r.event_id, r.schema_version, r.batch_id,
    r.event_type, r.event_family, r.event_timestamp, r.received_at,
    r.session_id, r.anonymous_id, r.user_id, r.entity_id, r.payload,
    r.payload_bytes, r.payload_hash, r.source, r.source_tag, now(), now()
FROM jsonb_to_recordset($1::jsonb) AS r(
    id text, data jsonb, tenant_id text, event_id text, schema_version text,
    batch_id text, event_type text, event_family text,
    event_timestamp timestamptz, received_at timestamptz,
    session_id text, anonymous_id text, user_id text, entity_id text,
    payload jsonb, payload_bytes integer, payload_hash text, source text,
    source_tag text
)
ON CONFLICT (tenant_id, event_id, schema_version) DO NOTHING
RETURNING tenant_id, event_id, schema_version
"""

_OUTBOX_INSERT_SQL = """
INSERT INTO event_outbox (
    id, data, tenant_id, event_id, topic, partition_key, payload, status,
    attempt_count, available_at, created_at, updated_at
)
SELECT
    r.id, r.data, r.tenant_id, r.event_id, r.topic, r.partition_key,
    r.payload, r.status, 0, r.available_at, now(), now()
FROM jsonb_to_recordset($1::jsonb) AS r(
    id text, data jsonb, tenant_id text, event_id text, topic text,
    partition_key text, payload jsonb, status text, available_at timestamptz
)
ON CONFLICT (tenant_id, event_id, topic) DO NOTHING
"""


async def _pg_commit(
    pool,
    unique: Sequence[BronzeSDKEvent],
    outbox_events: Sequence[OutboxEvent],
    orig_index: Sequence[int],
) -> set[tuple[str, str, str]]:
    """Persist Bronze + outbox in ONE asyncpg transaction; return persisted keys."""
    bronze_rows = [_bronze_row(rec) for rec in unique]
    bronze_json = json.dumps(
        [_as_bronze_record_param(row) for row in bronze_rows], default=str
    )

    async with pool.acquire() as conn:
        async with conn.transaction():
            returned = await conn.fetch(_BRONZE_INSERT_SQL, bronze_json)
            persisted = {
                (r["tenant_id"], r["event_id"], r["schema_version"]) for r in returned
            }

            # Build outbox rows only for events whose Bronze row was inserted.
            outbox_payload: list[dict] = []
            for k, rec in zip(orig_index, unique):
                if rec.key not in persisted:
                    continue
                ob = outbox_events[k] if k < len(outbox_events) else None
                if ob is None:
                    continue
                outbox_payload.append(_as_outbox_record_param(_outbox_row(ob)))

            if outbox_payload:
                await conn.execute(_OUTBOX_INSERT_SQL, json.dumps(outbox_payload, default=str))

    return persisted


def _as_bronze_record_param(row: dict) -> dict:
    """Shape a Bronze row for jsonb_to_recordset (nested JSONB kept as objects)."""
    return {
        "id": row["id"],
        "data": row,  # BaseRepository envelope — the full record
        "tenant_id": row["tenant_id"],
        "event_id": row["event_id"],
        "schema_version": row["schema_version"],
        "batch_id": row["batch_id"],
        "event_type": row["event_type"],
        "event_family": row["event_family"],
        "event_timestamp": row["event_timestamp"],
        "received_at": row["received_at"],
        "session_id": row["session_id"],
        "anonymous_id": row["anonymous_id"],
        "user_id": row["user_id"],
        "entity_id": row["entity_id"],
        "payload": row["payload"],
        "payload_bytes": row["payload_bytes"],
        "payload_hash": row["payload_hash"],
        "source": row["source"],
        "source_tag": row["source_tag"],
    }


def _as_outbox_record_param(row: dict) -> dict:
    return {
        "id": row["id"],
        "data": row,  # BaseRepository envelope — the full outbox record
        "tenant_id": row["tenant_id"],
        "event_id": row["event_id"],
        "topic": row["topic"],
        "partition_key": row["partition_key"],
        "payload": row["payload"],
        "status": row["status"],
        "available_at": row["available_at"],
    }
