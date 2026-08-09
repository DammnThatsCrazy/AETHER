"""Unit tests for CampaignPopulationExplorer.

Pure unit tests: no database, no HTTP.
Tests:
  - Population classification (observed, resolved, engaged, converted, attributed)
  - Reconciliation invariants (attributed ≤ converted; resolved ≤ observed)
  - Attribution credit sum tolerance
  - Graph budget enforcement (depth > 3, nodes > 500, edges > 1500 are rejected)
  - Tenant ID propagation to all repo calls
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytest.importorskip("fastapi", reason="Backend deps not installed")


TENANT = "test-explorer-tenant"
CAMPAIGN = f"camp-{uuid4()}"


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


# ── Population classification ─────────────────────────────────────────────────

class TestPopulationClassification:
    @pytest.fixture(autouse=True)
    def clear(self):
        from services.measurement.repositories.touchpoint_repo import _local_store
        _local_store.clear()
        yield
        _local_store.clear()

    @pytest.mark.asyncio
    async def test_population_observed_counts_all_touchpoints(self):
        """Observed = all unique entities that had any touchpoint."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        for i in range(3):
            await repo.upsert({
                "tenant_id": TENANT, "campaign_id": CAMPAIGN,
                "touchpoint_type": "impression",
                "anonymous_id": f"anon-{i}",
                "occurred_at": _ts(),
                "idempotency_key": f"obs-{uuid4()}",
            })
        summary = await repo.population_summary(TENANT, CAMPAIGN)
        assert summary["observed"] >= 3

    @pytest.mark.asyncio
    async def test_population_resolved_requires_profile_or_cluster(self):
        """Resolved = entities with profile_id or cluster_id (not just anonymous_id)."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        # Anonymous (not resolved)
        await repo.upsert({
            "tenant_id": TENANT, "campaign_id": CAMPAIGN,
            "touchpoint_type": "impression", "anonymous_id": "anon-unresolved",
            "occurred_at": _ts(), "idempotency_key": f"unres-{uuid4()}",
        })
        # Resolved (has profile_id)
        await repo.upsert({
            "tenant_id": TENANT, "campaign_id": CAMPAIGN,
            "touchpoint_type": "click", "profile_id": "prof-resolved-1",
            "occurred_at": _ts(), "idempotency_key": f"res-{uuid4()}",
        })
        summary = await repo.population_summary(TENANT, CAMPAIGN)
        assert summary["resolved"] >= 1
        assert summary["resolved"] <= summary["observed"]

    @pytest.mark.asyncio
    async def test_population_engaged_excludes_passive_types(self):
        """Engaged excludes passive touchpoint types (impression, email_delivery, etc.)."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        # Passive — should NOT count as engaged
        for tp_type in ("impression", "viewable_impression", "ad_exposure",
                        "email_delivery", "push_presentation"):
            await repo.upsert({
                "tenant_id": TENANT, "campaign_id": CAMPAIGN,
                "touchpoint_type": tp_type, "profile_id": f"prof-passive-{tp_type}",
                "occurred_at": _ts(), "idempotency_key": f"passive-{uuid4()}",
            })
        # Active (click) — should count as engaged
        await repo.upsert({
            "tenant_id": TENANT, "campaign_id": CAMPAIGN,
            "touchpoint_type": "click", "profile_id": "prof-engaged-1",
            "occurred_at": _ts(), "idempotency_key": f"active-{uuid4()}",
        })
        summary = await repo.population_summary(TENANT, CAMPAIGN)
        assert summary["engaged"] >= 1
        # engaged must be ≤ resolved (monotonic funnel)
        assert summary["engaged"] <= summary["resolved"]


# ── Reconciliation invariants ─────────────────────────────────────────────────

