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
from shared.integrity import hash_chain
from shared.logger.logger import get_logger, metrics
from services.ingestion.acquisition_privacy import sanitize_acquisition_payload

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


def _bronze_row(rec: BronzeSDKEvent, now: Optional[str] = None) -> dict:
    """Full record persisted to the ``data`` JSONB envelope (BaseRepository shape).

    ``now`` may be supplied by the caller so every row in one ingest batch shares
    an identical ``created_at`` — the hash chain relies on ``created_at`` being
    uniform within a batch (and strictly increasing across batches) to give a
    well-defined append order (see ``_chain_sort_key``). Omitting it (e.g. the
    unit tests that build a single row) falls back to a per-row timestamp,
    unchanged from the original behaviour.
    """
    payload = sanitize_acquisition_payload(rec.payload)
    payload_bytes, payload_hash = _payload_bytes_and_hash(payload)
    now = now or utc_now().isoformat()
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
        "payload": payload,
        "payload_bytes": payload_bytes,
        "payload_hash": payload_hash,
        "source": rec.source,
        "source_tag": rec.source_tag,
        # Append-only hash-chain columns (LEDGER M2). Default None = "not yet
        # chained": a duplicate row that ON CONFLICT skips, or a pre-cutover
        # historical row. `_chain_rows` overwrites these for every genuinely new
        # row before it is persisted.
        "prev_hash": None,
        "integrity_hash": None,
        "created_at": now,
        "updated_at": now,
    }


def _outbox_row(ob: OutboxEvent, now: Optional[str] = None) -> dict:
    """One transactional-outbox row to persist.

    ``now`` may be supplied by the caller so every outbox row in one ingest batch
    shares an identical ``created_at`` — the outbox hash chain (LEDGER M4) relies
    on ``created_at`` being uniform within a batch (and strictly increasing across
    batches) to give a well-defined append order (see ``_outbox_chain_sort_key``),
    exactly as ``_bronze_row`` does for the Bronze chain. ``payload_hash`` is a
    stable ``sort_keys`` SHA-256 of the already-sanitized payload, computed once
    here and carried in the ``data`` envelope so it is the content digest the
    chain hashes (and ``verify_chain`` re-reads) rather than a re-serialization of
    round-tripped JSONB.
    """
    now = now or utc_now().isoformat()
    payload = sanitize_acquisition_payload(ob.payload)
    _, payload_hash = _payload_bytes_and_hash(payload)
    return {
        "id": _outbox_id(ob.tenant_id, ob.event_id, ob.topic),
        "tenant_id": ob.tenant_id,
        "event_id": ob.event_id,
        "topic": ob.topic,
        "partition_key": ob.partition_key,
        "payload": payload,
        "payload_hash": payload_hash,
        "status": ob.status or OUTBOX_PENDING,
        "attempt_count": 0,
        "available_at": ob.available_at or now,
        "claimed_at": None,
        "claim_owner": None,
        "published_at": None,
        "last_error": None,
        # Append-only hash-chain columns (LEDGER M4). Default None = "not yet
        # chained": a duplicate row that ON CONFLICT skips, or a pre-cutover
        # historical row. `_chain_outbox_rows` overwrites these for every
        # genuinely new row before it is persisted.
        "prev_hash": None,
        "integrity_hash": None,
        "created_at": now,
        "updated_at": now,
    }


# ── Append-only hash chain (LEDGER M2) ───────────────────────────────────────
# Bronze rows get the same tamper-evidence AuditLedger already has: a per-tenant
# SHA-256 chain (shared/integrity/hash_chain.py). Each NEW row's integrity_hash
# folds its canonical event identity with the previous row's integrity_hash, so
# deleting, editing, or reordering a chained row is detectable by verify_chain.
#
# Partition key = tenant_id: every tenant owns an independent chain, so one
# tenant's rows never reference another's (matches AuditLedger and the primitive's
# documented "likely tenant_id" expectation). This is the natural per-stream key
# for Bronze — there is no coarser or more meaningful isolation boundary than the
# tenant for an append-only ledger of that tenant's events.
#
# Chain order within a partition = (created_at, event_id, schema_version). Bronze
# is append-only, so the chain must follow INGEST order, not event-occurrence
# order (event_timestamp): a late-arriving event appends to the tail, it does not
# splice into the middle. created_at is uniform within one ingest transaction and
# strictly increases across transactions, so it separates batches; (event_id,
# schema_version) — the tail of the row's unique key (tenant_id, event_id,
# schema_version) — is a total order for the rows sharing a batch's created_at.


