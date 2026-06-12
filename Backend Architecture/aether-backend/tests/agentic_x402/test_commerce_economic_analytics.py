"""Tests for CommerceEconomicAnalytics — revenue, cluster spend, treasury, facilitator perf."""

from __future__ import annotations

import pytest

from repositories.repos import (
    FacilitatorRepository,
    SettlementEventRepository,
    reset_in_memory_stores,
)
from services.commerce.economic_analytics import CommerceEconomicAnalytics


@pytest.fixture(autouse=True)
def isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


TENANT = "t-analytics"


def _views(settlements=None, facilitators=None) -> CommerceEconomicAnalytics:
    return CommerceEconomicAnalytics(
        settlements=settlements or SettlementEventRepository(),
        facilitators=facilitators or FacilitatorRepository(),
    )


# ── service_revenue ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_revenue_aggregates_settled():
    settlements = SettlementEventRepository()
    await settlements.record_event(
        settlement_event_id="se-r1", tenant_id=TENANT, intent_id="pi-1",
        agent_id="a1", status="settled", amount="10.00", currency="USDC",
        provider="inference-svc",
    )
    await settlements.record_event(
        settlement_event_id="se-r2", tenant_id=TENANT, intent_id="pi-2",
        agent_id="a1", status="access_granted", amount="5.00", currency="USDC",
        provider="inference-svc",
    )
    result = await _views(settlements).service_revenue("inference-svc", TENANT, "all")
    assert result["settled_count"] == 2
    from decimal import Decimal
    assert Decimal(result["revenue_by_currency"]["USDC"]) == Decimal("15.00")


@pytest.mark.asyncio
async def test_service_revenue_excludes_failed():
    settlements = SettlementEventRepository()
    await settlements.record_event(
        settlement_event_id="se-fail", tenant_id=TENANT, intent_id="pi-x",
        agent_id="a1", status="failed", amount="9.00", currency="USDC",
        provider="inference-svc",
    )
    result = await _views(settlements).service_revenue("inference-svc", TENANT, "all")
    assert result["settled_count"] == 0
    assert "USDC" not in result["revenue_by_currency"]


@pytest.mark.asyncio
async def test_service_revenue_excludes_other_providers():
    settlements = SettlementEventRepository()
    await settlements.record_event(
        settlement_event_id="se-other", tenant_id=TENANT, intent_id="pi-o",
        agent_id="a1", status="settled", amount="100.00", currency="USDC",
        provider="other-svc",
    )
    result = await _views(settlements).service_revenue("inference-svc", TENANT, "all")
    assert result["settled_count"] == 0


# ── cluster_spend ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cluster_spend_aggregates_by_cluster_id():
    settlements = SettlementEventRepository()
    await settlements.record_event(
        settlement_event_id="se-c1", tenant_id=TENANT, intent_id="pi-c1",
        agent_id="ag-1", status="settled", amount="3.00", currency="USDC",
        provider="prov", metadata={"cluster_id": "cluster-alpha"},
    )
    await settlements.record_event(
        settlement_event_id="se-c2", tenant_id=TENANT, intent_id="pi-c2",
        agent_id="ag-2", status="settled", amount="7.00", currency="USDC",
        provider="prov", metadata={"cluster_id": "cluster-alpha"},
    )
    result = await _views(settlements).cluster_spend("cluster-alpha", TENANT, "all")
    assert result["settled_count"] == 2
    assert result["unique_agents"] == 2
    from decimal import Decimal
    assert Decimal(result["spend_by_currency"]["USDC"]) == Decimal("10.00")


@pytest.mark.asyncio
async def test_cluster_spend_excludes_other_clusters():
    settlements = SettlementEventRepository()
    await settlements.record_event(
        settlement_event_id="se-other-cluster", tenant_id=TENANT, intent_id="pi-oc",
        agent_id="ag-x", status="settled", amount="50.00", currency="USDC",
        provider="prov", metadata={"cluster_id": "cluster-beta"},
    )
    result = await _views(settlements).cluster_spend("cluster-alpha", TENANT, "all")
    assert result["settled_count"] == 0


# ── treasury_balance ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_treasury_balance_returns_structure():
    result = await _views().treasury_balance(TENANT)
    assert "balance_usd" in result
    assert "runway_days" in result
    assert result["tenant_id"] == TENANT
    assert "computed_at" in result


@pytest.mark.asyncio
async def test_treasury_balance_runway_from_spend_rate():
    settlements = SettlementEventRepository()
    for i in range(30):
        await settlements.record_event(
            settlement_event_id=f"se-daily-{i}", tenant_id=TENANT, intent_id=f"pi-d{i}",
            agent_id="ag-1", status="settled", amount="1.00", currency="USDC",
            provider="prov",
        )
    result = await _views(settlements).treasury_balance(TENANT)
    # 30 events × $1 over 30d → daily rate = $1.00; balance_usd=0 → 0 days runway
    assert result["spend_last_30d_usd"] == pytest.approx(30.0, rel=0.01)
    # balance is 0 (no treasury seeded) and rate > 0 → runway = 0 days
    assert result["runway_days"] == 0


# ── facilitator_performance ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_facilitator_performance_counts_and_rates():
    settlements = SettlementEventRepository()
    for i in range(3):
        await settlements.record_event(
            settlement_event_id=f"se-fac-ok-{i}", tenant_id=TENANT, intent_id=f"pi-fok{i}",
            agent_id="ag-1", status="settled", amount="2.00", currency="USDC",
            provider="prov", facilitator_id="fac-alpha",
        )
    await settlements.record_event(
        settlement_event_id="se-fac-fail", tenant_id=TENANT, intent_id="pi-ff",
        agent_id="ag-1", status="failed", amount="2.00", currency="USDC",
        provider="prov", facilitator_id="fac-alpha",
    )
    result = await _views(settlements).facilitator_performance(TENANT, "all")
    assert len(result["facilitators"]) == 1
    fac = result["facilitators"][0]
    assert fac["facilitator_id"] == "fac-alpha"
    assert fac["transaction_count"] == 4
    assert fac["settled_count"] == 3
    assert fac["failed_count"] == 1
    assert fac["success_rate"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_facilitator_performance_sorted_by_volume():
    settlements = SettlementEventRepository()
    await settlements.record_event(
        settlement_event_id="se-big", tenant_id=TENANT, intent_id="pi-big",
        agent_id="ag-1", status="settled", amount="100.00", currency="USDC",
        provider="prov", facilitator_id="fac-big",
    )
    await settlements.record_event(
        settlement_event_id="se-small", tenant_id=TENANT, intent_id="pi-small",
        agent_id="ag-1", status="settled", amount="1.00", currency="USDC",
        provider="prov", facilitator_id="fac-small",
    )
    result = await _views(settlements).facilitator_performance(TENANT, "all")
    assert result["facilitators"][0]["facilitator_id"] == "fac-big"
