"""Economic write-path tests (agent 1E): the computed_results production writer
and the gold materializer's adoption of the canonical campaign computations.

Under test:

  * ``persist_computed_results`` is a durable, idempotent writer: the same
    canonical scope (same ``context_hash`` + definition) persisted twice records
    once and reports ``already_recorded`` on the replay — the crash-boundary
    guarantee (at-least-once, no duplication, no spurious conflict).
  * ``campaign_computation_context`` is deterministic: two constructions of the
    same window share a ``context_hash()``.
  * ``materialize_journey_economics`` consumes ``canonical_journey_allocated_cost``
    and ``canonical_campaign_metrics`` (not a local ROAS/CPA reimplementation):
    the gold row's ``ad_spend_usd`` is the ALLOCATED cost (conserved, never the
    full campaign spend), ROAS/CPA come from the canonical rate results, and the
    canonical results are persisted to ``computed_results``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from services.computation.campaign import (
    CampaignAggregates,
    canonical_campaign_metrics,
)
from services.computation.repositories import (
    ComputedResultsRepository,
    get_computation_repository,
)
from services.economic.computed_results import (
    campaign_computation_context,
    persist_computed_results,
)
from services.measurement import repositories as measurement_repos
from services.measurement.engine import gold_materializer
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.repositories.journey_repo import JourneyRepository
from services.measurement.repositories.spend_repo import SpendRepository
from shared.computation.context import ComputationContext
from shared.computation.result import CanonicalResult


@pytest.fixture(autouse=True)
async def _isolate():
    measurement_repos.spend_repo._local_store.clear()
    measurement_repos.attribution_run_repo._local_credits.clear()
    measurement_repos.attribution_run_repo._local_runs.clear()
    if gold_materializer._ch_client is not None:
        await gold_materializer._ch_client.close()
        gold_materializer._ch_client = None
    # Fresh ComputedResultsRepository singleton (the materializer uses it via the
    # module-level accessor) — no leakage across tests.
    import services.computation.repositories as comp_repos
    comp_repos._repo_singleton = None
    yield
    measurement_repos.spend_repo._local_store.clear()
    measurement_repos.attribution_run_repo._local_credits.clear()
    measurement_repos.attribution_run_repo._local_runs.clear()
    if gold_materializer._ch_client is not None:
        await gold_materializer._ch_client.close()
        gold_materializer._ch_client = None
    comp_repos._repo_singleton = None


def _ctx(tenant_id: str = "t-econ", subject_id: str = "j1") -> ComputationContext:
    return campaign_computation_context(
        tenant_id,
        subject_type="journey",
        subject_id=subject_id,
        event_time_start="2026-08-01T00:00:00+00:00",
        event_time_end="2026-08-02T00:00:00+00:00",
        native_currency="USD",
        journey_version="v1",
    )


def _metrics(tenant_id: str = "t-econ") -> dict[str, CanonicalResult]:
    agg = CampaignAggregates(
        impressions=1000,
        clicks=100,
        media_spend="50",
        total_cost="50",
        currency="USD",
        attributed_conversions="4",
        attributed_gross_revenue="200",
        attributed_net_revenue="200",
        first_party_conversions=0,
    )
    return canonical_campaign_metrics(_ctx(tenant_id), agg)


# ═══════════════════════════════════════════════════════════════════════════
# persist_computed_results — idempotent production writer
# ═══════════════════════════════════════════════════════════════════════════

async def test_persist_computed_results_records_once_replay_noops():
    repo = ComputedResultsRepository()
    metrics = _metrics()
    first = await persist_computed_results(metrics, tenant_id="t-econ", repo=repo, run_id="run-1")
    assert first["recorded"] == len(metrics)
    assert first["already_recorded"] == 0

    # Crash -> restart -> resume: the same scope persisted again is a no-op —
    # at-least-once without duplication and without a raised conflict.
    second = await persist_computed_results(metrics, tenant_id="t-econ", repo=repo, run_id="run-2")
    assert second["recorded"] == 0
    assert second["already_recorded"] == len(metrics)

    rows = await repo.list_for_tenant("t-econ", include_superseded=True)
    assert len(rows) == len(metrics)


async def test_persist_computed_results_rejects_wrong_tenant():
    repo = ComputedResultsRepository()
    with pytest.raises(ValueError):
        await persist_computed_results(_metrics(), tenant_id="someone-else", repo=repo)


async def test_persist_computed_results_requires_tenant():
    repo = ComputedResultsRepository()
    with pytest.raises(ValueError):
        await persist_computed_results(_metrics(), tenant_id="", repo=repo)


# ═══════════════════════════════════════════════════════════════════════════
# campaign_computation_context — deterministic scope identity
# ═══════════════════════════════════════════════════════════════════════════

def test_context_is_deterministic_across_instances():
    a = _ctx()
    b = _ctx()
    assert a.context_hash() == b.context_hash()


def test_context_differs_when_window_changes():
    a = campaign_computation_context(
        "t-econ", subject_type="journey", subject_id="j1",
        event_time_start="2026-08-01T00:00:00+00:00",
        event_time_end="2026-08-02T00:00:00+00:00",
    )
    b = campaign_computation_context(
        "t-econ", subject_type="journey", subject_id="j1",
        event_time_start="2026-08-03T00:00:00+00:00",
        event_time_end="2026-08-04T00:00:00+00:00",
    )
    assert a.context_hash() != b.context_hash()


# ═══════════════════════════════════════════════════════════════════════════
# materialize_journey_economics — consumes canonical metrics, persists results
# ═══════════════════════════════════════════════════════════════════════════


async def _fake_journey(self, tenant_id: str, journey_id: str):
    return {
        "profile_id": "p1",
        "campaign_ids": ["c1"],
        "conversion_ids": ["conv1"],
        "started_at": "2026-08-01T00:00:00+00:00",
        "ended_at": "2026-08-01T23:59:59+00:00",
        "journey_version": "v1",
    }


async def _fake_credits(self, tenant_id: str, conversion_id: str, *, active_only=True):
    return [{
        "campaign_id": "c1",
        "attributed_conversions": "3",
        "attributed_net_revenue": "1200",
    }]


async def _fake_summary(self, tenant_id: str, campaign_id: str, start_date=None, end_date=None):
    return {"total_attributed_conversions": "10"}


async def _fake_total_spend(self, tenant_id: str, campaign_id: str, *, period_start=None, period_end=None):
    return Decimal("1000")


async def test_journey_economics_uses_canonical_metrics_and_persists_results(monkeypatch):
    monkeypatch.setattr(JourneyRepository, "get_current", _fake_journey)
    monkeypatch.setattr(AttributionRunRepository, "list_credits_for_conversion", _fake_credits)
    monkeypatch.setattr(AttributionRunRepository, "campaign_credit_summary", _fake_summary)
    monkeypatch.setattr(SpendRepository, "total_spend", _fake_total_spend)

    rows = await gold_materializer.materialize_journey_economics("t-econ", "j1")
    assert rows == 1

    ch = await gold_materializer._ch()
    gold = ch.get_table("gold_journey_economics")
    assert gold and gold[0]["journey_id"] == "j1"
    # ad_spend is the ALLOCATED cost: 1000 × (3/10) = 300 — never the full 1000.
    assert gold[0]["ad_spend_usd"] == pytest.approx(300.0, abs=0.02)
    # ROAS = revenue / allocated spend = 1200/300 = 4.0 (canonical rate result).
    assert gold[0]["roas"] == pytest.approx(4.0, abs=0.01)
    # CPA = allocated spend / conversions = 300/3 = 100.
    assert gold[0]["cpa_usd"] == pytest.approx(100.0, abs=0.01)
    # AOV = revenue / attributed conversions = 1200/3 = 400.
    assert gold[0]["aov_usd"] == pytest.approx(400.0, abs=0.01)

    # The canonical results were persisted to computed_results.
    repo = get_computation_repository()
    rows = await repo.list_for_tenant("t-econ")
    ids = {r["definition_id"] for r in rows}
    assert "campaign.journey_allocated_cost" in ids
    assert "campaign.net_roas" in ids
    assert "campaign.cpa" in ids
    assert "campaign.aov" in ids


async def test_journey_economics_undefined_denominator_is_null_not_zero(monkeypatch):
    """A journey with zero allocated spend and no revenue yields NULL roas/cpa —
    the canonical honest status, never a fabricated 0.0."""

    async def _empty_journey(self, tenant_id, journey_id):
        return {
            "profile_id": "p1",
            "campaign_ids": [],
            "conversion_ids": [],
            "started_at": "2026-08-01T00:00:00+00:00",
            "ended_at": None,
            "journey_version": "v1",
        }

    monkeypatch.setattr(JourneyRepository, "get_current", _empty_journey)
    monkeypatch.setattr(AttributionRunRepository, "list_credits_for_conversion", _fake_credits)
    monkeypatch.setattr(AttributionRunRepository, "campaign_credit_summary", _fake_summary)
    monkeypatch.setattr(SpendRepository, "total_spend", _fake_total_spend)

    rows = await gold_materializer.materialize_journey_economics("t-econ", "j-empty")
    assert rows == 1
    ch = await gold_materializer._ch()
    gold = ch.get_table("gold_journey_economics")
    assert gold
    row = gold[0]
    assert row["ad_spend_usd"] == 0.0
    # Undefined denominators -> canonical missing_inputs -> NULL, never 0.0.
    assert row["roas"] is None
    assert row["cpa_usd"] is None
    assert row["aov_usd"] is None