def _chain_partition(row: dict) -> str:
    """The independent-chain key for a Bronze row (per tenant)."""
    return row.get("tenant_id") or ""


def _chain_sort_key(row: dict) -> tuple[str, str, str]:
    """Deterministic append order within a tenant's chain.

    See the section header: ``created_at`` orders/segregates batches; the
    ``(event_id, schema_version)`` tail of the unique key totally orders the rows
    of a single batch (which share one ``created_at``). Also used as the
    ``sort_key`` when re-walking the chain in ``verify_chain``.
    """
    return (row.get("created_at") or "", row.get("event_id") or "", row.get("schema_version") or "")


def _canonical_fields(row: dict) -> dict:
    """The STABLE, tamper-evident identity of one Bronze event to hash.

    Only fields that are immutable for a given event participate: its identity
    key (``tenant_id``/``event_id``/``schema_version``), when it OCCURRED
    (``event_timestamp`` — deliberately NOT the ingest-assigned, volatile
    ``received_at``), its type, and a stable content digest (``payload_hash``, a
    ``sort_keys`` SHA-256 of the already-sanitized payload). Volatile ingest
    metadata — ``received_at``, ``batch_id``, the derived row ``id``,
    ``created_at``/``updated_at`` — is excluded so the hash depends only on the
    event itself, exactly as ``AuditLedger`` excludes its persistence-assigned
    ``created_at``. ``prev_hash`` is excluded here too: the shared primitive folds
    it in (``hash_chain.compute_integrity_hash``).

    Every field read here is reconstructable from a stored row (typed column and
    ``data`` envelope alike), so ``verify_chain`` can re-derive the exact hash.
    """
    return {
        "event_id": row.get("event_id"),
        "tenant_id": row.get("tenant_id"),
        "schema_version": row.get("schema_version"),
        "event_type": row.get("event_type"),
        "event_timestamp": row.get("event_timestamp"),
        "payload_hash": row.get("payload_hash"),
    }


def _chain_rows(new_rows: list[dict], prior_tail: dict[str, str]) -> None:
    """Populate ``prev_hash``/``integrity_hash`` on each NEW row, in place.

    Rows are grouped by tenant partition and chained in append order
    (``_chain_sort_key``). The first row of a partition chains onto that tenant's
    prior tail — the ``integrity_hash`` of its last already-chained row, passed in
    ``prior_tail`` — when one exists, or begins a fresh chain otherwise
    (``prev_hash = None``, the pre-cutover boundary). Successive rows of the same
    batch chain to each other. ``new_rows`` must already be scoped to rows that
    will actually be persisted (never intra-batch or cross-request duplicates),
    so the stored chain has no gaps.
    """
    by_partition: dict[str, list[dict]] = {}
    for row in new_rows:
        by_partition.setdefault(_chain_partition(row), []).append(row)
    for partition, rows in by_partition.items():
        rows.sort(key=_chain_sort_key)
        prev = prior_tail.get(partition)  # None → fresh chain (pre-cutover boundary)
        for row in rows:
            integrity = hash_chain.compute_integrity_hash(_canonical_fields(row), prev or "")
            # Store the actual previous integrity_hash (None for a chain head), so
            # the column is a readable back-link; verify_chain re-derives prev from
            # the running chain, treating a head's absent prev as "".
            row["prev_hash"] = prev
            row["integrity_hash"] = integrity
            prev = integrity


def _memory_prior_tail(bronze_store: dict, partitions: set[str]) -> dict[str, str]:
    """Per-tenant chain tail (last chained integrity_hash) from the in-memory store.

    Rows with a NULL ``integrity_hash`` (pre-cutover / historical) are ignored —
    they are not chain anchors, so a partition with only such rows returns no tail
    and its first new row starts a fresh chain.
    """
    best: dict[str, tuple[tuple[str, str, str], str]] = {}
    for row in bronze_store.values():
        integrity = row.get("integrity_hash")
        if not integrity:
            continue
        partition = _chain_partition(row)
        if partition not in partitions:
            continue
        key = _chain_sort_key(row)
        if partition not in best or key > best[partition][0]:
            best[partition] = (key, integrity)
    return {partition: integrity for partition, (_, integrity) in best.items()}


