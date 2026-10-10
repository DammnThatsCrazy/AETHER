"""Unit tests: scripts/gold_tenant_backfill.py — tenant-inclusive Gold rekey.

``GoldRepository.materialize()`` keys Gold rows by
``sha256(f"{tenant_id}:{metric_name}:{entity_id}:{entity_type}")[:24]``. Before
that fix, the formula omitted ``tenant_id`` entirely
(``sha256(f"{metric_name}:{entity_id}:{entity_type}")[:24]``), so two tenants
materializing the same ``(metric_name, entity_id, entity_type)`` collided on
one row and silently overwrote each other. ``scripts/gold_tenant_backfill.py``
finds rows still sitting under that old formula (or any key that no longer
matches what ``materialize()`` would compute for the row's own fields) and
moves them to the correct tenant-scoped key.

These tests seed the shared in-memory Gold store directly (bypassing
``materialize()`` for the legacy rows, since ``materialize()`` can no longer
produce a truly tenant-less key — that is exactly the bug it fixed) and drive
the script's core ``run_backfill()`` coroutine, never the CLI/argparse layer.
"""
from __future__ import annotations

import asyncio
import hashlib

import pytest

from repositories.lake import GoldRepository
from repositories.repos import reset_in_memory_stores

from scripts.gold_tenant_backfill import run_backfill


def _legacy_record_id(metric_name: str, entity_id: str, entity_type: str) -> str:
    """Mirrors the PRE-FIX Gold record_id formula (no tenant_id at all) that
    shipped before ``GoldRepository.materialize()`` started including
    ``tenant_id`` in the hash. Reproduced here ONLY to simulate historical,
    already-corrupted production data for this test — the backfill script
    itself never uses this formula; it only ever calls
    ``GoldRepository.compute_record_id`` (the current, tenant-inclusive one).
    """
    return hashlib.sha256(f"{metric_name}:{entity_id}:{entity_type}".encode()).hexdigest()[:24]


@pytest.mark.asyncio
async def test_dry_run_mutates_nothing_and_reports_correctly():
    reset_in_memory_stores()
    domain = "backfill_dry_run"
    gold = GoldRepository(domain=domain)

    legacy_id = _legacy_record_id("score", "wallet1", "wallet")
    await gold.insert(legacy_id, {
        "metric_name": "score", "entity_id": "wallet1", "entity_type": "wallet",
        "tenant_id": "tenant-a", "value": {"v": 1},
    })

    report = await run_backfill(domains=[domain], apply=False)

    assert report["mode"] == "dry_run"
    d = report["domains"][0]
    assert d["table"] == "gold_backfill_dry_run"
    assert d["scanned"] == 1
    assert d["rekeyed"] == 1  # would be rekeyed
    assert d["collisions"] == 0
    assert d["skipped"] == 0
    new_id = GoldRepository.compute_record_id("tenant-a", "score", "wallet1", "wallet")
    assert d["moved"] == [{
        "from": legacy_id, "to": new_id, "tenant_id": "tenant-a",
        "metric_name": "score", "entity_id": "wallet1", "entity_type": "wallet",
    }]

    # Nothing written: the legacy row is exactly where it was, byte for byte,
    # and nothing exists yet at the target key.
    still_there = await gold.find_by_id(legacy_id)
    assert still_there is not None
    assert still_there["value"] == {"v": 1}
    assert await gold.find_by_id(new_id) is None

    # Totals reflect the single domain scanned.
    assert report["totals"] == {
        "scanned": 1, "rekeyed": 1, "collisions": 0,
        "collision_rows_dropped": 0, "skipped": 0,
    }


