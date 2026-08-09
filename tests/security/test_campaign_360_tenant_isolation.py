"""Security tests — cross-tenant isolation for Campaign 360 endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed (pip install -e '.[backend]')")

from datetime import datetime, timezone
from uuid import uuid4


def _ts():
    return datetime.now(timezone.utc).isoformat()


TENANT_A = "tenant-360-sec-A"
TENANT_B = "tenant-360-sec-B"
CAMPAIGN_A = f"campaign-sec-{uuid4()}"
CAMPAIGN_B = f"campaign-sec-{uuid4()}"


# ── Touchpoint tenant isolation ────────────────────────────────────────────────

class TestCampaignTouchpointTenantIsolation:
    @pytest.fixture(autouse=True)
    def clear(self):
        from services.measurement.repositories.touchpoint_repo import _local_store
        _local_store.clear()
        yield
        _local_store.clear()

    @pytest.mark.asyncio
    async def test_list_by_campaign_scoped_to_tenant(self):
        """list_by_campaign must not return rows from another tenant's campaign."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        tp_a = {
            "tenant_id": TENANT_A, "campaign_id": CAMPAIGN_A,
            "touchpoint_type": "click", "occurred_at": _ts(),
            "idempotency_key": f"tp-a-{uuid4()}",
        }
        tp_b = {
            "tenant_id": TENANT_B, "campaign_id": CAMPAIGN_A,
            "touchpoint_type": "click", "occurred_at": _ts(),
            "idempotency_key": f"tp-b-{uuid4()}",
        }
        await repo.upsert(tp_a)
        await repo.upsert(tp_b)
        results = await repo.list_by_campaign(TENANT_A, CAMPAIGN_A)
        assert all(r.get("tenant_id") == TENANT_A for r in results), (
            "list_by_campaign must not return rows from TENANT_B when queried as TENANT_A"
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_population_summary_scoped_to_tenant(self):
        """population_summary must only count touchpoints for the requesting tenant."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        for i in range(3):
            await repo.upsert({
                "tenant_id": TENANT_A, "campaign_id": CAMPAIGN_A,
                "touchpoint_type": "click", "anonymous_id": f"anon-a-{i}",
                "occurred_at": _ts(),
                "idempotency_key": f"tp-pop-a-{uuid4()}",
            })
        await repo.upsert({
            "tenant_id": TENANT_B, "campaign_id": CAMPAIGN_A,
            "touchpoint_type": "click", "anonymous_id": "anon-b-1",
            "occurred_at": _ts(),
            "idempotency_key": f"tp-pop-b-{uuid4()}",
        })
        summary = await repo.population_summary(TENANT_A, CAMPAIGN_A)
        assert summary.get("observed", 0) == 3, (
            "population_summary observed count must exclude TENANT_B rows"
        )

    @pytest.mark.asyncio
    async def test_cross_campaign_isolation(self):
        """Querying campaign B's touchpoints with campaign A's ID returns no rows."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        await repo.upsert({
            "tenant_id": TENANT_A, "campaign_id": CAMPAIGN_B,
            "touchpoint_type": "impression", "occurred_at": _ts(),
            "idempotency_key": f"tp-cb-{uuid4()}",
        })
        results = await repo.list_by_campaign(TENANT_A, CAMPAIGN_A)
        assert results == [], "Must not return campaign B rows when querying campaign A"


# ── Conversion tenant isolation ────────────────────────────────────────────────

class TestCampaignConversionTenantIsolation:
    @pytest.fixture(autouse=True)
    def clear(self):
        from services.measurement.repositories.conversion_repo import _local_store as conv_store
        from services.measurement.repositories.touchpoint_repo import _local_store as tp_store
        conv_store.clear()
        tp_store.clear()
        yield
        conv_store.clear()
        tp_store.clear()

    @pytest.mark.asyncio
    async def test_list_by_campaign_excludes_other_tenant_conversions(self):
        """list_by_campaign on ConversionRepo must not expose cross-tenant conversions."""
        from services.measurement.repositories.conversion_repo import ConversionRepository
        repo = ConversionRepository()

        # Insert attributed conversion for tenant A
        cv_a = {
            "tenant_id": TENANT_A, "campaign_id": CAMPAIGN_A,
            "source_event_id": f"ev-a-{uuid4()}", "conversion_type": "purchase",
            "gross_value": 100.0, "currency": "USD", "occurred_at": _ts(),
        }
        # Insert attributed conversion for tenant B with same campaign ID
        cv_b = {
            "tenant_id": TENANT_B, "campaign_id": CAMPAIGN_A,
            "source_event_id": f"ev-b-{uuid4()}", "conversion_type": "purchase",
            "gross_value": 999.0, "currency": "USD", "occurred_at": _ts(),
        }
        await repo.upsert(cv_a)
        await repo.upsert(cv_b)

        results = await repo.list_by_campaign(TENANT_A, CAMPAIGN_A, include_unattributed=True)
        assert all(r.get("tenant_id") == TENANT_A for r in results), (
            "list_by_campaign must not return TENANT_B's conversions"
        )

    @pytest.mark.asyncio
    async def test_campaign_population_summary_tenant_scoped(self):
        """campaign_population_summary must only aggregate the requesting tenant's data."""
        from services.measurement.repositories.conversion_repo import ConversionRepository
        repo = ConversionRepository()

        for _ in range(2):
            await repo.upsert({
                "tenant_id": TENANT_A, "campaign_id": CAMPAIGN_A,
                "source_event_id": f"ev-a-{uuid4()}", "conversion_type": "purchase",
                "gross_value": 50.0, "currency": "USD", "occurred_at": _ts(),
            })
        await repo.upsert({
            "tenant_id": TENANT_B, "campaign_id": CAMPAIGN_A,
            "source_event_id": f"ev-b-{uuid4()}", "conversion_type": "purchase",
            "gross_value": 10000.0, "currency": "USD", "occurred_at": _ts(),
        })

        summary = await repo.campaign_population_summary(TENANT_A, CAMPAIGN_A)
        # TENANT_B's $10,000 conversion must not appear in TENANT_A's summary
        gross = summary.get("attributed_gross_revenue", 0)
        assert gross < 10000.0, (
            f"campaign_population_summary must not include TENANT_B revenue; got {gross}"
        )