# ── Append-only hash chain for the outbox (LEDGER M4) ────────────────────────
# The transactional outbox gets the SAME per-tenant tamper-evidence the Bronze
# tier got in M2 — an independent SHA-256 chain per tenant over each NEW outbox
# row (shared/integrity/hash_chain.py), populated in the SAME transaction that
# writes the row. Deleting, editing, or reordering a chained outbox row is then
# detectable by verify_chain, so the relay's queue of "what will be published"
# is as tamper-evident as the Bronze events it was derived from.
#
# Partition key = tenant_id, identical to Bronze: every tenant owns an
# independent outbox chain (matches AuditLedger and the primitive's documented
# per-tenant expectation), so one tenant's outbox rows never reference another's.
#
# Chain order within a partition = (created_at, event_id, topic). The outbox is
# append-only, so the chain follows INGEST order: created_at is uniform within one
# ingest transaction and strictly increases across transactions (separating
# batches); (event_id, topic) — the tail of the row's unique key (tenant_id,
# event_id, topic) — totally orders the rows sharing a batch's created_at.
#
# Canonical (hashed) fields = the outbox row's STABLE routing identity plus a
# content digest: event_id, tenant_id, topic, partition_key, payload_hash. These
# are exactly the fields that are immutable for a given queued event. Volatile
# lifecycle/ingest metadata — status, attempt_count, available_at, claimed_at,
# claim_owner, published_at, last_error, the derived row id, created_at/updated_at
# — is excluded so the hash depends only on WHAT is to be published, not on the
# relay's mutable delivery state. (The outbox row, unlike a Bronze event, carries
# no stable event-occurrence timestamp of its own — available_at/created_at are
# ingest-assigned — so occurrence is captured via payload_hash, the digest of the
# event body, rather than a separate volatile timestamp.) prev_hash is folded in
# by the shared primitive, not listed here.


def _outbox_chain_partition(row: dict) -> str:
    """The independent-chain key for an outbox row (per tenant)."""
    return row.get("tenant_id") or ""


def _outbox_chain_sort_key(row: dict) -> tuple[str, str, str]:
    """Deterministic append order within a tenant's outbox chain.

    ``created_at`` orders/segregates batches; the ``(event_id, topic)`` tail of
    the unique key totally orders the rows of a single batch (which share one
    ``created_at``). Also used as the ``sort_key`` when re-walking the chain in
    ``verify_chain``.
    """
    return (row.get("created_at") or "", row.get("event_id") or "", row.get("topic") or "")


def _outbox_canonical_fields(row: dict) -> dict:
    """The STABLE, tamper-evident identity of one outbox row to hash.

    Only fields immutable for a given queued event participate: its routing
    identity (``tenant_id``/``event_id``/``topic``/``partition_key``) and a stable
    content digest (``payload_hash`` — a ``sort_keys`` SHA-256 of the already-
    sanitized payload, stored at write time). Volatile relay/ingest metadata
    (``status``, ``attempt_count``, ``available_at``, ``claimed_at``,
    ``claim_owner``, ``published_at``, ``last_error``, the derived row ``id``,
    ``created_at``/``updated_at``) is excluded so the hash depends only on the
    event to be published. ``prev_hash`` is excluded here too: the shared
    primitive folds it in (``hash_chain.compute_integrity_hash``).

    Every field read here is reconstructable from a stored row's ``data``
    envelope, so ``verify_chain`` can re-derive the exact hash.
    """
    return {
        "event_id": row.get("event_id"),
        "tenant_id": row.get("tenant_id"),
        "topic": row.get("topic"),
        "partition_key": row.get("partition_key"),
        "payload_hash": row.get("payload_hash"),
    }