@pytest.mark.asyncio
async def test_apply_rekeys_tenant_less_row_to_tenant_inclusive_id():
    """A single surviving legacy row (last writer tenant-b — the historical
    overwrite this whole fix is about) is moved cleanly to its tenant-scoped
    key. Whatever tenant-a may have originally written under this same
    tenant-less key pre-fix is already gone by the time this runs; the
    backfill cannot resurrect it (see the runbook's cross-tenant-corruption
    caveat) — it can only relocate what currently exists.
    """
    reset_in_memory_stores()
    domain = "backfill_apply_simple"
    gold = GoldRepository(domain=domain)

    legacy_id = _legacy_record_id("score", "wallet2", "wallet")
    await gold.insert(legacy_id, {
        "metric_name": "score", "entity_id": "wallet2", "entity_type": "wallet",
        "tenant_id": "tenant-b", "value": {"v": "survivor"},
    })

    report = await run_backfill(domains=[domain], apply=True)

    assert report["mode"] == "apply"
    d = report["domains"][0]
    assert d["scanned"] == 1
    assert d["rekeyed"] == 1
    assert d["collisions"] == 0
    assert d["collision_rows_dropped"] == 0

    new_id = GoldRepository.compute_record_id("tenant-b", "score", "wallet2", "wallet")
    assert await gold.find_by_id(legacy_id) is None  # old key gone — moved, not copied
    moved = await gold.find_by_id(new_id)
    assert moved is not None
    assert moved["value"] == {"v": "survivor"}
    assert moved["tenant_id"] == "tenant-b"
    assert moved["id"] == new_id

    # Idempotent: re-running is a clean no-op.
    report2 = await run_backfill(domains=[domain], apply=True)
    d2 = report2["domains"][0]
    assert d2["scanned"] == 1
    assert d2["rekeyed"] == 0
    assert d2["collisions"] == 0
    assert d2["skipped"] == 1
    assert d2["skipped_already_correct"] == 1
    still_moved = await gold.find_by_id(new_id)
    assert still_moved["value"] == {"v": "survivor"}  # unchanged by the second pass


@pytest.mark.asyncio
async def test_apply_collision_keeps_latest_updated_at_and_preserves_loser():
    """Two CURRENT rows claim the same tenant-scoped identity: a stale
    pre-fix leftover still sitting under the old tenant-less key, and a fresh
    row already correctly materialized (post-fix) under the new key for the
    same tenant/metric/entity/type. This is the 'old tenant-less key ...
    can't be perfectly disambiguated' collision the backfill must resolve
    without silently dropping data: latest updated_at wins, the loser is
    left exactly where it is (never deleted) and fully logged.
    """
    reset_in_memory_stores()
    domain = "backfill_collision"
    gold = GoldRepository(domain=domain)

    legacy_id = _legacy_record_id("risk", "wallet3", "wallet")
    await gold.insert(legacy_id, {
        "metric_name": "risk", "entity_id": "wallet3", "entity_type": "wallet",
        "tenant_id": "tenant-a", "value": {"v": "stale_pre_fix"},
    })
    # Guarantee a strictly later updated_at on the row materialized below —
    # utc_now() has ample resolution for this on its own, but a short sleep
    # removes any doubt rather than relying on it.
    await asyncio.sleep(0.05)
    await gold.materialize(
        metric_name="risk", entity_id="wallet3", entity_type="wallet",
        tenant_id="tenant-a", value={"v": "fresh_after_fix"},
    )
    new_id = GoldRepository.compute_record_id("tenant-a", "risk", "wallet3", "wallet")

    report = await run_backfill(domains=[domain], apply=True)

    d = report["domains"][0]
    assert d["scanned"] == 2
    assert d["collisions"] == 1
    assert d["collision_rows_dropped"] == 1
    assert d["rekeyed"] == 0  # winner was already correctly keyed; nothing moved
    assert d["skipped"] == 0
    assert d["moved"] == []

    # Winner (later updated_at) survives untouched at the canonical id.
    winner = await gold.find_by_id(new_id)
    assert winner is not None
    assert winner["value"] == {"v": "fresh_after_fix"}

    # Loser is left exactly where it was — never deleted.
    loser = await gold.find_by_id(legacy_id)
    assert loser is not None
    assert loser["value"] == {"v": "stale_pre_fix"}

    detail = d["collision_detail"]
    assert len(detail) == 1
    assert detail[0]["canonical_id"] == new_id
    assert detail[0]["winner"]["id"] == new_id
    assert detail[0]["winner"]["value"] == {"v": "fresh_after_fix"}
    assert [l["id"] for l in detail[0]["losers"]] == [legacy_id]
    assert detail[0]["losers"][0]["value"] == {"v": "stale_pre_fix"}
    assert detail[0]["losers"][0]["tenant_id"] == "tenant-a"

    # Idempotent: re-running reports the SAME collision again (the loser is
    # never silently resolved/forgotten) rather than pretending it's settled.
    report2 = await run_backfill(domains=[domain], apply=True)
    d2 = report2["domains"][0]
    assert d2["collisions"] == 1
    assert d2["collision_rows_dropped"] == 1
    assert await gold.find_by_id(legacy_id) is not None
    assert (await gold.find_by_id(new_id))["value"] == {"v": "fresh_after_fix"}


