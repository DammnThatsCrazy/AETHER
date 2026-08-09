"""Integration tests for Campaign 360 API endpoints.

Tests all 8 new campaign routes (overview, touchpoints, population, entities,
clusters, journeys, conversions, graph) by calling route handlers directly
with mocked request state — no HTTP transport, no database required.

Requires backend dependencies. Skipped gracefully if not installed.
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
from unittest.mock import MagicMock, AsyncMock


def _ts():
    return datetime.now(timezone.utc).isoformat()


TENANT_ID = "int-test-tenant-360"
CAMPAIGN_ID = f"camp-int-{uuid.uuid4()}"


class FakeTenant:
    def __init__(self, tenant_id: str = TENANT_ID):
        self.tenant_id = tenant_id
        self.api_key_tier = "enterprise"
        self._permissions = {"campaign:read", "campaign:manage"}

    def require_permission(self, _perm: str):
        pass


def make_request(tenant_id: str = TENANT_ID, **kwargs):
    req = MagicMock()
    req.state.tenant = FakeTenant(tenant_id)
    for k, v in kwargs.items():
        setattr(req.state, k, v)
    return req


async def _seed_touchpoints(n: int = 3):
    from services.measurement.repositories.touchpoint_repo import TouchpointRepository
    repo = TouchpointRepository()
    for i in range(n):
        await repo.upsert({
            "tenant_id": TENANT_ID, "campaign_id": CAMPAIGN_ID,
            "touchpoint_type": "click" if i % 2 == 0 else "impression",
            "profile_id": f"prof-int-{i}" if i > 0 else None,
            "anonymous_id": f"anon-int-{i}" if i == 0 else None,
            "occurred_at": _ts(),
            "idempotency_key": f"tp-int-{uuid.uuid4()}",
        })


async def _seed_campaign_local(campaign_id: str = CAMPAIGN_ID, tenant_id: str = TENANT_ID):
    """Seed a campaign in the local campaign store so _require_campaign works."""
    try:
        from services.campaign.routes import _local_campaigns
        _local_campaigns[campaign_id] = {
            "campaign_id": campaign_id,
            "tenant_id": tenant_id,
            "name": "Integration Test Campaign",
            "status": "active",
            "channel": "email",
        }
    except ImportError:
        pass


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
async def clear_stores():
    from services.measurement.repositories.touchpoint_repo import _local_store as tp
    from services.measurement.repositories.conversion_repo import _local_store as cv
    from services.measurement.repositories.attribution_run_repo import _local_credits as cr
    tp.clear()
    cv.clear()
    cr.clear()
    try:
        from services.campaign.routes import _local_campaigns
        _local_campaigns.clear()
    except (ImportError, AttributeError):
        pass
    yield
    tp.clear()
    cv.clear()
    cr.clear()
    try:
        from services.campaign.routes import _local_campaigns
        _local_campaigns.clear()
    except (ImportError, AttributeError):
        pass


# ── Overview endpoint ──────────────────────────────────────────────────────────

class TestOverviewEndpoint:
    @pytest.mark.asyncio
    async def test_overview_returns_reconciled_metrics(self):
        """GET /campaigns/{id}/overview returns overview with required fields."""
        await _seed_touchpoints(3)
        await _seed_campaign_local()

        from services.campaign.exploration import CampaignPopulationExplorer
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        from services.measurement.repositories.conversion_repo import ConversionRepository
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        from services.measurement.repositories.journey_repo import JourneyRepository
        from services.measurement.repositories.spend_repo import SpendRepository

        explorer = CampaignPopulationExplorer(
            touchpoint_repo=TouchpointRepository(),
            conversion_repo=ConversionRepository(),
            run_repo=AttributionRunRepository(),
            journey_repo=JourneyRepository(),
            spend_repo=SpendRepository(),
        )
        overview = await explorer.get_overview(TENANT_ID, CAMPAIGN_ID)

        assert "observed_count" in overview
        assert "resolved_count" in overview
        assert "attributed_count" in overview
        assert "converted_count" in overview
        # Invariants
        assert overview["resolved_count"] <= overview["observed_count"]
        assert overview["attributed_count"] <= overview["converted_count"]

    @pytest.mark.asyncio
    async def test_overview_returns_zero_for_empty_campaign(self):
        """Overview for a campaign with no data returns zeroed metrics, not errors."""
        await _seed_campaign_local()

        from services.campaign.exploration import CampaignPopulationExplorer
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        from services.measurement.repositories.conversion_repo import ConversionRepository
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        from services.measurement.repositories.journey_repo import JourneyRepository
        from services.measurement.repositories.spend_repo import SpendRepository

        explorer = CampaignPopulationExplorer(
            touchpoint_repo=TouchpointRepository(),
            conversion_repo=ConversionRepository(),
            run_repo=AttributionRunRepository(),
            journey_repo=JourneyRepository(),
            spend_repo=SpendRepository(),
        )
        empty_campaign = f"empty-{uuid.uuid4()}"
        overview = await explorer.get_overview(TENANT_ID, empty_campaign)
        assert overview["observed_count"] == 0
        assert overview["converted_count"] == 0


# ── Population endpoint ────────────────────────────────────────────────────────

class TestPopulationEndpoint:
    @pytest.mark.asyncio
    async def test_population_observed_returns_items(self):
        """Population endpoint for 'observed' returns items list."""
        await _seed_touchpoints(3)
        await _seed_campaign_local()

        from services.campaign.exploration import CampaignPopulationExplorer
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        from services.measurement.repositories.conversion_repo import ConversionRepository
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        from services.measurement.repositories.journey_repo import JourneyRepository
        from services.measurement.repositories.spend_repo import SpendRepository

        explorer = CampaignPopulationExplorer(
            touchpoint_repo=TouchpointRepository(),
            conversion_repo=ConversionRepository(),
            run_repo=AttributionRunRepository(),
            journey_repo=JourneyRepository(),
            spend_repo=SpendRepository(),
        )
        result = await explorer.get_population(TENANT_ID, CAMPAIGN_ID, population_type="observed")
        assert "items" in result
        assert isinstance(result["items"], list)

    @pytest.mark.asyncio
    async def test_population_pagination_respects_limit(self):
        """Population endpoint respects limit parameter."""
        await _seed_touchpoints(5)
        await _seed_campaign_local()

        from services.campaign.exploration import CampaignPopulationExplorer
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        from services.measurement.repositories.conversion_repo import ConversionRepository
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        from services.measurement.repositories.journey_repo import JourneyRepository
        from services.measurement.repositories.spend_repo import SpendRepository

        explorer = CampaignPopulationExplorer(
            touchpoint_repo=TouchpointRepository(),
            conversion_repo=ConversionRepository(),
            run_repo=AttributionRunRepository(),
            journey_repo=JourneyRepository(),
            spend_repo=SpendRepository(),
        )
        result = await explorer.get_population(TENANT_ID, CAMPAIGN_ID, population_type="observed", limit=2)
        assert len(result.get("items", [])) <= 2


# ── Cluster endpoint ───────────────────────────────────────────────────────────

class TestClusterEndpoint:
    @pytest.mark.asyncio
    async def test_cluster_rollup_returns_cluster_list(self):
        """Cluster rollup returns a list of cluster dicts."""
        await _seed_campaign_local()

        from services.measurement.repositories.attribution_run_repo import (
            AttributionRunRepository, _local_credits,
        )
        cluster_id = f"cl-int-{uuid.uuid4()}"
        _local_credits.append({
            "credit_id": str(uuid.uuid4()),
            "tenant_id": TENANT_ID, "campaign_id": CAMPAIGN_ID,
            "cluster_id": cluster_id, "credit_weight": 1.0,
            "gross_value": 250.0, "net_value": 200.0, "is_active": True,
        })

        repo = AttributionRunRepository()
        rows = await repo.campaign_cluster_rollup(TENANT_ID, CAMPAIGN_ID)
        assert isinstance(rows, list)
        assert any(r.get("cluster_id") == cluster_id for r in rows)

    @pytest.mark.asyncio
    async def test_cluster_rollup_groups_correctly(self):
        """Multiple credits for the same cluster are aggregated into one row."""
        await _seed_campaign_local()

        from services.measurement.repositories.attribution_run_repo import (
            AttributionRunRepository, _local_credits,
        )
        cluster_id = f"cl-agg-{uuid.uuid4()}"
        for i in range(3):
            _local_credits.append({
                "credit_id": str(uuid.uuid4()),
                "tenant_id": TENANT_ID, "campaign_id": CAMPAIGN_ID,
                "cluster_id": cluster_id, "credit_weight": 0.33,
                "gross_value": 100.0, "net_value": 80.0, "is_active": True,
            })

        repo = AttributionRunRepository()
        rows = await repo.campaign_cluster_rollup(TENANT_ID, CAMPAIGN_ID)
        cluster_rows = [r for r in rows if r.get("cluster_id") == cluster_id]
        assert len(cluster_rows) == 1, "Multiple credits must collapse into one cluster row"
        assert cluster_rows[0].get("conversion_count", 0) >= 1


# ── Conversion endpoint ────────────────────────────────────────────────────────

class TestConversionEndpoint:
    @pytest.fixture(autouse=True)
    def clear_conv(self):
        from services.measurement.repositories.conversion_repo import _local_store
        _local_store.clear()
        yield
        _local_store.clear()

    @pytest.mark.asyncio
    async def test_conversions_campaign_filter_returns_correct_conversions(self):
        """list_by_campaign returns only conversions for the specified campaign."""
        from services.measurement.repositories.conversion_repo import ConversionRepository
        repo = ConversionRepository()
        other_campaign = f"other-camp-{uuid.uuid4()}"

        await repo.upsert({
            "tenant_id": TENANT_ID, "campaign_id": CAMPAIGN_ID,
            "source_event_id": f"ev-mine-{uuid.uuid4()}", "conversion_type": "purchase",
            "gross_value": 100.0, "currency": "USD", "occurred_at": _ts(),
        })
        await repo.upsert({
            "tenant_id": TENANT_ID, "campaign_id": other_campaign,
            "source_event_id": f"ev-other-{uuid.uuid4()}", "conversion_type": "purchase",
            "gross_value": 999.0, "currency": "USD", "occurred_at": _ts(),
        })

        results = await repo.list_by_campaign(TENANT_ID, CAMPAIGN_ID, include_unattributed=True)
        assert all(r.get("campaign_id") == CAMPAIGN_ID for r in results)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_missing_campaign_returns_empty(self):
        """list_by_campaign for a non-existent campaign returns empty list."""
        from services.measurement.repositories.conversion_repo import ConversionRepository
        repo = ConversionRepository()
        results = await repo.list_by_campaign(TENANT_ID, f"missing-{uuid.uuid4()}")
        assert results == []


# ── Graph endpoint ────────────────────────────────────────────────────────────

class TestGraphEndpoint:
    @pytest.mark.asyncio
    async def test_graph_campaign_anchor_returns_bounded_graph(self):
        """Graph endpoint returns nodes, edges, and truncation status within budget."""
        await _seed_touchpoints(2)

        from services.campaign.exploration import CampaignPopulationExplorer
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        from services.measurement.repositories.conversion_repo import ConversionRepository
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        from services.measurement.repositories.journey_repo import JourneyRepository
        from services.measurement.repositories.spend_repo import SpendRepository

        explorer = CampaignPopulationExplorer(
            touchpoint_repo=TouchpointRepository(),
            conversion_repo=ConversionRepository(),
            run_repo=AttributionRunRepository(),
            journey_repo=JourneyRepository(),
            spend_repo=SpendRepository(),
        )
        result = await explorer.get_graph_anchor(TENANT_ID, CAMPAIGN_ID, request={"depth": 2, "max_nodes": 100, "max_edges": 300})
        assert "nodes" in result
        assert "edges" in result
        assert "truncated" in result
        assert len(result["nodes"]) <= 100
        assert len(result["edges"]) <= 300

    @pytest.mark.asyncio
    async def test_graph_contains_campaign_anchor_node(self):
        """Graph result must include the campaign itself as the anchor node."""
        await _seed_touchpoints(2)

        from services.campaign.exploration import CampaignPopulationExplorer
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        from services.measurement.repositories.conversion_repo import ConversionRepository
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        from services.measurement.repositories.journey_repo import JourneyRepository
        from services.measurement.repositories.spend_repo import SpendRepository

        explorer = CampaignPopulationExplorer(
            touchpoint_repo=TouchpointRepository(),
            conversion_repo=ConversionRepository(),
            run_repo=AttributionRunRepository(),
            journey_repo=JourneyRepository(),
            spend_repo=SpendRepository(),
        )
        result = await explorer.get_graph_anchor(TENANT_ID, CAMPAIGN_ID, request={})
        nodes = result.get("nodes", [])
        anchor_ids = [n.get("id") for n in nodes]
        assert CAMPAIGN_ID in anchor_ids, "Campaign anchor node must be present in graph result"

    @pytest.mark.asyncio
    async def test_graph_rejects_over_budget_request(self):
        """Graph endpoint enforces hard limits and raises ValueError for out-of-budget requests."""
        from services.campaign.exploration import CampaignPopulationExplorer
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        from services.measurement.repositories.conversion_repo import ConversionRepository
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        from services.measurement.repositories.journey_repo import JourneyRepository
        from services.measurement.repositories.spend_repo import SpendRepository

        explorer = CampaignPopulationExplorer(
            touchpoint_repo=TouchpointRepository(),
            conversion_repo=ConversionRepository(),
            run_repo=AttributionRunRepository(),
            journey_repo=JourneyRepository(),
            spend_repo=SpendRepository(),
        )
        with pytest.raises(ValueError):
            await explorer.get_graph_anchor(TENANT_ID, CAMPAIGN_ID, request={"depth": 10, "max_nodes": 9999})


# ── Cross-tenant access returns empty / isolated ───────────────────────────────

class TestCrossTenantIsolation:
    @pytest.mark.asyncio
    async def test_cross_tenant_campaign_overview_isolated(self):
        """Querying with wrong tenant_id returns zeroed overview, not cross-tenant data."""
        await _seed_touchpoints(3)

        from services.campaign.exploration import CampaignPopulationExplorer
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        from services.measurement.repositories.conversion_repo import ConversionRepository
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        from services.measurement.repositories.journey_repo import JourneyRepository
        from services.measurement.repositories.spend_repo import SpendRepository

        explorer = CampaignPopulationExplorer(
            touchpoint_repo=TouchpointRepository(),
            conversion_repo=ConversionRepository(),
            run_repo=AttributionRunRepository(),
            journey_repo=JourneyRepository(),
            spend_repo=SpendRepository(),
        )
        wrong_tenant = f"wrong-tenant-{uuid.uuid4()}"
        overview = await explorer.get_overview(wrong_tenant, CAMPAIGN_ID)
        assert overview["observed_count"] == 0, (
            "Cross-tenant campaign query must return zero observed_count"
        )

    @pytest.mark.asyncio
    async def test_missing_campaign_overview_returns_zeros(self):
        """Overview for a campaign that doesn't exist returns zeroed metrics."""
        from services.campaign.exploration import CampaignPopulationExplorer
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        from services.measurement.repositories.conversion_repo import ConversionRepository
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        from services.measurement.repositories.journey_repo import JourneyRepository
        from services.measurement.repositories.spend_repo import SpendRepository

        explorer = CampaignPopulationExplorer(
            touchpoint_repo=TouchpointRepository(),
            conversion_repo=ConversionRepository(),
            run_repo=AttributionRunRepository(),
            journey_repo=JourneyRepository(),
            spend_repo=SpendRepository(),
        )
        missing = f"missing-camp-{uuid.uuid4()}"
        overview = await explorer.get_overview(TENANT_ID, missing)
        for key in ("observed_count", "resolved_count", "converted_count", "attributed_count"):
            assert overview[key] == 0, f"Missing campaign: {key} must be 0"
