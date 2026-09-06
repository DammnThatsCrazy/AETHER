"""Typed valuation repositories — DB-free in-memory runs (lane C3-W3).

Covers the persistence primitives: idempotent observation append on the
content-hash observation_id, snapshot immutability carve-out (mark_superseded
flips status/back-pointer without touching the economic fact), tenant isolation
on reads, and the current-state policy repo upsert. Typed repos fall back to
shared in-memory stores when no DB pool is configured (AETHER_ENV=local).
"""
from __future__ import annotations

import pytest

from repositories.typed_repo import reset_typed_in_memory_stores
from services.valuation.models import MarketPriceObservation
from services.valuation.price_providers import (
    PROVIDER_REPORTED,
    make_observation,
    seconds_before,
)
from services.valuation.repositories import (
    TenantValuePolicyRepo,
    ValuationPriceObservationRepo,
    ValuationSnapshotRepo,
)

EFFECTIVE = "2026-09-02T12:00:00+00:00"
USD = "fiat:USD"
ETH = "crypto:ETH"


@pytest.fixture(autouse=True)
def _clean_typed_stores():
    reset_typed_in_memory_stores()
    yield
    reset_typed_in_memory_stores()


def _obs_record(*, observed_at=None) -> dict:
    at = observed_at or seconds_before(EFFECTIVE, 60)
    obs = make_observation(
        asset_id=ETH, quote_asset_id=USD, price="100.00",
        provider=PROVIDER_REPORTED, observed_at=at, source="provider:eth",
    )
    record = obs.model_dump(exclude_none=True)
    record.pop("data", None)
    return record


def _snapshot_record(
    tenant_id: str = "tenant_a",
    *,
    valuation_id: str = "val_snapshot1",
    idempotency_key: str = "key1",
    reporting_amount="200.00",
    status: str = "current",
) -> dict:
    return {
        "valuation_id": valuation_id,
        "tenant_id": tenant_id,
        "idempotency_key": idempotency_key,
        "canonical_asset_id": ETH,
        "deployment_id": None,
        "economic_role": "payment",
        "native_amount": "2.00",
        "native_currency": "ETH",
        "reporting_asset_id": USD,
        "reporting_amount": reporting_amount,
        "valuation_basis": "event_time",
        "price_status": "normal",
        "valuation_method": "provider_reported",
        "provider": PROVIDER_REPORTED,
        "conversion_refs": [],
        "evidence": None,
        "registry_version": "reg-1",
        "policy_version": None,
        "price_observation_ids": ["obs_1"],
        "supersedes_snapshot_id": None,
        "superseded_by_snapshot_id": None,
        "status": status,
        "computed_at": EFFECTIVE,
        "effective_at": EFFECTIVE,
        "execution_by_aether": False,
    }


# ── valuation_price_observations ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observation_repo_insert_is_idempotent_on_content_hash():
    repo = ValuationPriceObservationRepo()
    record = _obs_record()
    assert await repo.insert(record) is True
    # Identical observation (same deterministic observation_id) is a no-op.
    assert await repo.insert(record) is False
    rows = await repo.find_many()
    assert len(rows) == 1
    assert rows[0]["observation_id"] == record["observation_id"]


@pytest.mark.asyncio
async def test_observation_repo_distinct_instants_append_separate_rows():
    repo = ValuationPriceObservationRepo()
    first = _obs_record(observed_at=seconds_before(EFFECTIVE, 3600))
    second = _obs_record(observed_at=seconds_before(EFFECTIVE, 60))
    assert await repo.insert(first) is True
    assert await repo.insert(second) is True
    rows = await repo.find_many({}, order_by="observed_at", descending=True)
    assert len(rows) == 2
    assert rows[0]["observed_at"] == second["observed_at"]


@pytest.mark.asyncio
async def test_observation_repo_lookup_candidates_orders_desc():
    repo = ValuationPriceObservationRepo()
    old = _obs_record(observed_at=seconds_before(EFFECTIVE, 7200))
    recent = _obs_record(observed_at=seconds_before(EFFECTIVE, 60))
    await repo.insert(old)
    await repo.insert(recent)
    rows = await repo.lookup_candidates(ETH, PROVIDER_REPORTED)
    assert [r["observation_id"] for r in rows] == [
        recent["observation_id"], old["observation_id"],
    ]


# ── valuation_snapshots ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_repo_insert_conflicts_on_tenant_idempotency():
    repo = ValuationSnapshotRepo()
    record = _snapshot_record()
    assert await repo.insert(record) is True
    assert await repo.insert(record) is False
    assert len(await repo.find_many({"tenant_id": "tenant_a"})) == 1


@pytest.mark.asyncio
async def test_snapshot_repo_tenant_isolation_on_reads():
    repo = ValuationSnapshotRepo()
    await repo.insert(_snapshot_record("tenant_a", valuation_id="val_a", idempotency_key="ka"))
    await repo.insert(_snapshot_record("tenant_b", valuation_id="val_b", idempotency_key="kb"))
    a_rows = await repo.find_many({"tenant_id": "tenant_a"})
    b_rows = await repo.find_many({"tenant_id": "tenant_b"})
    assert len(a_rows) == 1 and a_rows[0]["valuation_id"] == "val_a"
    assert len(b_rows) == 1 and b_rows[0]["valuation_id"] == "val_b"
    assert await repo.find_one({"tenant_id": "tenant_a", "valuation_id": "val_b"}) is None