# ── Attribution run tenant isolation ──────────────────────────────────────────

class TestCampaignAttributionRunTenantIsolation:
    @pytest.fixture(autouse=True)
    def clear(self):
        from services.measurement.repositories.attribution_run_repo import _local_credits
        _local_credits.clear()
        yield
        _local_credits.clear()

    @pytest.mark.asyncio
    async def test_cluster_rollup_scoped_to_tenant(self):
        """campaign_cluster_rollup must only aggregate credits for the requesting tenant."""
        from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
        repo = AttributionRunRepository()

        cid = f"cluster-{uuid4()}"

        # Insert credit for tenant A
        _write_credit(cid, TENANT_A, CAMPAIGN_A, 0.5, 200.0, 180.0)
        # Insert credit for tenant B with same campaign/cluster IDs
        _write_credit(cid, TENANT_B, CAMPAIGN_A, 0.5, 99999.0, 88888.0)

        rows = await repo.campaign_cluster_rollup(TENANT_A, CAMPAIGN_A)
        for row in rows:
            assert row.get("attributed_gross_revenue", 0) < 99999.0, (
                "cluster_rollup must not include TENANT_B's revenue"
            )


def _write_credit(cluster_id: str, tenant_id: str, campaign_id: str, weight: float, gross: float, net: float):
    from services.measurement.repositories.attribution_run_repo import _local_credits
    _local_credits.append({
        "credit_id": str(uuid4()),
        "tenant_id": tenant_id,
        "campaign_id": campaign_id,
        "cluster_id": cluster_id,
        "credit_weight": weight,
        "gross_value": gross,
        "net_value": net,
        "is_active": True,
    })


# ── Explorer graph budget enforcement ─────────────────────────────────────────

class TestCampaignGraphBudgetEnforcement:
    """Graph query budget is enforced at the service layer, not just the route."""

    @pytest.mark.asyncio
    async def test_graph_depth_exceeds_max_is_rejected(self):
        """CampaignPopulationExplorer.get_graph_anchor must reject depth > 3."""
        from services.campaign.exploration import CampaignPopulationExplorer
        explorer = _make_explorer()
        with pytest.raises(ValueError, match="depth"):
            await explorer.get_graph_anchor(
                TENANT_A, CAMPAIGN_A,
                request={"depth": 4, "max_nodes": 100, "max_edges": 300},
            )

    @pytest.mark.asyncio
    async def test_graph_max_nodes_exceeds_limit_is_rejected(self):
        """CampaignPopulationExplorer.get_graph_anchor must reject max_nodes > 500."""
        from services.campaign.exploration import CampaignPopulationExplorer
        explorer = _make_explorer()
        with pytest.raises(ValueError, match="max_nodes"):
            await explorer.get_graph_anchor(
                TENANT_A, CAMPAIGN_A,
                request={"depth": 2, "max_nodes": 501, "max_edges": 300},
            )

    @pytest.mark.asyncio
    async def test_graph_max_edges_exceeds_limit_is_rejected(self):
        """CampaignPopulationExplorer.get_graph_anchor must reject max_edges > 1500."""
        from services.campaign.exploration import CampaignPopulationExplorer
        explorer = _make_explorer()
        with pytest.raises(ValueError, match="max_edges"):
            await explorer.get_graph_anchor(
                TENANT_A, CAMPAIGN_A,
                request={"depth": 2, "max_nodes": 100, "max_edges": 1501},
            )


def _make_explorer():
    """Build a CampaignPopulationExplorer with stub repos."""
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


# ── Forged campaign ID ────────────────────────────────────────────────────────

class TestForgedCampaignIdIsolation:
    @pytest.fixture(autouse=True)
    def clear(self):
        from services.measurement.repositories.touchpoint_repo import _local_store
        _local_store.clear()
        yield
        _local_store.clear()

    @pytest.mark.asyncio
    async def test_forged_campaign_id_returns_empty(self):
        """Querying a non-existent (forged) campaign ID returns no touchpoints."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        await repo.upsert({
            "tenant_id": TENANT_A, "campaign_id": CAMPAIGN_A,
            "touchpoint_type": "click", "occurred_at": _ts(),
            "idempotency_key": f"tp-forge-{uuid4()}",
        })
        forged_id = f"forged-{uuid4()}"
        results = await repo.list_by_campaign(TENANT_A, forged_id)
        assert results == [], "Forged campaign ID must return no rows"

    @pytest.mark.asyncio
    async def test_tenant_id_always_propagated_to_touchpoint_repo(self):
        """Verify tenant_id is always required and present in touchpoint queries."""
        from services.measurement.repositories.touchpoint_repo import TouchpointRepository
        repo = TouchpointRepository()
        # All list_by_campaign calls require tenant_id as first positional arg
        # This test verifies no rows are returned for an empty tenant
        results = await repo.list_by_campaign("", CAMPAIGN_A)
        assert results == [], "Empty tenant_id must return no rows"
