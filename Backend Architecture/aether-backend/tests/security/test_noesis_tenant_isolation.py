"""Tenant isolation tests for Noesis (P4.2).

For each tested intent, seeds data for tenant A and tenant B, queries as
tenant A, and asserts zero tenant B records leak into the response.

Also verifies that plan.tenant_id is always overwritten to the scope's
effective_tenant_id, regardless of what the LLM provider returned.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.noesis.models import NoesisQueryRequest, QueryPlan
from services.noesis.service import NoesisService
from shared.auth.auth import TenantContext, Role
from shared.graph.graph import GraphClient


def _tenant(tenant_id: str, role: Role = Role.VIEWER) -> TenantContext:
    tc = MagicMock(spec=TenantContext)
    tc.tenant_id = tenant_id
    tc.role = role
    tc.permissions = ["read"]
    tc.has_permission = lambda p: p in ("read",)
    tc.require_permission = lambda p: None
    return tc


def _make_service(**kwargs) -> NoesisService:
    graph = MagicMock(spec=GraphClient)
    graph.get_vertex = AsyncMock(return_value=None)
    graph.get_neighbors = AsyncMock(return_value=[])
    graph.get_edges = AsyncMock(return_value=[])
    analytics = MagicMock()
    analytics.dashboard_summary = AsyncMock(return_value={})
    return NoesisService(graph=graph, analytics=analytics, **kwargs)


def _rows_for(tenant_id: str, count: int = 3) -> list[dict]:
    return [{"id": f"{tenant_id}-{i}", "tenant_id": tenant_id, "name": f"entity-{i}"} for i in range(count)]


@pytest.mark.asyncio
async def test_entity_search_isolates_tenants():
    service = _make_service()
    tenant_a_rows = _rows_for("tenant-A")
    tenant_b_rows = _rows_for("tenant-B")

    service.entities = MagicMock()
    service.entities.find_many = AsyncMock(side_effect=lambda filters=None, **kw: (
        tenant_a_rows if (filters or {}).get("tenant_id") == "tenant-A" else tenant_b_rows
    ))

    req = NoesisQueryRequest(message="show me entities", surface="aether")
    resp = await service.query(req, _tenant("tenant-A"))

    all_tenant_ids = {r.get("tenant_id") for r in resp.results if isinstance(r, dict)}
    assert "tenant-B" not in all_tenant_ids, f"Tenant B data leaked: {all_tenant_ids}"


@pytest.mark.asyncio
async def test_alert_lookup_isolates_tenants():
    service = _make_service()
    tenant_a_alerts = [{"id": "A-alert", "tenant_id": "tenant-A", "status": "open"}]
    tenant_b_alerts = [{"id": "B-alert", "tenant_id": "tenant-B", "status": "open"}]

    service.alerts = MagicMock()
    service.alerts.find_many = AsyncMock(side_effect=lambda filters=None, **kw: (
        tenant_a_alerts if (filters or {}).get("tenant_id") == "tenant-A" else tenant_b_alerts
    ))

    req = NoesisQueryRequest(message="show me open alerts", surface="aether")
    resp = await service.query(req, _tenant("tenant-A"))

    all_tenant_ids = {r.get("tenant_id") for r in resp.results if isinstance(r, dict)}
    assert "tenant-B" not in all_tenant_ids, f"Tenant B alerts leaked: {all_tenant_ids}"


@pytest.mark.asyncio
async def test_wallet_lookup_isolates_tenants():
    service = _make_service()
    tenant_a_wallets = [{"id": "w-A", "tenant_id": "tenant-A", "address": "0xAA"}]
    tenant_b_wallets = [{"id": "w-B", "tenant_id": "tenant-B", "address": "0xBB"}]

    service.wallets = MagicMock()
    service.wallets.find_many = AsyncMock(side_effect=lambda filters=None, **kw: (
        tenant_a_wallets if (filters or {}).get("tenant_id") == "tenant-A" else tenant_b_wallets
    ))

    req = NoesisQueryRequest(message="show wallets", surface="aether")
    resp = await service.query(req, _tenant("tenant-A"))

    all_tenant_ids = {r.get("tenant_id") for r in resp.results if isinstance(r, dict)}
    assert "tenant-B" not in all_tenant_ids, f"Tenant B wallets leaked: {all_tenant_ids}"


@pytest.mark.asyncio
async def test_plan_tenant_id_always_overwritten_to_scope():
    """When LLM returns a plan with tenant_id different from the caller's scope,
    _validate_plan must block the request with ForbiddenError — tenant data must not
    be accessible even if the LLM is compromised or adversarially prompted."""
    from shared.common.common import ForbiddenError

    evil_plan = QueryPlan(
        intent="entity_search",
        tenant_id="tenant-B",  # attacker tried to cross tenant
        confidence=0.9,
        source="llm",
    )

    mock_provider = MagicMock()
    mock_provider.plan = AsyncMock(return_value=evil_plan)
    mock_provider.provider_name = "test-evil"

    service = _make_service(provider=mock_provider)
    service.entities = MagicMock()
    service.entities.find_many = AsyncMock(return_value=[])

    req = NoesisQueryRequest(message="zzz entity lookup", surface="aether")
    with pytest.raises(ForbiddenError):
        await service.query(req, _tenant("tenant-A"))


@pytest.mark.asyncio
async def test_risk_cluster_lookup_isolates_tenants():
    service = _make_service()
    service.entities = MagicMock()
    service.entities.find_many = AsyncMock(side_effect=lambda filters=None, **kw: (
        [{"id": "r-A", "tenant_id": "tenant-A", "risk_score": 0.9}]
        if (filters or {}).get("tenant_id") == "tenant-A"
        else [{"id": "r-B", "tenant_id": "tenant-B", "risk_score": 0.95}]
    ))

    req = NoesisQueryRequest(message="show risky entities", surface="aether")
    resp = await service.query(req, _tenant("tenant-A"))

    all_tenant_ids = {r.get("tenant_id") for r in resp.results if isinstance(r, dict)}
    assert "tenant-B" not in all_tenant_ids, f"Tenant B risk data leaked: {all_tenant_ids}"


@pytest.mark.asyncio
async def test_campaign_reward_lookup_isolates_tenants():
    service = _make_service()
    service.campaigns = MagicMock()
    service.campaigns.find_many = AsyncMock(side_effect=lambda filters=None, **kw: (
        [{"id": "camp-A", "tenant_id": "tenant-A"}]
        if (filters or {}).get("tenant_id") == "tenant-A"
        else [{"id": "camp-B", "tenant_id": "tenant-B"}]
    ))
    service.rewards = MagicMock()
    service.rewards.find_many = AsyncMock(return_value=[])

    req = NoesisQueryRequest(message="list campaigns", surface="aether")
    resp = await service.query(req, _tenant("tenant-A"))

    all_tenant_ids = {r.get("tenant_id") for r in resp.results if isinstance(r, dict)}
    assert "tenant-B" not in all_tenant_ids, f"Tenant B campaigns leaked: {all_tenant_ids}"
