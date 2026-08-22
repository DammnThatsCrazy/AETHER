"""Unit tests for the table-agnostic hash-chain primitive.

`shared/integrity/hash_chain.py` was extracted from
`services/security/audit_ledger.py` (Program 1, M1 of
`docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md`). The `AuditLedger` test
suite (`tests/security/test_security_governance.py`) is the regression oracle
proving that extraction changed zero behavior; these tests instead exercise
the primitive directly and generically -- with a synthetic record shape, not
`SecurityAuditEvent` -- to prove it really is table-agnostic.
"""
from __future__ import annotations

import uuid

import pytest

from shared.integrity.hash_chain import compute_integrity_hash, verify_chain


def _make_chain(partition: str, n: int, *, start_seq: int = 0) -> list[dict]:
    """Build `n` sequentially-chained synthetic records for one partition,
    following the exact pattern a real caller (e.g. AuditLedger.record())
    follows: hash = compute_integrity_hash(fields, prev_tail); tail = hash.

    The ordering key (`seq`) is deliberately kept OUTSIDE the hashed `fields`
    -- mirroring how AuditLedger's `_chain_seq` is repository bookkeeping,
    not part of the tamper-evident payload.
    """
    records = []
    prev = ""
    for i in range(n):
        seq = start_seq + i
        fields = {"partition": partition, "payload": f"event-{partition}-{seq}"}
        h = compute_integrity_hash(fields, prev)
        records.append(
            {"id": f"{partition}-{seq}", "partition": partition, "seq": seq, "fields": fields, "hash": h}
        )
        prev = h
    return records


def _verify(records: list[dict]) -> dict:
    return verify_chain(
        records,
        partition_key=lambda r: r["partition"],
        sort_key=lambda r: (r["partition"], r["seq"]),
        canonical_field_variants=lambda r: [r["fields"]],
        stored_hash=lambda r: r["hash"],
        record_id=lambda r: r["id"],
    )


# ── compute_integrity_hash: determinism ─────────────────────────────────────

def test_hash_is_deterministic_for_same_fields_and_prev_hash():
    fields = {"a": 1, "b": "x"}
    assert compute_integrity_hash(fields, "prev123") == compute_integrity_hash(fields, "prev123")


def test_hash_is_independent_of_dict_key_insertion_order():
    a = {"a": 1, "b": "x", "c": [1, 2]}
    b = {"c": [1, 2], "a": 1, "b": "x"}
    assert compute_integrity_hash(a, "p") == compute_integrity_hash(b, "p")


def test_hash_changes_when_a_field_value_changes():
    base = {"a": 1, "b": "x"}
    tampered = {"a": 1, "b": "y"}
    assert compute_integrity_hash(base, "p") != compute_integrity_hash(tampered, "p")


def test_hash_changes_when_prev_hash_changes():
    fields = {"a": 1}
    assert compute_integrity_hash(fields, "p1") != compute_integrity_hash(fields, "p2")


def test_hash_tolerates_non_json_native_values_via_default_str():
    # UUIDs/enums/etc. are not natively JSON-serializable; compute_integrity_hash
    # must stringify them (default=str) rather than raise, and do so stably.
    fields = {"id": uuid.UUID(int=0)}
    assert compute_integrity_hash(fields, "") == compute_integrity_hash(fields, "")


def test_caller_supplied_fields_are_not_mutated():
    fields = {"a": 1}
    compute_integrity_hash(fields, "p")
    assert fields == {"a": 1}  # no "prev_hash" key leaked into the caller's dict


# ── chain linkage ────────────────────────────────────────────────────────────

def test_each_record_hash_depends_on_the_previous_hash():
    chain = _make_chain("t1", 3)
    assert len({chain[0]["hash"], chain[1]["hash"], chain[2]["hash"]}) == 3
    # Recomputing record 1's hash using record 0's hash as prev must match
    # exactly what was stored when the chain was built.
    recomputed = compute_integrity_hash(chain[1]["fields"], chain[0]["hash"])
    assert recomputed == chain[1]["hash"]


def test_identical_fields_in_different_chain_positions_hash_differently():
    # Same logical fields hashed against two different prev_hash tails must
    # not collide -- the chain position is part of what's proven.
    fields = {"payload": "same"}
    h_first = compute_integrity_hash(fields, "")
    h_second = compute_integrity_hash(fields, h_first)
    assert h_first != h_second


# ── verify_chain: happy path ─────────────────────────────────────────────────

def test_verify_chain_accepts_an_intact_chain():
    chain = _make_chain("t1", 5)
    result = _verify(chain)
    assert result["chain_intact"] is True
    assert result["records_checked"] == 5
    assert result["chains_verified"] == 1
    assert result["broken_record_ids"] == []


def test_verify_chain_on_empty_input():
    result = _verify([])
    assert result == {
        "records_checked": 0,
        "chains_verified": 0,
        "chain_intact": True,
        "broken_record_ids": [],
    }


# ── verify_chain: tamper / break / reorder detection ─────────────────────────