def _chain_outbox_rows(new_rows: list[dict], prior_tail: dict[str, str]) -> None:
    """Populate ``prev_hash``/``integrity_hash`` on each NEW outbox row, in place.

    Rows are grouped by tenant partition and chained in append order
    (``_outbox_chain_sort_key``). The first row of a partition chains onto that
    tenant's prior tail — the ``integrity_hash`` of its last already-chained outbox
    row, passed in ``prior_tail`` — when one exists, or begins a fresh chain
    otherwise (``prev_hash = None``, the pre-cutover boundary). Successive rows of
    the same batch chain to each other. ``new_rows`` must already be scoped to rows
    that will actually be persisted (never intra-batch or cross-request
    duplicates), so the stored chain has no gaps.
    """
    by_partition: dict[str, list[dict]] = {}
    for row in new_rows:
        by_partition.setdefault(_outbox_chain_partition(row), []).append(row)
    for partition, rows in by_partition.items():
        rows.sort(key=_outbox_chain_sort_key)
        prev = prior_tail.get(partition)  # None → fresh chain (pre-cutover boundary)
        for row in rows:
            integrity = hash_chain.compute_integrity_hash(
                _outbox_canonical_fields(row), prev or ""
            )
            # Store the actual previous integrity_hash (None for a chain head), so
            # the column is a readable back-link; verify_chain re-derives prev from
            # the running chain, treating a head's absent prev as "".
            row["prev_hash"] = prev
            row["integrity_hash"] = integrity
            prev = integrity


def _memory_outbox_prior_tail(outbox_store: dict, partitions: set[str]) -> dict[str, str]:
    """Per-tenant outbox chain tail (last chained integrity_hash) from the store.

    Rows with a NULL ``integrity_hash`` (pre-cutover / historical) are ignored —
    they are not chain anchors, so a partition with only such rows returns no tail
    and its first new row starts a fresh chain.
    """
    best: dict[str, tuple[tuple[str, str, str], str]] = {}
    for row in outbox_store.values():
        integrity = row.get("integrity_hash")
        if not integrity:
            continue
        partition = _outbox_chain_partition(row)
        if partition not in partitions:
            continue
        key = _outbox_chain_sort_key(row)
        if partition not in best or key > best[partition][0]:
            best[partition] = (key, integrity)
    return {partition: integrity for partition, (_, integrity) in best.items()}


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
    now = utc_now().isoformat()  # one created_at for the whole batch (chain order)

    # Stage Bronze rows that are new (not already present under their id).
    staged_bronze: list[tuple[str, dict, tuple[str, str, str]]] = []
    new_rows: list[dict] = []
    persisted: set[tuple[str, str, str]] = set()
    for rec in unique:
        rid = _bronze_id(rec.tenant_id, rec.event_id, rec.schema_version)
        if rid in bronze_store:
            continue  # already durable (cross-request duplicate)
        row = _bronze_row(rec, now)
        staged_bronze.append((rid, row, rec.key))
        new_rows.append(row)
        persisted.add(rec.key)

    # Hash-chain the brand-new rows (scoped to new rows only) onto each tenant's
    # existing chain tail, inside this same commit unit. Mutates the row dicts in
    # place, so the staged rows carry their prev_hash/integrity_hash when stored.
    partitions = {_chain_partition(row) for row in new_rows}
    _chain_rows(new_rows, _memory_prior_tail(bronze_store, partitions))

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
        staged_outbox.append((oid, _outbox_row(ob, now)))

    # Hash-chain the brand-new outbox rows (LEDGER M4), scoped to new rows only
    # (already-present oids were skipped above), onto each tenant's existing outbox
    # chain tail — inside this same commit unit. Mutates the row dicts in place, so
    # the staged rows carry their prev_hash/integrity_hash when stored.
    new_outbox_rows = [row for _, row in staged_outbox]
    outbox_partitions = {_outbox_chain_partition(row) for row in new_outbox_rows}
    _chain_outbox_rows(
        new_outbox_rows, _memory_outbox_prior_tail(outbox_store, outbox_partitions)
    )

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
    source_tag, prev_hash, integrity_hash, created_at, updated_at
)
SELECT
    r.id, r.data, r.tenant_id, r.event_id, r.schema_version, r.batch_id,
    r.event_type, r.event_family, r.event_timestamp, r.received_at,
    r.session_id, r.anonymous_id, r.user_id, r.entity_id, r.payload,
    r.payload_bytes, r.payload_hash, r.source, r.source_tag,
    r.prev_hash, r.integrity_hash, now(), now()
