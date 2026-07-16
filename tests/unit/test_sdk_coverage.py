"""Unit tests for the tenant-level SDK dimension-coverage diagnostic.

In-memory (AETHER_ENV=local). Covers: an empty tenant yields a well-formed
zero result; a tenant whose entities have wallet/session data reflects it in
coverage; a dimension read raising for one entity degrades only that entity's
dimension to error without aborting the sweep; and the sample cap flags a
truncated sample.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

import pytest
from repositories.repos import reset_in_memory_stores

from services.profile.aggregator import Profile360Aggregator
from services.reconciliation.coverage import compute_tenant_coverage
from services.reconciliation.expectations import REGISTERED_DIMENSIONS


def setup_function() -> None:
    reset_in_memory_stores()


async def _make_entity(agg: Profile360Aggregator, eid: str, tid: str) -> None:
    await agg._entities.create_entity(eid, tid, "human", f"Name {eid}")


def _dim(result: dict, dimension: str) -> dict:
    return next(d for d in result["dimensions"] if d["dimension"] == dimension)


def _assert_partition(result: dict) -> None:
    """Every dimension's four buckets must sum to entities_sampled."""
    sampled = result["entities_sampled"]
    for d in result["dimensions"]:
        assert d["ready"] + d["stale"] + d["empty"] + d["error"] == sampled


@pytest.mark.asyncio
async def test_empty_tenant_is_wellformed_not_error():
    agg = Profile360Aggregator()
    result = await compute_tenant_coverage("tenant-empty", aggregator=agg)

    assert result["tenant_id"] == "tenant-empty"
    assert result["kind"] == "sdk_coverage"
    assert result["entities_sampled"] == 0
    assert result["sample_capped"] is False
    assert result["overall_coverage"] is None
    assert {d["dimension"] for d in result["dimensions"]} == set(REGISTERED_DIMENSIONS)
    for d in result["dimensions"]:
        assert d["ready"] == d["stale"] == d["empty"] == d["error"] == 0
        assert d["coverage_ratio"] is None
    assert result["population_size"] == 0
    assert result["methodology"] == "full_population_census"
    assert result["overall_value_state"] == "missing"
    assert "computed_at" in result


@pytest.mark.asyncio
async def test_entities_with_wallet_and_session_data_show_coverage():
    agg = Profile360Aggregator()
    tid = "tenant-cov"
    await _make_entity(agg, "e1", tid)
    await _make_entity(agg, "e2", tid)

    async def fake_wallets(entity_id, tenant_id):
        # count>=1, no watermark -> fresh -> "ready".
        return {"items": [{"id": f"{entity_id}-wallet"}]}

    async def fake_sessions(entity_id, tenant_id):
        return {"items": [{"id": f"{entity_id}-session"}]}

    agg.wallets = fake_wallets
    agg.sessions = fake_sessions

    result = await compute_tenant_coverage(tid, aggregator=agg)

    assert result["entities_sampled"] == 2
    assert result["sample_capped"] is False
    _assert_partition(result)

    wallets = _dim(result, "wallets")
    sessions = _dim(result, "sessions")
    assert wallets["ready"] == 2
    assert wallets["coverage_ratio"] == 1.0
    assert sessions["ready"] == 2
    assert sessions["coverage_ratio"] == 1.0

    # A dimension with no seeded data is empty, not ready.
    campaigns = _dim(result, "campaigns")
    assert campaigns["ready"] == 0
    assert campaigns["empty"] == 2
    assert campaigns["coverage_ratio"] == 0.0

    assert 0.0 < result["overall_coverage"] < 1.0


@pytest.mark.asyncio
async def test_dimension_error_for_one_entity_does_not_abort_sweep():
    agg = Profile360Aggregator()
    tid = "tenant-err"
    await _make_entity(agg, "e1", tid)
    await _make_entity(agg, "e2", tid)

    async def flaky_wallets(entity_id, tenant_id):
        if entity_id == "e1":
            raise RuntimeError("wallet backend exploded")
        return {"items": [{"id": f"{entity_id}-wallet"}]}

    agg.wallets = flaky_wallets

    result = await compute_tenant_coverage(tid, aggregator=agg)

    # Sweep completed over both entities despite the per-entity failure.
    assert result["entities_sampled"] == 2
    _assert_partition(result)

    wallets = _dim(result, "wallets")
    assert wallets["error"] == 1   # e1's wallet dimension degraded to error
    assert wallets["ready"] == 1   # e2 still counted honestly

    # Other dimensions for both entities are unaffected (empty, no data).
    assert _dim(result, "campaigns")["empty"] == 2


@pytest.mark.asyncio
async def test_sample_cap_flags_truncated_sample():
    agg = Profile360Aggregator()
    tid = "tenant-big"
    for i in range(5):
        await _make_entity(agg, f"e{i}", tid)

    result = await compute_tenant_coverage(tid, aggregator=agg, sample_limit=2)

    assert result["sample_capped"] is True
    assert result["population_size"] == 5
    assert result["entities_sampled"] == 2
    assert result["sample_limit"] == 2
    assert result["methodology"] == "deterministic_hash_sample"
    assert result["seed_version"] == "sdk-coverage-v1"
    assert _dim(result, "wallets")["confidence_interval"]["method"] == "wilson_score"
    _assert_partition(result)


@pytest.mark.asyncio
async def test_sample_cap_false_when_under_limit():
    agg = Profile360Aggregator()
    tid = "tenant-small"
    for i in range(3):
        await _make_entity(agg, f"e{i}", tid)

    result = await compute_tenant_coverage(tid, aggregator=agg, sample_limit=200)

    assert result["sample_capped"] is False
    assert result["population_size"] == 3
    assert result["entities_sampled"] == 3
    assert result["methodology"] == "full_population_census"


@pytest.mark.asyncio
async def test_hash_sample_is_reproducible_over_full_population():
    agg = Profile360Aggregator()
    tenant_id = "tenant-representative"
    for index in range(20):
        await _make_entity(agg, f"entity-{index:02d}", tenant_id)

    first = await agg._entities.sample_by_tenant(
        tenant_id, limit=5, seed_version="sdk-coverage-v1"
    )
    second = await agg._entities.sample_by_tenant(
        tenant_id, limit=5, seed_version="sdk-coverage-v1"
    )

    first_ids = [row["entity_id"] for row in first]
    assert first_ids == [row["entity_id"] for row in second]
    assert len(set(first_ids)) == 5
    assert set(first_ids) != {f"entity-{index:02d}" for index in range(5)}
