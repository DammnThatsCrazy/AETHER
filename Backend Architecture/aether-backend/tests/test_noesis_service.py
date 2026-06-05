from __future__ import annotations

import pytest

from repositories.repos import BaseRepository, EntityRepository, reset_in_memory_stores
from services.noesis.models import NoesisQueryRequest, QueryPlan
from services.noesis.service import NoesisService
from shared.auth.auth import Role, TenantContext
from shared.cache.cache import CacheClient
from shared.common.common import ForbiddenError
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from repositories.repos import AnalyticsRepository


class StaticProvider:
    def __init__(self, plan: QueryPlan | None):
        self._plan = plan

    async def plan(self, request: NoesisQueryRequest, effective_tenant_id: str) -> QueryPlan | None:
        return self._plan


@pytest.fixture()
def tenant() -> TenantContext:
    return TenantContext(tenant_id="tenant-a", role=Role.VIEWER, permissions=["read"])


@pytest.fixture()
def operator() -> TenantContext:
    return TenantContext(tenant_id="kyber", role=Role.ADMIN, permissions=["read", "admin", "kyber:read"])


@pytest.fixture()
def service() -> NoesisService:
    reset_in_memory_stores()
    graph = GraphClient()
    return NoesisService(graph=graph, analytics=AnalyticsRepository(CacheClient()))


@pytest.mark.asyncio
async def test_entity_search_is_tenant_scoped(service: NoesisService, tenant: TenantContext):
    repo = EntityRepository()
    await repo.create_entity("entity-a", "tenant-a", "human", "Alice", None, {"risk_score": 0.8})
    await repo.create_entity("entity-b", "tenant-b", "human", "Bob", None, {"risk_score": 0.2})

    response = await service.query(NoesisQueryRequest(message="find Alice", surface="aether"), tenant)

    assert response.intent == "entity_search"
    assert response.results
    assert all(row["tenant_id"] == "tenant-a" for row in response.results)
    assert "entity-b" not in str(response.model_dump())
    assert response.query_debug is None


@pytest.mark.asyncio
async def test_aether_rejects_cross_tenant_request(service: NoesisService, tenant: TenantContext):
    with pytest.raises(ForbiddenError):
        await service.query(NoesisQueryRequest(message="show alerts", surface="aether", tenant_id="tenant-b"), tenant)


@pytest.mark.asyncio
async def test_alert_lookup_filters_unresolved(service: NoesisService, tenant: TenantContext):
    alerts = BaseRepository("alerts")
    await alerts.insert("alert-open", {"tenant_id": "tenant-a", "status": "open", "title": "SDK missing user_id"})
    await alerts.insert("alert-closed", {"tenant_id": "tenant-a", "status": "resolved", "title": "closed"})

    response = await service.query(NoesisQueryRequest(message="show unresolved alerts", surface="aether"), tenant)

    assert response.intent == "alert_lookup"
    assert len(response.results) == 1
    assert response.results[0]["id"] == "alert-open"


@pytest.mark.asyncio
async def test_kyber_operator_can_query_tenant_summary(service: NoesisService, operator: TenantContext):
    tenants = BaseRepository("tenants")
    await tenants.insert("tenant-a", {"tenant_id": "tenant-a", "name": "Tenant A"})

    response = await service.query(NoesisQueryRequest(message="summarize tenant status", surface="kyber", tenant_id="tenant-a"), operator)

    assert response.intent == "tenant_summary"
    assert response.query_debug is not None
    assert response.results[0]["tenant"]["name"] == "Tenant A"


@pytest.mark.asyncio
async def test_graph_lookup_hides_other_tenant_neighbors(service: NoesisService, tenant: TenantContext):
    await service.graph.upsert_vertex(Vertex(VertexType.USER, "user-a", {"tenant_id": "tenant-a", "display_name": "A"}))
    await service.graph.upsert_vertex(Vertex(VertexType.USER, "user-b", {"tenant_id": "tenant-b", "display_name": "B"}))
    await service.graph.add_edge(Edge(EdgeType.SIMILAR_TO, "user-a", "user-b", {"tenant_id": "tenant-b"}))

    response = await service.query(NoesisQueryRequest(message="what is connected to user user-a", surface="aether"), tenant)

    assert response.intent == "graph_lookup"
    assert response.graph.nodes == [{"id": "user-a", "type": "User", "label": "A", "properties": {"tenant_id": "tenant-a", "display_name": "A"}}]
    assert response.graph.edges == []