FROM jsonb_to_recordset($1::jsonb) AS r(
    id text, data jsonb, tenant_id text, event_id text, schema_version text,
    batch_id text, event_type text, event_family text,
    event_timestamp timestamptz, received_at timestamptz,
    session_id text, anonymous_id text, user_id text, entity_id text,
    payload jsonb, payload_bytes integer, payload_hash text, source text,
    source_tag text, prev_hash text, integrity_hash text
)
-- Arbiter is the PRIMARY KEY id (a deterministic sha256 of
-- tenant_id|event_id|schema_version, so it is 1:1 with the composite unique
-- key). Under concurrent inserts of the same event, ON CONFLICT DO NOTHING
-- only suppresses a conflict detected on its arbiter index; with the composite
-- as the arbiter, a racing insert could still raise on the SEPARATE id PK
-- (bronze_sdk_events_pkey) before the composite arbiter resolved. Making the
-- PK the arbiter serializes the race on that one index — exactly-once holds.
ON CONFLICT (id) DO NOTHING
RETURNING tenant_id, event_id, schema_version
"""

# Which of this batch's (tenant_id, event_id, schema_version) keys already exist?
# Only genuinely-new rows join the chain (scoped to new rows only); existing rows
# keep the integrity_hash from their original insert.
_BRONZE_EXISTING_KEYS_SQL = """
SELECT b.tenant_id, b.event_id, b.schema_version
FROM bronze_sdk_events b
JOIN jsonb_to_recordset($1::jsonb) AS r(
    tenant_id text, event_id text, schema_version text
) ON b.tenant_id = r.tenant_id
   AND b.event_id = r.event_id
   AND b.schema_version = r.schema_version
"""

# Per-tenant chain tail: the integrity_hash of the last already-chained row,
# ordered by the same append key the writer chains on. NULL-hash (pre-cutover)
# rows are excluded so a tenant with only historical rows returns no tail.
_BRONZE_CHAIN_TAIL_SQL = """
SELECT DISTINCT ON (tenant_id) tenant_id, integrity_hash
FROM bronze_sdk_events
WHERE tenant_id = ANY($1::text[]) AND integrity_hash IS NOT NULL
ORDER BY tenant_id, created_at DESC, event_id DESC, schema_version DESC
"""

_OUTBOX_INSERT_SQL = """
INSERT INTO event_outbox (
    id, data, tenant_id, event_id, topic, partition_key, payload, status,
    attempt_count, available_at, prev_hash, integrity_hash, created_at, updated_at
)
SELECT
    r.id, r.data, r.tenant_id, r.event_id, r.topic, r.partition_key,
    r.payload, r.status, 0, r.available_at, r.prev_hash, r.integrity_hash,
    now(), now()
FROM jsonb_to_recordset($1::jsonb) AS r(
    id text, data jsonb, tenant_id text, event_id text, topic text,
    partition_key text, payload jsonb, status text, available_at timestamptz,
    prev_hash text, integrity_hash text
)
-- Arbiter is the PK id (deterministic sha256 of tenant_id|event_id|topic, 1:1
-- with the composite unique key) for the same concurrency reason as the Bronze
-- insert above: it serializes a racing duplicate on the one PK index rather
-- than risking a raise on the separate event_outbox PK.
ON CONFLICT (id) DO NOTHING
"""

# Which of this batch's (tenant_id, event_id, topic) keys already exist? Only
# genuinely-new outbox rows join the chain (scoped to new rows only); an existing
# row keeps the integrity_hash from its original insert.
_OUTBOX_EXISTING_KEYS_SQL = """
SELECT o.tenant_id, o.event_id, o.topic
FROM event_outbox o
JOIN jsonb_to_recordset($1::jsonb) AS r(
    tenant_id text, event_id text, topic text
) ON o.tenant_id = r.tenant_id
   AND o.event_id = r.event_id
   AND o.topic = r.topic