@pytest.mark.asyncio
async def test_mark_superseded_only_touches_backpointer_and_status():
    repo = ValuationSnapshotRepo()
    await repo.insert(_snapshot_record(valuation_id="val_old", idempotency_key="k1"))
    await repo.insert(_snapshot_record(valuation_id="val_new", idempotency_key="k2"))
    assert await repo.mark_superseded("tenant_a", "val_old", "val_new") is True
    old = await repo.find_one({"tenant_id": "tenant_a", "valuation_id": "val_old"})
    # Economic fact columns are untouched.
    assert old["status"] == "superseded"
    assert old["superseded_by_snapshot_id"] == "val_new"
    assert old["reporting_amount"] == "200.00"
    assert old["price_status"] == "normal"
    new = await repo.find_one({"tenant_id": "tenant_a", "valuation_id": "val_new"})
    assert new["status"] == "current"


@pytest.mark.asyncio
async def test_mark_superseded_rejects_self_supersede():
    repo = ValuationSnapshotRepo()
    await repo.insert(_snapshot_record(valuation_id="val_old", idempotency_key="k1"))
    with pytest.raises(ValueError):
        await repo.mark_superseded("tenant_a", "val_old", "val_old")


@pytest.mark.asyncio
async def test_mark_superseded_unknown_target_raises():
    repo = ValuationSnapshotRepo()
    with pytest.raises(ValueError, match="not found"):
        await repo.mark_superseded("tenant_a", "does-not-exist", "val_new")


@pytest.mark.asyncio
async def test_mark_superseded_already_superseded_raises():
    repo = ValuationSnapshotRepo()
    await repo.insert(_snapshot_record(valuation_id="val_old", idempotency_key="k1"))
    await repo.insert(_snapshot_record(valuation_id="val_new", idempotency_key="k2"))
    await repo.insert(_snapshot_record(valuation_id="val_newer", idempotency_key="k3"))
    assert await repo.mark_superseded("tenant_a", "val_old", "val_new") is True
    # A row can be superseded exactly once — a second supersede is refused.
    with pytest.raises(ValueError, match="not current"):
        await repo.mark_superseded("tenant_a", "val_old", "val_newer")


@pytest.mark.asyncio
async def test_snapshot_repo_refuses_generic_update_outside_carve_out():
    repo = ValuationSnapshotRepo()
    await repo.insert(_snapshot_record(valuation_id="val_old", idempotency_key="k1"))
    with pytest.raises(ValueError, match="immutable"):
        await repo.update_by_key(
            {"tenant_id": "tenant_a", "valuation_id": "val_old"},
            {"reporting_amount": "9999"},
        )
    # The carve-out itself is permitted (supersede back-pointer).
    assert await repo.update_by_key(
        {"tenant_id": "tenant_a", "valuation_id": "val_old"},
        {"status": "superseded", "superseded_by_snapshot_id": "val_new"},
    ) is True


@pytest.mark.asyncio
async def test_observation_repo_refuses_update_by_key():
    repo = ValuationPriceObservationRepo()
    await repo.insert(_obs_record())
    with pytest.raises(ValueError, match="append-only"):
        await repo.update_by_key(
            {"observation_id": "obs_1"},
            {"price": "9999"},
        )


@pytest.mark.asyncio
async def test_find_current_for_asset_filters_superseded_out():
    repo = ValuationSnapshotRepo()
    await repo.insert(_snapshot_record(valuation_id="val_current", idempotency_key="k1"))
    await repo.insert(_snapshot_record(valuation_id="val_old", idempotency_key="k2", status="superseded"))
    current = await repo.find_current_for_asset("tenant_a", ETH)
    assert [r["valuation_id"] for r in current] == ["val_current"]


# ── tenant_value_policies ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_policy_repo_insert_then_update_by_key():
    repo = TenantValuePolicyRepo()
    record = {
        "tenant_id": "tenant_a",
        "policy_version": "1",
        "reporting_asset_id": USD,
        "allowed_reporting_asset_ids": [USD],
        "provider_chain_policy": "default",
        "stale_threshold_seconds": None,
        "fallback_allowed": False,
    }
    assert await repo.insert(record) is True
    assert await repo.update_by_key(
        {"tenant_id": "tenant_a"},
        {"policy_version": "2", "fallback_allowed": True},
    ) is True
    row = await repo.find_one({"tenant_id": "tenant_a"})
    assert row["policy_version"] == "2"
    assert row["fallback_allowed"] is True
    assert row["allowed_reporting_asset_ids"] == [USD]


@pytest.mark.asyncio
async def test_policy_repo_reinsert_is_idempotent_noop():
    repo = TenantValuePolicyRepo()
    record = {
        "tenant_id": "tenant_a",
        "policy_version": "1",
        "reporting_asset_id": USD,
        "allowed_reporting_asset_ids": [USD],
        "provider_chain_policy": "default",
        "stale_threshold_seconds": None,
        "fallback_allowed": False,
    }
    assert await repo.insert(record) is True
    assert await repo.insert(record) is False