@pytest.mark.asyncio
async def test_llm_plan_fallback_is_validated(tenant: TenantContext):
    reset_in_memory_stores()
    service = NoesisService(
        graph=GraphClient(),
        analytics=AnalyticsRepository(CacheClient()),
        provider=StaticProvider(QueryPlan(intent="alert_lookup", tenant_id="tenant-a", source="llm", confidence=0.9)),
    )
    alerts = BaseRepository("alerts")
    await alerts.insert("alert-open", {"tenant_id": "tenant-a", "status": "open"})

    response = await service.query(NoesisQueryRequest(message="tell me something obscure", surface="aether"), tenant)

    assert response.mode == "llm_text_to_query"
    assert response.intent == "alert_lookup"
    assert response.results[0]["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_unsupported_intent_returns_refinement(service: NoesisService, tenant: TenantContext):
    response = await service.query(NoesisQueryRequest(message="write a poem", surface="aether"), tenant)

    assert response.mode == "fallback"
    assert response.error is not None
    assert response.error.code == "unsupported_intent"
    assert response.actions[0].type == "refine_query"


@pytest.mark.asyncio
async def test_query_records_conversation_history(service: NoesisService, tenant: TenantContext):
    repo = EntityRepository()
    await repo.create_entity("entity-a", "tenant-a", "human", "Alice", None, {})

    response = await service.query(
        NoesisQueryRequest(message="find Alice", surface="aether", conversation_id="conv-a"),
        tenant,
    )
    record = await service.conversations.get("conv-a", tenant_id="tenant-a", surface="aether")

    assert response.conversation_id == "conv-a"
    assert record["tenant_id"] == "tenant-a"
    assert [m["role"] for m in record["messages"]] == ["user", "assistant"]
    assert "query_debug" not in record["messages"][1]["response"]


@pytest.mark.asyncio
async def test_conversation_store_does_not_cross_tenants(service: NoesisService, tenant: TenantContext):
    await service.query(
        NoesisQueryRequest(message="show unresolved alerts", surface="aether", conversation_id="conv-private"),
        tenant,
    )

    with pytest.raises(Exception):
        await service.conversations.get("conv-private", tenant_id="tenant-b", surface="aether")


@pytest.mark.asyncio
async def test_streaming_query_emits_status_and_final_events(tenant: TenantContext):
    from types import SimpleNamespace

    from services.noesis.routes import _query_event_stream

    reset_in_memory_stores()
    request = SimpleNamespace(state=SimpleNamespace(tenant=tenant))
    graph = GraphClient()
    events = []
    async for event in _query_event_stream(
        NoesisQueryRequest(message="show unresolved alerts", surface="aether"),
        request,
        graph,
    ):
        events.append(event)

    assert any("event: status" in event for event in events)
    assert any("event: answer" in event for event in events)
    assert any("event: final" in event for event in events)


@pytest.mark.asyncio
async def test_conversation_export_and_delete_are_scoped(service: NoesisService, tenant: TenantContext):
    await service.query(
        NoesisQueryRequest(message="show unresolved alerts", surface="aether", conversation_id="conv-export"),
        tenant,
    )

    exported = await service.conversations.export_for_scope(surface="aether", tenant_id="tenant-a")
    assert exported["count"] == 1
    assert exported["conversations"][0]["conversation_id"] == "conv-export"
    assert "query_debug" not in exported["conversations"][0]["messages"][1]["response"]

    deleted = await service.conversations.delete("conv-export", tenant_id="tenant-a", surface="aether")
    assert deleted["deleted"] is True

    with pytest.raises(Exception):
        await service.conversations.get("conv-export", tenant_id="tenant-a", surface="aether")


@pytest.mark.asyncio
async def test_noesis_budget_rate_limits_repeated_calls(tenant: TenantContext):
    from types import SimpleNamespace

    from services.noesis import routes as noesis_routes
    from shared.common.common import RateLimitedError

    noesis_routes._RATE_BUCKETS.clear()
    request = SimpleNamespace(state=SimpleNamespace(tenant=tenant))
    noesis_routes._enforce_budget(request, bucket="unit", limit=1)
    with pytest.raises(RateLimitedError):
        noesis_routes._enforce_budget(request, bucket="unit", limit=1)


@pytest.mark.asyncio
async def test_noesis_route_audit_records_export_and_delete(tenant: TenantContext):
    from types import SimpleNamespace

    from services.noesis import routes as noesis_routes
    from services.security.repositories import SecurityAuditEventRepository

    reset_in_memory_stores()
    noesis_routes._RATE_BUCKETS.clear()
    request = SimpleNamespace(state=SimpleNamespace(tenant=tenant))
    await noesis_routes._conversations.record_turn(
        NoesisQueryRequest(message="show unresolved alerts", surface="aether", conversation_id="conv-route"),
        service_response := await NoesisService(GraphClient(), AnalyticsRepository(CacheClient())).query(
            NoesisQueryRequest(message="show unresolved alerts", surface="aether", conversation_id="conv-route-audit"),
            tenant,
        ),
        "tenant-a",
    )
    service_response.conversation_id = "conv-route"

    exported = await noesis_routes.export_noesis_conversations(request, surface="aether")
    deleted = await noesis_routes.delete_noesis_conversation("conv-route", request, surface="aether")
    audit_rows = await SecurityAuditEventRepository().find_many(filters={"tenant_id": "tenant-a"}, limit=20)

    assert exported["data"]["count"] >= 1
    assert deleted["data"]["deleted"] is True
    assert any(row["event_type"] == "noesis_conversation_export" for row in audit_rows)
    assert any(row["event_type"] == "noesis_conversation_delete" for row in audit_rows)