def test_verify_chain_detects_a_tampered_field_without_cascading():
    chain = _make_chain("t1", 3)
    chain[1]["fields"] = dict(chain[1]["fields"])
    chain[1]["fields"]["payload"] = "tampered"
    result = _verify(chain)
    assert result["chain_intact"] is False
    # Only the tampered record is flagged -- the chain re-anchors on record 1's
    # actual (untouched) stored hash, so record 2 still verifies correctly.
    assert result["broken_record_ids"] == [chain[1]["id"]]


def test_verify_chain_detects_a_deleted_record():
    chain = _make_chain("t1", 4)
    # Simulate deleting the row at seq=1: the next surviving record's stored
    # hash was chained against the now-missing row's hash, so it can no
    # longer be reproduced from the row that now precedes it.
    remaining = [chain[0], chain[2], chain[3]]
    result = _verify(remaining)
    assert result["chain_intact"] is False
    assert chain[2]["id"] in result["broken_record_ids"]


def test_verify_chain_detects_reordering():
    chain = _make_chain("t1", 3)
    # Swap the ordering key of the 2nd and 3rd records while leaving their
    # stored fields/hash untouched -- simulating rows being replayed out of
    # the order they were actually chained in.
    chain[1]["seq"], chain[2]["seq"] = chain[2]["seq"], chain[1]["seq"]
    result = _verify(chain)
    assert result["chain_intact"] is False
    assert set(result["broken_record_ids"]) & {chain[1]["id"], chain[2]["id"]}


def test_missing_stored_hash_is_flagged_without_cascading():
    chain = _make_chain("t1", 3)
    chain[0]["hash"] = None  # simulate a row persisted with no hash at all
    result = _verify(chain)
    assert result["chain_intact"] is False
    # Chain advancement falls back to the canonical expected hash when no
    # hash was stored, so the gap is reported once and does not cascade.
    assert result["broken_record_ids"] == [chain[0]["id"]]


# ── partition-key isolation ───────────────────────────────────────────────────

def test_partitions_are_verified_independently():
    t1 = _make_chain("t1", 3)
    t2 = _make_chain("t2", 3)
    result = _verify(t1 + t2)
    assert result["chain_intact"] is True
    assert result["chains_verified"] == 2
    assert result["records_checked"] == 6


def test_a_break_in_one_partition_does_not_flag_another_partition():
    t1 = _make_chain("t1", 3)
    t2 = _make_chain("t2", 3)
    t1[1]["fields"] = dict(t1[1]["fields"])
    t1[1]["fields"]["payload"] = "tampered"
    result = _verify(t1 + t2)
    assert result["chain_intact"] is False
    assert result["chains_verified"] == 2
    broken = set(result["broken_record_ids"])
    assert t1[1]["id"] in broken
    assert not (broken & {r["id"] for r in t2})


def test_a_second_partitions_first_record_is_not_compared_against_the_first_partitions_tail():
    # Regression for the exact bug class AuditLedger.verify_chain already
    # guards against (see test_global_chain_verifies_per_tenant): a global
    # walk across partitions must track one previous-hash per partition, not
    # a single global previous hash, or the second partition's first record
    # would be falsely flagged broken.
    t1 = _make_chain("t1", 2)
    t2 = _make_chain("t2", 2)
    # Interleave the two partitions in delivery order to prove ordering
    # across partitions doesn't matter, only sort_key + partition_key do.
    interleaved = [t1[0], t2[0], t1[1], t2[1]]
    result = _verify(interleaved)
    assert result["chain_intact"] is True
    assert result["broken_record_ids"] == []


# ── multi-variant tolerance (the "v1 vs v2" backcompat shape AuditLedger uses) ─

def test_canonical_field_variants_accepts_any_matching_shape():
    prev = ""
    legacy_shape = {"a": 1}
    legacy_hash = compute_integrity_hash(legacy_shape, prev)
    record = {"id": "r1", "partition": "t1", "seq": 0, "hash": legacy_hash, "legacy_fields": legacy_shape}
    result = verify_chain(
        [record],
        partition_key=lambda r: r["partition"],
        sort_key=lambda r: r["seq"],
        # Current/new shape listed first (canonical); legacy shape listed
        # second as the backcompat fallback -- exactly AuditLedger's v2-then-v1
        # ordering.
        canonical_field_variants=lambda r: [{"a": 1, "b": 2}, r["legacy_fields"]],
        stored_hash=lambda r: r["hash"],
        record_id=lambda r: r["id"],
    )
    assert result["chain_intact"] is True


def test_canonical_field_variants_still_detects_tampering_of_either_shape():
    prev = ""
    tampered_hash = compute_integrity_hash({"a": 999}, prev)  # matches neither shape
    record = {"id": "r1", "partition": "t1", "seq": 0, "hash": tampered_hash}
    result = verify_chain(
        [record],
        partition_key=lambda r: r["partition"],
        sort_key=lambda r: r["seq"],
        canonical_field_variants=lambda r: [{"a": 1, "b": 2}, {"a": 1}],
        stored_hash=lambda r: r["hash"],
        record_id=lambda r: r["id"],
    )
    assert result["chain_intact"] is False
    assert result["broken_record_ids"] == ["r1"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