@pytest.mark.asyncio
async def test_dry_run_reports_collision_without_mutating_either_row():
    """Dry-run must classify a collision identically to --apply, but write
    nothing — neither the winner nor the loser moves.
    """
    reset_in_memory_stores()
    domain = "backfill_collision_dry_run"
    gold = GoldRepository(domain=domain)

    legacy_id = _legacy_record_id("risk", "wallet4", "wallet")
    await gold.insert(legacy_id, {
        "metric_name": "risk", "entity_id": "wallet4", "entity_type": "wallet",
        "tenant_id": "tenant-a", "value": {"v": "stale"},
    })
    await asyncio.sleep(0.05)
    await gold.materialize(
        metric_name="risk", entity_id="wallet4", entity_type="wallet",
        tenant_id="tenant-a", value={"v": "fresh"},
    )
    new_id = GoldRepository.compute_record_id("tenant-a", "risk", "wallet4", "wallet")

    report = await run_backfill(domains=[domain], apply=False)
    d = report["domains"][0]
    assert d["collisions"] == 1
    assert d["collision_rows_dropped"] == 1

    # Both rows are exactly where they started.
    assert (await gold.find_by_id(legacy_id))["value"] == {"v": "stale"}
    assert (await gold.find_by_id(new_id))["value"] == {"v": "fresh"}


@pytest.mark.asyncio
async def test_malformed_row_is_skipped_not_crashed_on():
    reset_in_memory_stores()
    domain = "backfill_malformed"
    gold = GoldRepository(domain=domain)
    await gold.insert("broken-row", {"tenant_id": "tenant-a", "value": {"v": 1}})  # no metric_name/entity_id/entity_type

    report = await run_backfill(domains=[domain], apply=True)
    d = report["domains"][0]
    assert d["scanned"] == 1
    assert d["skipped_malformed"] == 1
    assert d["rekeyed"] == 0
    assert d["collisions"] == 0
    # Untouched — the malformed row is still there under its original id.
    assert await gold.find_by_id("broken-row") is not None


@pytest.mark.asyncio
async def test_compute_record_id_matches_what_materialize_actually_persists():
    """Guards against the script's formula (via compute_record_id) ever
    drifting from what materialize() actually writes under — the backfill
    script imports and calls compute_record_id() directly rather than
    forking the hash, so this equality is the whole safety property.
    """
    reset_in_memory_stores()
    gold = GoldRepository(domain="backfill_formula_parity")
    row = await gold.materialize(
        metric_name="m", entity_id="e", entity_type="t", tenant_id="tenant-z", value=1,
    )
    assert row["id"] == GoldRepository.compute_record_id("tenant-z", "m", "e", "t")


@pytest.mark.asyncio
async def test_domain_scoping_never_touches_a_different_domain():
    reset_in_memory_stores()
    gold_a = GoldRepository(domain="backfill_scope_a")
    gold_b = GoldRepository(domain="backfill_scope_b")

    legacy_a = _legacy_record_id("score", "w", "wallet")
    legacy_b = _legacy_record_id("score", "w", "wallet")  # same legacy id, different table
    await gold_a.insert(legacy_a, {
        "metric_name": "score", "entity_id": "w", "entity_type": "wallet",
        "tenant_id": "tenant-a", "value": {"v": "a"},
    })
    await gold_b.insert(legacy_b, {
        "metric_name": "score", "entity_id": "w", "entity_type": "wallet",
        "tenant_id": "tenant-b", "value": {"v": "b"},
    })

    report = await run_backfill(domains=["backfill_scope_a"], apply=True)
    assert len(report["domains"]) == 1
    assert report["domains"][0]["table"] == "gold_backfill_scope_a"

    new_a = GoldRepository.compute_record_id("tenant-a", "score", "w", "wallet")
    assert (await gold_a.find_by_id(new_a))["value"] == {"v": "a"}
    # domain b was never targeted — its legacy row is untouched.
    assert await gold_b.find_by_id(legacy_b) is not None
    assert (await gold_b.find_by_id(legacy_b))["value"] == {"v": "b"}