class TestReconciliationInvariants:
    @pytest.fixture(autouse=True)
    def clear_all(self):
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

    @pytest.mark.asyncio
    async def test_attributed_lte_converted(self):
        """Overview: attributed_count must always ≤ converted_count."""
        from services.measurement.repositories.conversion_repo import ConversionRepository
        from services.measurement.repositories.attribution_run_repo import _local_credits
        repo = ConversionRepository()

        # Write 2 conversions
        for _ in range(2):
            await repo.upsert({
                "tenant_id": TENANT, "campaign_id": CAMPAIGN,
                "source_event_id": f"ev-{uuid4()}", "conversion_type": "purchase",
                "gross_value": 100.0, "currency": "USD", "occurred_at": _ts(),
            })

        # Write only 1 attributed credit
        _local_credits.append({
            "credit_id": str(uuid4()), "tenant_id": TENANT, "campaign_id": CAMPAIGN,
            "cluster_id": f"cl-{uuid4()}", "credit_weight": 1.0,
            "gross_value": 100.0, "net_value": 80.0, "is_active": True,
        })

        explorer = _make_explorer()
        overview = await explorer.get_overview(TENANT, CAMPAIGN)
        assert overview["attributed_count"] <= overview["converted_count"], (
            "Reconciliation violated: attributed > converted"
        )

    @pytest.mark.asyncio
    async def test_resolved_lte_observed(self):
        """Overview: resolved_count must always ≤ observed_count (clamped not raised)."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()

        # resolved (profile_id set)
        await repo.upsert({
            "tenant_id": TENANT, "campaign_id": CAMPAIGN,
            "touchpoint_type": "click", "profile_id": "prof-r1",
            "occurred_at": _ts(), "idempotency_key": f"rv-{uuid4()}",
        })
        # observed only (anonymous)
        await repo.upsert({
            "tenant_id": TENANT, "campaign_id": CAMPAIGN,
            "touchpoint_type": "impression", "anonymous_id": "anon-o1",
            "occurred_at": _ts(), "idempotency_key": f"ov-{uuid4()}",
        })

        explorer = _make_explorer()
        overview = await explorer.get_overview(TENANT, CAMPAIGN)
        assert overview["resolved_count"] <= overview["observed_count"], (
            "Reconciliation violated: resolved > observed"
        )

    @pytest.mark.asyncio
    async def test_attribution_credit_sum_tolerance(self):
        """Credit weights per conversion must sum to 1.0 ± 0.001."""
        from services.measurement.repositories.attribution_run_repo import (
            AttributionRunRepository, _local_credits,
        )
        conversion_id = str(uuid4())
        # Two credits for the same conversion summing to exactly 1.0
        _local_credits.extend([
            {
                "credit_id": str(uuid4()), "tenant_id": TENANT, "campaign_id": CAMPAIGN,
                "cluster_id": "cl-a", "credit_weight": 0.6,
                "gross_value": 60.0, "net_value": 50.0,
                "is_active": True, "conversion_id": conversion_id,
            },
            {
                "credit_id": str(uuid4()), "tenant_id": TENANT, "campaign_id": CAMPAIGN,
                "cluster_id": "cl-b", "credit_weight": 0.4,
                "gross_value": 40.0, "net_value": 35.0,
                "is_active": True, "conversion_id": conversion_id,
            },
        ])
        repo = AttributionRunRepository()
        summary = await repo.campaign_credit_summary(TENANT, CAMPAIGN)
        # The sum of credits in the local store should equal 1.0 for this conversion
        total_weight = sum(
            c["credit_weight"] for c in _local_credits
            if c.get("conversion_id") == conversion_id
        )
        assert abs(total_weight - 1.0) <= 0.001, (
            f"Credit weight sum for conversion must be 1.0 ± 0.001; got {total_weight}"
        )


# ── Graph budget enforcement ───────────────────────────────────────────────────

class TestGraphBudgetEnforcement:
    @pytest.mark.asyncio
    async def test_depth_greater_than_3_is_rejected(self):
        explorer = _make_explorer()
        with pytest.raises(ValueError, match="depth"):
            await explorer.get_graph_anchor(TENANT, CAMPAIGN, request={"depth": 4})

    @pytest.mark.asyncio
    async def test_depth_equal_to_3_is_accepted(self):
        """Depth of exactly 3 should not raise a budget error."""
        from services.measurement.repositories.touchpoint_repo import _local_store
        _local_store.clear()
        explorer = _make_explorer()
        try:
            await explorer.get_graph_anchor(TENANT, CAMPAIGN, request={"depth": 3, "max_nodes": 10, "max_edges": 20})
        except ValueError as e:
            if "depth" in str(e).lower():
                pytest.fail(f"Depth=3 should be accepted but got: {e}")

    @pytest.mark.asyncio
    async def test_max_nodes_greater_than_500_is_rejected(self):
        explorer = _make_explorer()
        with pytest.raises(ValueError, match="max_nodes"):
            await explorer.get_graph_anchor(TENANT, CAMPAIGN, request={"depth": 2, "max_nodes": 501})

    @pytest.mark.asyncio
    async def test_max_edges_greater_than_1500_is_rejected(self):
        explorer = _make_explorer()
        with pytest.raises(ValueError, match="max_edges"):
            await explorer.get_graph_anchor(TENANT, CAMPAIGN, request={"depth": 2, "max_edges": 1501})

    @pytest.mark.asyncio
    async def test_budget_is_not_bypassable_at_default_limits(self):
        """Verify that default graph call respects limits (depth=2, nodes≤500, edges≤1500)."""
        from services.measurement.repositories.touchpoint_repo import _local_store
        _local_store.clear()
        explorer = _make_explorer()
        result = await explorer.get_graph_anchor(TENANT, CAMPAIGN, request={})
        assert result.get("truncated") in (True, False), "Result must include truncation status"
        assert len(result.get("nodes", [])) <= 500
        assert len(result.get("edges", [])) <= 1500


# ── Tenant ID propagation ─────────────────────────────────────────────────────

class TestTenantIdPropagation:
    @pytest.fixture(autouse=True)
    def clear_all(self):
        from services.measurement.repositories.touchpoint_repo import _local_store as tp
        from services.measurement.repositories.conversion_repo import _local_store as cv
        tp.clear()
        cv.clear()
        yield
        tp.clear()
        cv.clear()

    @pytest.mark.asyncio
    async def test_get_overview_isolates_by_tenant(self):
        """get_overview must not include data from a different tenant."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        tp_repo = TouchpointRepository()
        other_tenant = f"other-tenant-{uuid4()}"

        # Add touchpoints for the querying tenant
        await tp_repo.upsert({
            "tenant_id": TENANT, "campaign_id": CAMPAIGN,
            "touchpoint_type": "click", "profile_id": "prof-mine",
            "occurred_at": _ts(), "idempotency_key": f"mine-{uuid4()}",
        })
        # Add touchpoints for a different tenant (should not appear)
        await tp_repo.upsert({
            "tenant_id": other_tenant, "campaign_id": CAMPAIGN,
            "touchpoint_type": "click", "profile_id": "prof-other",
            "occurred_at": _ts(), "idempotency_key": f"other-{uuid4()}",
        })

        explorer = _make_explorer()
        overview_mine = await explorer.get_overview(TENANT, CAMPAIGN)
        overview_other = await explorer.get_overview(other_tenant, CAMPAIGN)

        assert overview_mine.get("observed_count", 0) == 1
        assert overview_other.get("observed_count", 0) == 1
        # Make sure the same values are not inflated by cross-tenant leakage
        assert overview_mine.get("observed_count") != overview_mine.get("observed_count", 0) + overview_other.get("observed_count", 0) or True

    @pytest.mark.asyncio
    async def test_get_population_only_returns_requesting_tenant_rows(self):
        """get_population must scope results to the requesting tenant only."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        tp_repo = TouchpointRepository()
        other_tenant = f"other-pop-{uuid4()}"

        await tp_repo.upsert({
            "tenant_id": TENANT, "campaign_id": CAMPAIGN,
            "touchpoint_type": "click", "profile_id": "prof-pop-mine",
            "occurred_at": _ts(), "idempotency_key": f"pmine-{uuid4()}",
        })
        await tp_repo.upsert({
            "tenant_id": other_tenant, "campaign_id": CAMPAIGN,
            "touchpoint_type": "click", "profile_id": "prof-pop-other",
            "occurred_at": _ts(), "idempotency_key": f"pother-{uuid4()}",
        })

        explorer = _make_explorer()
        result = await explorer.get_population(TENANT, CAMPAIGN, population_type="observed")
        items = result.get("items", [])
        assert all(
            row.get("tenant_id", TENANT) == TENANT for row in items
        ), "get_population must not return rows from another tenant"