"""

# Per-tenant outbox chain tail: the integrity_hash of the last already-chained
# row, ordered by the same append key the writer chains on. NULL-hash
# (pre-cutover) rows are excluded so a tenant with only historical rows returns
# no tail.
_OUTBOX_CHAIN_TAIL_SQL = """
SELECT DISTINCT ON (tenant_id) tenant_id, integrity_hash
FROM event_outbox
WHERE tenant_id = ANY($1::text[]) AND integrity_hash IS NOT NULL
ORDER BY tenant_id, created_at DESC, event_id DESC, topic DESC
"""


async def _pg_commit(
    pool,
    unique: Sequence[BronzeSDKEvent],
    outbox_events: Sequence[OutboxEvent],
    orig_index: Sequence[int],
) -> set[tuple[str, str, str]]:
    """Persist Bronze + outbox in ONE asyncpg transaction; return persisted keys."""
    now = utc_now().isoformat()  # one created_at for the whole batch (chain order)
    rows_by_key = {rec.key: _bronze_row(rec, now) for rec in unique}
    keys_json = json.dumps(
        [
            {
                "tenant_id": rec.tenant_id,
                "event_id": rec.event_id,
                "schema_version": rec.schema_version,
            }
            for rec in unique
        ],
        default=str,
    )
    tenants = sorted({rec.tenant_id for rec in unique})

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Hash-chain only rows that don't already exist (scoped to new rows),
            # anchored to each tenant's current tail — all inside this txn so the
            # tail we read is consistent with the rows we're about to append.
            existing = {
                (r["tenant_id"], r["event_id"], r["schema_version"])
                for r in await conn.fetch(_BRONZE_EXISTING_KEYS_SQL, keys_json)
            }
            new_rows = [rows_by_key[rec.key] for rec in unique if rec.key not in existing]
            prior_tail = {
                r["tenant_id"]: r["integrity_hash"]
                for r in await conn.fetch(_BRONZE_CHAIN_TAIL_SQL, tenants)
            }
            _chain_rows(new_rows, prior_tail)

            bronze_json = json.dumps(
                [_as_bronze_record_param(rows_by_key[rec.key]) for rec in unique],
                default=str,
            )
            returned = await conn.fetch(_BRONZE_INSERT_SQL, bronze_json)
            persisted = {
                (r["tenant_id"], r["event_id"], r["schema_version"]) for r in returned
            }

            # Build outbox rows only for events whose Bronze row was inserted.
            outbox_rows: list[dict] = []
            for k, rec in zip(orig_index, unique):
                if rec.key not in persisted:
                    continue
                ob = outbox_events[k] if k < len(outbox_events) else None
                if ob is None:
                    continue
                outbox_rows.append(_outbox_row(ob, now))

            if outbox_rows:
                # Hash-chain only genuinely-new outbox rows (LEDGER M4), scoped by
                # the unique (tenant_id, event_id, topic) key, anchored to each
                # tenant's current outbox tail — inside this same txn so the tail we
                # read is consistent with the rows we're about to append. Every row
                # here already corresponds to a newly-inserted Bronze event, but the
                # existing-keys probe is kept (mirroring the Bronze path) so an
                # outbox row that somehow already exists is never re-chained.
                outbox_keys_json = json.dumps(
                    [
                        {
                            "tenant_id": r["tenant_id"],
                            "event_id": r["event_id"],
                            "topic": r["topic"],
                        }
                        for r in outbox_rows
                    ],
                    default=str,
                )
                existing_outbox = {
                    (r["tenant_id"], r["event_id"], r["topic"])
                    for r in await conn.fetch(_OUTBOX_EXISTING_KEYS_SQL, outbox_keys_json)
                }
                new_outbox_rows = [
                    r
                    for r in outbox_rows
                    if (r["tenant_id"], r["event_id"], r["topic"]) not in existing_outbox
                ]
                outbox_tenants = sorted({r["tenant_id"] for r in outbox_rows})
                outbox_prior_tail = {
                    r["tenant_id"]: r["integrity_hash"]
                    for r in await conn.fetch(_OUTBOX_CHAIN_TAIL_SQL, outbox_tenants)
                }
                _chain_outbox_rows(new_outbox_rows, outbox_prior_tail)

                await conn.execute(
                    _OUTBOX_INSERT_SQL,
                    json.dumps(
                        [_as_outbox_record_param(r) for r in outbox_rows], default=str
                    ),
                )

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
        "prev_hash": row.get("prev_hash"),
        "integrity_hash": row.get("integrity_hash"),
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
        "prev_hash": row.get("prev_hash"),
        "integrity_hash": row.get("integrity_hash"),
    }
