"""LEDGER M4 — append-only hash chain over ``event_outbox``.

Exercises the per-tenant tamper-evidence chain that ``ingest_many`` populates on
every NEW outbox row, run against the ``AETHER_ENV=local`` in-memory backend so
no Postgres is required. This mirrors the Bronze chain covered by
``test_bronze_hash_chain.py`` (LEDGER M2), extended to the transactional outbox.
Covers:

* new outbox rows get a populated ``integrity_hash``;
* ``prev_hash`` links consecutive rows (chain head is NULL);
* ``hash_chain.verify_chain`` over a tenant's outbox rows passes;
* a second ``ingest_many`` continues the chain from the prior batch's tail;
* pre-cutover NULL-hash rows are the documented boundary — a fresh chain starts,
  ingestion does not crash or chain onto un-hashed history;
* per-tenant chains are independent (tenant B never references tenant A);
* tampering with a hashed field is detected.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

from repositories.repos import (  # noqa: E402
    _IN_MEMORY_STORES,
    reset_in_memory_stores,
)
from shared.integrity import hash_chain  # noqa: E402
from services.ingestion.bronze_bulk import (  # noqa: E402
    BronzeSDKEvent,
    OutboxEvent,
    _outbox_canonical_fields,
    _outbox_chain_partition,
    _outbox_chain_sort_key,
    _outbox_id,
    ingest_many,
)

pytestmark = pytest.mark.asyncio

_TOPIC = "sdk.events.validated"


# ── fixtures / builders ──────────────────────────────────────────────────────

def _outbox_store() -> dict:
    return _IN_MEMORY_STORES.setdefault("event_outbox", {})


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def _event(
    tenant: str,
    event_id: str,
    *,
    schema_version: str = "2",
    event_type: str = "page",
    event_timestamp: str = "2026-08-08T00:00:00+00:00",
    payload: dict | None = None,
) -> BronzeSDKEvent:
    """A Bronze event — its acceptance is what causes an outbox row to be written."""
    return BronzeSDKEvent(
        tenant_id=tenant,
        event_id=event_id,
        schema_version=schema_version,
        batch_id="batch-1",
        event_type=event_type,
        event_family="web",
        event_timestamp=event_timestamp,
        received_at="2026-08-08T00:00:01+00:00",
        session_id="session-1",
        anonymous_id="anon-1",
        user_id=None,
        entity_id="anon-1",
        payload=payload if payload is not None else {"k": event_id},
    )


def _outbox(tenant: str, event_id: str, *, payload: dict | None = None) -> OutboxEvent:
    return OutboxEvent(
        tenant_id=tenant,
        event_id=event_id,
        topic=_TOPIC,
        partition_key=tenant,
        payload=payload if payload is not None else {"k": event_id},
    )


async def _ingest(tenant: str, event_ids: list[str]) -> None:
    recs = [_event(tenant, eid) for eid in event_ids]
    obs = [_outbox(tenant, eid) for eid in event_ids]
    result = await ingest_many(recs, obs)
    assert result.accepted_count == len(event_ids)
    # An outbox row is enqueued for every accepted event.
    assert result.outbox_written == len(event_ids)


def _tenant_outbox_rows(tenant: str) -> list[dict]:
    return [r for r in _outbox_store().values() if r.get("tenant_id") == tenant]


def _chained_outbox_rows(tenant: str) -> list[dict]:
    """A tenant's post-cutover outbox rows (those carrying an integrity_hash), in
    chain order. NULL-hash historical rows are the pre-cutover boundary and are
    not part of the verifiable chain."""
    rows = [r for r in _tenant_outbox_rows(tenant) if r.get("integrity_hash")]
    return sorted(rows, key=_outbox_chain_sort_key)


def _verify(tenant: str) -> dict:
    return hash_chain.verify_chain(
        _chained_outbox_rows(tenant),
        partition_key=_outbox_chain_partition,
        sort_key=_outbox_chain_sort_key,
        canonical_field_variants=lambda r: [_outbox_canonical_fields(r)],
        stored_hash=lambda r: r.get("integrity_hash"),
        record_id=lambda r: r["event_id"],
    )


# ── tests ────────────────────────────────────────────────────────────────────

async def test_new_outbox_rows_get_populated_integrity_hash_and_verify():
    reset_in_memory_stores()
    tenant = _tenant()

    await _ingest(tenant, ["e0", "e1", "e2"])

    rows = _chained_outbox_rows(tenant)
    assert len(rows) == 3
    # Every new outbox row carries a real (hex sha256) integrity_hash.
    assert all(r["integrity_hash"] for r in rows)
    assert all(len(r["integrity_hash"]) == 64 for r in rows)
    # The chain hashes the STABLE routing identity + content digest, so a
    # payload_hash is present on every chained row.
    assert all(r.get("payload_hash") for r in rows)

    verification = _verify(tenant)
    assert verification["chain_intact"] is True
    assert verification["records_checked"] == 3
    assert verification["chains_verified"] == 1
    assert verification["broken_record_ids"] == []


async def test_prev_hash_links_consecutive_outbox_rows():
    reset_in_memory_stores()
    tenant = _tenant()

    await _ingest(tenant, ["e0", "e1", "e2"])

    rows = _chained_outbox_rows(tenant)
    # Chain head has no predecessor → prev_hash is NULL.
    assert rows[0]["prev_hash"] is None
    # Each subsequent prev_hash back-links to the prior row's integrity_hash.
    for earlier, later in zip(rows, rows[1:]):
        assert later["prev_hash"] == earlier["integrity_hash"]


async def test_second_ingest_continues_outbox_chain_from_prior_batch():
    reset_in_memory_stores()
    tenant = _tenant()

    await _ingest(tenant, ["a1", "a2"])
    first_tail = max(_chained_outbox_rows(tenant), key=_outbox_chain_sort_key)[
        "integrity_hash"
    ]

    # A later batch appends to the tail rather than starting a new chain.
    await _ingest(tenant, ["b1"])

    rows = _chained_outbox_rows(tenant)
    assert len(rows) == 3
    # b1 sorts last (later created_at; also "b1" > "a2"); it chains onto the tail
    # integrity_hash of the previous batch.
    assert rows[-1]["event_id"] == "b1"
    assert rows[-1]["prev_hash"] == first_tail

    verification = _verify(tenant)
    assert verification["chain_intact"] is True
    assert verification["records_checked"] == 3
    assert verification["chains_verified"] == 1


async def test_pre_cutover_null_outbox_rows_are_boundary_not_crash():
    reset_in_memory_stores()
    tenant = _tenant()

    # Simulate a historical outbox row written before M4: hash columns are NULL.
    store = _outbox_store()
    hist_id = _outbox_id(tenant, "old", _TOPIC)
    store[hist_id] = {
        "id": hist_id,
        "tenant_id": tenant,
        "event_id": "old",
        "topic": _TOPIC,
        "partition_key": tenant,
        "payload": {"k": "old"},
        "payload_hash": "0" * 64,
        "status": "pending",
        "created_at": "2026-01-01T00:00:00+00:00",
        "prev_hash": None,
        "integrity_hash": None,
    }

    # Ingesting after the boundary must not crash and must start a FRESH chain.
    await _ingest(tenant, ["new1", "new2"])

    chained = _chained_outbox_rows(tenant)
    assert [r["event_id"] for r in chained] == ["new1", "new2"]
    # The first post-cutover row did NOT chain onto the un-hashed historical row.
    assert chained[0]["prev_hash"] is None
    assert chained[1]["prev_hash"] == chained[0]["integrity_hash"]

    # The historical row is untouched — still the NULL boundary marker.
    assert store[hist_id]["integrity_hash"] is None
    assert store[hist_id]["prev_hash"] is None

    # Verification over the post-cutover chain passes (boundary row excluded).
    assert _verify(tenant)["chain_intact"] is True


async def test_cross_tenant_outbox_chains_are_independent():
    reset_in_memory_stores()
    tenant_a = f"A-{uuid.uuid4().hex[:8]}"
    tenant_b = f"B-{uuid.uuid4().hex[:8]}"

    # Interleave two tenants inside ONE batch.
    recs = [
        _event(tenant_a, "a1"),
        _event(tenant_b, "b1"),
        _event(tenant_a, "a2"),
        _event(tenant_b, "b2"),
    ]
    obs = [
        _outbox(tenant_a, "a1"),
        _outbox(tenant_b, "b1"),
        _outbox(tenant_a, "a2"),
        _outbox(tenant_b, "b2"),
    ]
    result = await ingest_many(recs, obs)
    assert result.accepted_count == 4
    assert result.outbox_written == 4

    a_rows = _chained_outbox_rows(tenant_a)
    b_rows = _chained_outbox_rows(tenant_b)
    assert len(a_rows) == 2 and len(b_rows) == 2

    # Each tenant has its own chain head.
    assert a_rows[0]["prev_hash"] is None
    assert b_rows[0]["prev_hash"] is None

    # No hash from tenant A's chain appears anywhere in tenant B's back-links.
    a_hashes = {r["integrity_hash"] for r in a_rows}
    for r in b_rows:
        assert r["prev_hash"] not in a_hashes

    # Each tenant verifies as its own single, intact chain.
    for tenant in (tenant_a, tenant_b):
        verification = _verify(tenant)
        assert verification["chain_intact"] is True
        assert verification["chains_verified"] == 1
        assert verification["records_checked"] == 2


async def test_tampering_with_hashed_outbox_field_is_detected():
    reset_in_memory_stores()
    tenant = _tenant()

    await _ingest(tenant, ["e0", "e1", "e2"])

    # Tamper a hashed canonical field (the content digest) on the middle row.
    victim = next(r for r in _tenant_outbox_rows(tenant) if r["event_id"] == "e1")
    victim["payload_hash"] = "tampered" + "0" * 56

    verification = _verify(tenant)
    assert verification["chain_intact"] is False
    assert "e1" in verification["broken_record_ids"]
    # Only the tampered row is flagged — the break does not cascade.
    assert verification["broken_record_ids"] == ["e1"]
