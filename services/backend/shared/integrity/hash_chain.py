"""Table-agnostic append-only hash-chain primitive.

Extracted from ``services/security/audit_ledger.py`` (``AuditLedger``), the
first (and, until this extraction, only) place Aether proves tamper-evidence
for a table via a per-partition SHA-256 hash chain. This module generalizes
that pattern so a second table (or a third) can reuse the exact same
integrity math instead of a fresh implementation being written each time.

This is a **pure primitive**: it has no knowledge of any specific table,
model, or repository. Every caller supplies:

  - "canonical fields to hash": a plain ``dict`` of the fields that make up
    the tamper-evident record for one row, already resolved by the caller
    (e.g. an audit event's sanitized metadata, or a Bronze event's envelope
    fields). ``compute_integrity_hash`` adds ``prev_hash`` and hashes the
    result deterministically (``json.dumps(..., sort_keys=True,
    default=str)``) so field ordering and non-JSON-native values (enums,
    UUIDs, etc.) never change the hash.
  - "chain partition key": the value each independent hash chain is scoped
    to (tenant for audit events; likely ``tenant_id`` again for a future
    Bronze table, per
    ``docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md``). Two rows with
    different partition keys never depend on each other's hashes, and
    ``verify_chain`` tracks one running "previous hash" per partition so a
    second partition's first row is never falsely compared against a first
    partition's tail.

``AuditLedger`` is the only caller today (a pure refactor — see
``services/security/audit_ledger.py``); wiring a second table into this
primitive is explicitly out of scope for this change
(``docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md``, Program 1, M2+).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Optional, Sequence, TypeVar

__all__ = ["compute_integrity_hash", "verify_chain", "ChainVerification"]

T = TypeVar("T")

# Shape returned by verify_chain(). A plain dict (not a dataclass/BaseModel) so
# callers can pass it straight through as an API response body, matching what
# AuditLedger.verify_chain() already returned before this extraction.
ChainVerification = dict[str, Any]


def compute_integrity_hash(canonical_fields: dict[str, Any], prev_hash: str = "") -> str:
    """Hash ``canonical_fields`` chained to ``prev_hash``.

    ``canonical_fields`` must already exclude ``prev_hash`` — this function
    adds it before hashing so every caller chains consistently and cannot
    accidentally omit it. Serialization is deterministic (``sort_keys=True``,
    ``default=str``), so the resulting hash depends only on the *values* of
    the supplied fields, never on dict insertion order or the exact Python
    type of a value (e.g. an ``Enum`` or ``datetime`` stringifies the same
    way every time via ``default=str``).
    """
    payload = dict(canonical_fields)
    payload["prev_hash"] = prev_hash
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def verify_chain(
    records: Sequence[T],
    *,
    partition_key: Callable[[T], str],
    sort_key: Callable[[T], Any],
    canonical_field_variants: Callable[[T], Sequence[dict[str, Any]]],
    stored_hash: Callable[[T], Optional[str]],
    record_id: Callable[[T], str],
) -> ChainVerification:
    """Re-walk ``records`` and confirm each partition's hash chain holds.

    Records are ordered by ``sort_key`` and grouped by ``partition_key``;
    each partition tracks its own independent running "previous hash", so
    verifying one partition never depends on another partition's rows or
    ordering.

    For each record, ``canonical_field_variants`` returns one or more
    acceptable canonical-field shapes to hash — a single-element sequence
    for a table with one stable hash shape, or multiple elements to tolerate
    a historical hash-shape widening without a backfill (the same
    "v1 vs v2" tolerance ``AuditLedger`` already relies on). The record's
    stored hash (``stored_hash``) is accepted if it matches *any* variant
    re-hashed against that partition's current running previous hash; the
    first variant is treated as canonical for chain-advancement purposes
    when a record has no stored hash at all (e.g. a defensively-tolerated
    malformed row).

    Returns::

        {
            "records_checked": int,
            "chains_verified": int,       # distinct partitions observed
            "chain_intact": bool,
            "broken_record_ids": list[str],
        }
    """
    ordered = sorted(records, key=sort_key)
    prev_by_partition: dict[str, str] = {}
    broken: list[str] = []
    for record in ordered:
        key = partition_key(record)
        prev = prev_by_partition.get(key, "")
        variants = canonical_field_variants(record)
        expected = [compute_integrity_hash(fields, prev) for fields in variants]
        actual = stored_hash(record)
        if actual not in expected:
            broken.append(record_id(record))
        # Advance the chain on the *actual* stored hash when present, so a
        # single tampered/missing hash is reported once rather than cascading
        # into every later record in the same partition being falsely
        # flagged as broken too. Fall back to the first (canonical) expected
        # variant only when no hash was stored at all.
        prev_by_partition[key] = actual or (expected[0] if expected else prev)
    return {
        "records_checked": len(ordered),
        "chains_verified": len(prev_by_partition),
        "chain_intact": not broken,
        "broken_record_ids": broken,
    }
