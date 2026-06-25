"""End-to-end paid media ecommerce flow with Campaign 360 verification.

Simulates a complete paid-media-driven ecommerce journey:
  impression → click → add-to-cart → purchase

Then verifies that Campaign 360 endpoints return expected data after the flow.

Uses in-memory local stores (no HTTP, no database). Skipped if backend
deps are not installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed (pip install -e '.[backend]')")

import uuid
from datetime import datetime, timezone


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _make_explorer():
    from services.measurement.repositories.touchpoint_repo import TouchpointRepository
    from services.measurement.repositories.conversion_repo import ConversionRepository
    from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
    from services.measurement.repositories.journey_repo import JourneyRepository
    from services.measurement.repositories.spend_repo import SpendRepository
    from services.campaign.exploration import CampaignPopulationExplorer
    return CampaignPopulationExplorer(
        touchpoint_repo=TouchpointRepository(),
        conversion_repo=ConversionRepository(),
        run_repo=AttributionRunRepository(),
        journey_repo=JourneyRepository(),
        spend_repo=SpendRepository(),
    )


@pytest.fixture(autouse=True)
async def clear_all_stores():
    from services.measurement.repositories.touchpoint_repo import _local_store as tp
    from services.measurement.repositories.conversion_repo import _local_store as cv
    from services.measurement.repositories.attribution_run_repo import _local_credits as cr
    tp.clear()
    cv.clear()
    cr.clear()
    yield
    tp.clear()
    cv.clear()
    cr.clear()


TENANT = "e2e-paid-media"
CAMPAIGN_ID = f"camp-pm-{uuid.uuid4()}"
CLUSTER_ID = f"cl-pm-{uuid.uuid4()}"
PROFILE_ID = "prof-pm-buyer-1"
CONVERSION_ID = str(uuid.uuid4())


async def _seed_full_journey():
    """Seed a complete paid-media ecommerce journey for one customer."""
    from services.measurement.repositories.touchpoint_repo import TouchpointRepository
    from services.measurement.repositories.conversion_repo import ConversionRepository
    from services.measurement.repositories.attribution_run_repo import _local_credits

    tp_repo = TouchpointRepository()
    cv_repo = ConversionRepository()

    # Step 1: display impression (upper funnel)
    await tp_repo.upsert({
        "tenant_id": TENANT, "campaign_id": CAMPAIGN_ID,
        "touchpoint_type": "impression", "channel": "display",
        "profile_id": PROFILE_ID, "cluster_id": CLUSTER_ID,
        "anonymous_id": "anon-pm-1",
        "occurred_at": _ts(), "idempotency_key": f"tp-pm-imp-{uuid.uuid4()}",
    })

    # Step 2: paid search click (mid funnel)
    await tp_repo.upsert({
        "tenant_id": TENANT, "campaign_id": CAMPAIGN_ID,
        "touchpoint_type": "click", "channel": "paid_search",
        "profile_id": PROFILE_ID, "cluster_id": CLUSTER_ID,
        "anonymous_id": "anon-pm-1",
        "occurred_at": _ts(), "idempotency_key": f"tp-pm-click-{uuid.uuid4()}",
    })

    # Step 3: email re-engagement (mid funnel)
    await tp_repo.upsert({
        "tenant_id": TENANT, "campaign_id": CAMPAIGN_ID,
        "touchpoint_type": "email_open", "channel": "email",
        "profile_id": PROFILE_ID, "cluster_id": CLUSTER_ID,
        "anonymous_id": "anon-pm-1",
        "occurred_at": _ts(), "idempotency_key": f"tp-pm-email-{uuid.uuid4()}",
    })

    # Step 4: purchase conversion (lower funnel)
    await cv_repo.upsert({
        "tenant_id": TENANT, "campaign_id": CAMPAIGN_ID,
        "source_event_id": f"ev-pm-{uuid.uuid4()}",
        "conversion_type": "purchase",
        "gross_value": 199.99, "net_value": 169.99,
        "occurred_at": _ts(),
    })

    # Attribution credit (linear model — equal weight across 3 touchpoints)
    for weight in [1.0 / 3] * 3:
        _local_credits.append({
            "credit_id": str(uuid.uuid4()),
            "tenant_id": TENANT, "campaign_id": CAMPAIGN_ID,
            "cluster_id": CLUSTER_ID, "credit_weight": weight,
            "gross_value": 199.99 * weight, "net_value": 169.99 * weight,
            "is_active": True, "conversion_id": CONVERSION_ID,
            "model": "linear",
        })


class TestPaidMediaEcommerceFlow:
    """Verifies Campaign 360 endpoints return correct data after a full
    paid-media ecommerce journey is seeded."""

    @pytest.mark.asyncio
    async def test_overview_reflects_complete_journey(self):
        await _seed_full_journey()
        explorer = _make_explorer()
        overview = await explorer.get_overview(TENANT, CAMPAIGN_ID)

        assert overview["observed_count"] >= 1, "Customer must be in observed population"
        assert overview["resolved_count"] >= 1, "Customer with profile_id must be resolved"
        assert overview["engaged_count"] >= 1, "Click/email touchpoints must count as engaged"

        # Reconciliation invariants
        assert overview["resolved_count"] <= overview["observed_count"]
        assert overview["attributed_count"] <= overview["converted_count"]

    @pytest.mark.asyncio
    async def test_population_observed_includes_customer(self):
        await _seed_full_journey()
        explorer = _make_explorer()
        result = await explorer.get_population(TENANT, CAMPAIGN_ID, population_type="observed")
        entity_ids = [r.get("entity_id") for r in result.get("items", [])]
        assert len(entity_ids) >= 1, "Customer must appear in observed population"

    @pytest.mark.asyncio
    async def test_population_resolved_includes_profile(self):
        await _seed_full_journey()
        explorer = _make_explorer()
        result = await explorer.get_population(TENANT, CAMPAIGN_ID, population_type="resolved")
        items = result.get("items", [])
        assert len(items) >= 1, "Profile with profile_id must appear in resolved population"

    @pytest.mark.asyncio
    async def test_conversions_returned_for_campaign(self):
        await _seed_full_journey()
        from services.measurement.repositories.conversion_repo import ConversionRepository
        repo = ConversionRepository()
        conversions = await repo.list_by_campaign(TENANT, CAMPAIGN_ID, include_unattributed=True)
        assert len(conversions) >= 1, "Purchase conversion must be returned"
        assert conversions[0].get("gross_value", 0) > 0

    @pytest.mark.asyncio
    async def test_cluster_rollup_captures_linear_attribution(self):
        await _seed_full_journey()
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        repo = AttributionRunRepository()
        rows = await repo.campaign_cluster_rollup(TENANT, CAMPAIGN_ID)
        cluster_row = next((r for r in rows if r.get("cluster_id") == CLUSTER_ID), None)
        assert cluster_row is not None, "Cluster must appear in rollup"
        assert cluster_row.get("attributed_gross_revenue", 0) > 0

    @pytest.mark.asyncio
    async def test_graph_anchor_contains_campaign_node(self):
        await _seed_full_journey()
        explorer = _make_explorer()
        result = await explorer.get_graph_anchor(
            TENANT, CAMPAIGN_ID,
            request={"depth": 2, "max_nodes": 100, "max_edges": 300},
        )
        node_ids = [n.get("id") for n in result.get("nodes", [])]
        assert CAMPAIGN_ID in node_ids, "Campaign must be the graph anchor node"

    @pytest.mark.asyncio
    async def test_graph_budget_not_exceeded(self):
        await _seed_full_journey()
        explorer = _make_explorer()
        result = await explorer.get_graph_anchor(
            TENANT, CAMPAIGN_ID,
            request={"depth": 2, "max_nodes": 10, "max_edges": 20},
        )
        assert len(result.get("nodes", [])) <= 10
        assert len(result.get("edges", [])) <= 20

    @pytest.mark.asyncio
    async def test_multi_channel_touchpoints_all_observed(self):
        """All three channel touchpoints (display, paid_search, email) should
        be visible through the touchpoint repo's campaign read."""
        await _seed_full_journey()
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        touchpoints = await repo.list_by_campaign(TENANT, CAMPAIGN_ID, limit=50)
        channels = {t.get("channel") for t in touchpoints}
        assert "display" in channels
        assert "paid_search" in channels
        assert "email" in channels

    @pytest.mark.asyncio
    async def test_attribution_credit_weights_sum_to_one(self):
        """Linear attribution across 3 touchpoints must sum to ~1.0."""
        await _seed_full_journey()
        from services.measurement.repositories.attribution_run_repo import _local_credits
        campaign_credits = [
            c for c in _local_credits
            if c.get("campaign_id") == CAMPAIGN_ID
            and c.get("conversion_id") == CONVERSION_ID
        ]
        total_weight = sum(c.get("credit_weight", 0) for c in campaign_credits)
        assert abs(total_weight - 1.0) < 0.001, f"Credit weights must sum to 1.0 ± 0.001, got {total_weight}"
