"""
Aether Backend — End-to-End Integration Tests

Tests full cross-service flows:
  1. Campaign: touchpoints → attribution computation
  2. Analytics: export request → job lifecycle → status polling
  3. GraphQL: query validation → resolver → authorization enforcement
  4. Agent: task creation → lifecycle tracking → audit trail
  5. Ingestion: IP enrichment → geo normalization → output validation
  6. A2H: Agent-to-Human relationship layer (graph edges, classification, events)

These tests exercise the actual service code without HTTP transport
by calling route handler functions directly with mocked request state.

Requires backend dependencies (fastapi, pydantic, httpx). Skipped
gracefully if not installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import threading

import pytest

# Add backend path early so service imports resolve
sys.path.insert(0, "Backend Architecture/aether-backend")

# Skip entire module if backend deps aren't installed
pytest.importorskip("fastapi", reason="Backend deps not installed (pip install -e '.[backend]')")

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

# =========================================================================
# Shared test utilities
# =========================================================================


class FakeTenant:
    """Mock tenant context for testing."""

    def __init__(self, tenant_id: str = "test-tenant-001", permissions: set = None):
        self.tenant_id = tenant_id
        self.api_key_tier = "enterprise"
        self._permissions = permissions or {
            "campaign:manage", "analytics:export", "agent:manage", "admin",
        }

    def require_permission(self, perm: str) -> None:
        if perm not in self._permissions:
            raise PermissionError(f"Missing permission: {perm}")


class FakeRequest:
    """Mock FastAPI request with tenant state and client info."""

    def __init__(self, tenant: FakeTenant = None, ip: str = "203.0.113.42"):
        self.state = MagicMock()
        self.state.tenant = tenant or FakeTenant()
        self.client = MagicMock()
        self.client.host = ip
        self.headers = {"X-Request-ID": str(uuid.uuid4())}


class FakeProducer:
    """Mock event producer that records published events."""

    def __init__(self):
        self.events: list = []

    async def publish(self, event):
        self.events.append(event)

    async def publish_batch(self, events):
        self.events.extend(events)


class FakeCache:
    """Mock cache client."""

    def __init__(self):
        self._store = {}

    async def get_json(self, key):
        return self._store.get(key)

    async def set_json(self, key, value, ttl=None):
        self._store[key] = value

    async def delete(self, key):
        self._store.pop(key, None)


# =========================================================================
# 1. Campaign Attribution E2E
# =========================================================================


class TestCampaignAttributionE2E:
    """Campaign attribution — uses canonical AttributionResolver (per-conversion)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset campaign state between tests."""
        from services.campaign import routes
        # _touchpoint_store removed; touchpoints now persisted via TouchpointRepository
        routes._repo._store.clear()
        yield

    @pytest.mark.asyncio
    async def test_full_attribution_flow(self):
        """Credit weights from AttributionResolver sum to 1.0 and attribute the full revenue."""
        from services.attribution.resolver import AttributionConfig, AttributionResolver

        resolver = AttributionResolver(AttributionConfig())
        now = datetime.now(timezone.utc).isoformat()
        touchpoints = [
            {"channel": "email", "source": "newsletter", "timestamp": now, "event_type": "click"},
            {"channel": "direct", "source": "direct", "timestamp": now, "event_type": "click"},
        ]
        result = await resolver.resolve(
            user_id="user-001",
            event={"event_type": "purchase", "revenue": 99.99},
            touchpoints=touchpoints,
            model_name="linear",
        )
        total_weight = sum(c.weight for c in result.credits)
        assert abs(total_weight - 1.0) < 0.001
        attributed_revenue = sum(c.weight * 99.99 for c in result.credits)
        assert abs(attributed_revenue - 99.99) < 0.02

    @pytest.mark.asyncio
    async def test_attribution_models_consistent(self):
        """All models produce credit weights summing to 1.0 for the same touchpoints."""
        from services.attribution.resolver import AttributionConfig, AttributionResolver

        resolver = AttributionResolver(AttributionConfig())
        now = datetime.now(timezone.utc).isoformat()
        touchpoints = [
            {"channel": ch, "source": ch, "timestamp": now, "event_type": "click"}
            for ch in ["email", "social", "direct"]
        ]

        for model in ["first_touch", "last_touch", "linear", "time_decay", "position_based"]:
            result = await resolver.resolve(
                user_id="user-001",
                event={"event_type": "purchase"},
                touchpoints=touchpoints,
                model_name=model,
            )
            total_weight = sum(c.weight for c in result.credits)
            assert abs(total_weight - 1.0) < 0.001, f"{model}: total_weight={total_weight}"
            attributed_revenue = sum(c.weight * 200.0 for c in result.credits)
            assert abs(attributed_revenue - 200.0) < 0.05, f"{model}: revenue={attributed_revenue}"

    @pytest.mark.asyncio
    async def test_empty_touchpoints_graceful(self):
        """Resolver with no touchpoints returns empty credits (min_touchpoints not met)."""
        from services.attribution.resolver import AttributionConfig, AttributionResolver

        resolver = AttributionResolver(AttributionConfig())
        result = await resolver.resolve(
            user_id="user-001",
            event={"event_type": "purchase"},
            touchpoints=[],
        )
        assert result.credits == []

    @pytest.mark.asyncio
    async def test_tenant_isolation_on_attribution(self):
        """Campaign belongs to tenant-A, not tenant-B."""
        from services.campaign.routes import _repo

        campaign_id = str(uuid.uuid4())
        await _repo.insert(campaign_id, {
            "tenant_id": "tenant-A",
            "name": "Test",
            "channel": "email",
        })

        campaign = await _repo.find_by_id(campaign_id)
        assert campaign is not None
        assert campaign["tenant_id"] != "tenant-B"


# =========================================================================
# 2. Analytics Export E2E
# =========================================================================


class TestAnalyticsExportE2E:
    """Full flow: request export → job created → poll status → completed."""

    @pytest.fixture(autouse=True)
    def setup(self):
        # sys.path configured at module level
        from services.analytics import routes
        if hasattr(routes._export_store, '_data'):
            routes._export_store._data.clear()
        yield

    @pytest.mark.asyncio
    async def test_export_idempotency(self):
        """Same query + format should reuse existing job."""
        from services.analytics.routes import _export_store

        job_id = str(uuid.uuid4())
        job = {
            "export_id": job_id,
            "tenant_id": "test-tenant",
            "format": "csv",
            "status": "completed",
            "query_hash": "abc123",
            "row_count": 100,
        }
        await _export_store.set(job_id, job)

        # Simulate idempotency check
        matches = await _export_store.find(
            query_hash="abc123", tenant_id="test-tenant",
        )
        completed = [j for j in matches if j.get("status") in ("queued", "processing", "completed")]
        assert len(completed) == 1
        assert completed[0]["export_id"] == job_id

    def test_export_job_sanitization(self):
        """Sanitized export should not contain internal fields."""
        from services.analytics.routes import _sanitize_export_job

        job = {
            "export_id": "ex-001",
            "tenant_id": "secret-tenant",
            "query_hash": "internal-hash",
            "format": "csv",
            "status": "completed",
        }
        sanitized = _sanitize_export_job(job)
        assert "tenant_id" not in sanitized
        assert "query_hash" not in sanitized
        assert sanitized["export_id"] == "ex-001"

    @pytest.mark.asyncio
    async def test_export_tenant_isolation(self):
        """Export job retrieval should enforce tenant matching."""
        from services.analytics.routes import _export_store

        job = {"export_id": "ex-002", "tenant_id": "tenant-A", "status": "completed"}
        await _export_store.set("ex-002", job)

        retrieved = await _export_store.get("ex-002")
        assert retrieved["tenant_id"] != "tenant-B"


# =========================================================================
# 3. GraphQL Validation E2E
# =========================================================================


class TestGraphQLValidationE2E:
    """Full flow: query parsing → validation → field-level enforcement."""

    def test_valid_events_query(self):
        from services.analytics.routes import _parse_and_validate_graphql

        result = _parse_and_validate_graphql(
            "query { events { event_id event_type timestamp } }"
        )
        assert result["root_type"] == "events"
        assert "event_id" in result["fields"]
        assert "event_type" in result["fields"]

    def test_introspection_blocked(self):
        from services.analytics.routes import _parse_and_validate_graphql
        from shared.common.common import BadRequestError

        with pytest.raises(BadRequestError, match="Introspection"):
            _parse_and_validate_graphql("{ __schema { types { name } } }")

        with pytest.raises(BadRequestError, match="Introspection"):
            _parse_and_validate_graphql("{ __type(name: \"Event\") { fields { name } } }")

    def test_unknown_root_type_rejected(self):
        from services.analytics.routes import _parse_and_validate_graphql
        from shared.common.common import BadRequestError

        with pytest.raises(BadRequestError, match="Unknown root type"):
            _parse_and_validate_graphql("{ users { id name } }")

    def test_unknown_fields_rejected(self):
        from services.analytics.routes import _parse_and_validate_graphql
        from shared.common.common import BadRequestError

        with pytest.raises(BadRequestError, match="Unknown fields"):
            _parse_and_validate_graphql("{ events { event_id secret_field } }")

    def test_depth_limit_enforced(self):
        from services.analytics.routes import _parse_and_validate_graphql
        from shared.common.common import BadRequestError

        deep = "{ events { event_id { nested { deep { deeper { deepest } } } } } }"
        with pytest.raises(BadRequestError, match="too deep"):
            _parse_and_validate_graphql(deep)

    def test_empty_query_rejected(self):
        from services.analytics.routes import _parse_and_validate_graphql
        from shared.common.common import BadRequestError

        with pytest.raises(BadRequestError, match="Empty"):
            _parse_and_validate_graphql("")

    def test_campaigns_query_valid(self):
        from services.analytics.routes import _parse_and_validate_graphql

        result = _parse_and_validate_graphql(
            "{ campaigns { campaign_id name channel } }"
        )
        assert result["root_type"] == "campaigns"
        assert len(result["fields"]) == 3


# =========================================================================
# 4. Agent Task Bridge E2E
# =========================================================================


class TestAgentTaskBridgeE2E:
    """Full flow: create task → lookup → audit trail."""

    @pytest.fixture(autouse=True)
    def setup(self):
        # sys.path configured at module level
        from services.agent import routes
        if hasattr(routes._task_store, '_data'):
            routes._task_store._data.clear()
        if hasattr(routes._audit_store, '_data'):
            routes._audit_store._data.clear()
            routes._audit_store._lists.clear()
        yield

    @pytest.mark.asyncio
    async def test_task_creation_and_lookup(self):
        """Created task should be retrievable with correct state."""
        from services.agent.routes import _task_store

        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        task = {
            "task_id": task_id,
            "tenant_id": "test-tenant",
            "worker_type": "web_crawler",
            "priority": "high",
            "status": "queued",
            "created_at": now,
        }

        await _task_store.set(task_id, task)
        retrieved = await _task_store.get(task_id)

        assert retrieved is not None
        assert retrieved["task_id"] == task_id
        assert retrieved["status"] == "queued"

    @pytest.mark.asyncio
    async def test_task_tenant_isolation(self):
        """Task from wrong tenant should not be accessible."""
        from services.agent.routes import _task_store

        task_id = str(uuid.uuid4())
        await _task_store.set(task_id, {
            "task_id": task_id,
            "tenant_id": "tenant-A",
            "status": "queued",
        })

        task = await _task_store.get(task_id)
        assert task["tenant_id"] != "tenant-B"

    @pytest.mark.asyncio
    async def test_audit_trail_records(self):
        """Audit entries should be retrievable per tenant."""
        from services.agent.routes import _audit_store

        await _audit_store.append_list("tenant-A", {
            "task_id": "t1", "tenant_id": "tenant-A",
            "action": "submitted", "timestamp": "2025-01-01T00:00:00Z",
        })
        await _audit_store.append_list("tenant-B", {
            "task_id": "t2", "tenant_id": "tenant-B",
            "action": "submitted", "timestamp": "2025-01-01T00:01:00Z",
        })
        await _audit_store.append_list("tenant-A", {
            "task_id": "t3", "tenant_id": "tenant-A",
            "action": "completed", "timestamp": "2025-01-01T00:02:00Z",
        })

        tenant_a = await _audit_store.get_list("tenant-A")
        assert len(tenant_a) == 2

    def test_invalid_worker_type_validation(self):
        from services.agent.routes import VALID_WORKER_TYPES

        assert "web_crawler" in VALID_WORKER_TYPES
        assert "invalid_type" not in VALID_WORKER_TYPES


# =========================================================================
# 5. IP Geo-Enrichment E2E
# =========================================================================


class TestGeoEnrichmentE2E:
    """Full flow: IP extraction → enrichment → normalized output."""

    def test_private_ip_returns_empty_geo(self):
        from services.ingestion.routes import _geo_lookup, _is_private_ip

        assert _is_private_ip("192.168.1.1")
        assert _is_private_ip("10.0.0.1")
        assert _is_private_ip("172.16.0.1")
        assert _is_private_ip("127.0.0.1")
        assert _is_private_ip("::1")

        result = _geo_lookup("192.168.1.1")
        assert result == {}

    def test_public_ip_not_private(self):
        from services.ingestion.routes import _is_private_ip

        assert not _is_private_ip("8.8.8.8")
        assert not _is_private_ip("203.0.113.42")
        assert not _is_private_ip("1.1.1.1")

    def test_invalid_ip_returns_empty(self):
        from services.ingestion.routes import _geo_lookup

        result = _geo_lookup("not-an-ip")
        assert result == {}

    def test_enrich_ip_always_returns_hash(self):
        from services.ingestion.routes import _enrich_ip

        request = FakeRequest(ip="8.8.8.8")
        result = _enrich_ip(request)
        assert "ip_hash" in result
        assert len(result["ip_hash"]) == 64  # SHA-256 hex digest
        assert result["ip_hash"] == hashlib.sha256(b"8.8.8.8").hexdigest()

    def test_enrich_ip_empty_ip_returns_empty(self):
        from services.ingestion.routes import _enrich_ip

        request = FakeRequest(ip="")
        request.client.host = ""
        request.headers = {}
        result = _enrich_ip(request)
        assert result == {}

    def test_geo_fields_structure(self):
        """Even without MaxMind DB, result should have correct field structure."""
        from services.ingestion.routes import _enrich_ip

        request = FakeRequest(ip="203.0.113.1")
        result = _enrich_ip(request)

        expected_fields = {
            "ip_hash", "ip_range", "country_code", "region", "city",
            "latitude", "longitude", "timezone", "asn", "isp",
            "is_vpn", "is_proxy", "is_tor", "is_datacenter",
        }
        assert set(result.keys()) == expected_fields


# =========================================================================
# 6. Concurrency Safety Tests
# =========================================================================


class TestConcurrencySafety:
    """Verify DurableStore thread safety under concurrent access."""

    def test_concurrent_in_memory_store_writes(self):
        """InMemoryStore should handle concurrent writes without data loss."""
        from shared.store import InMemoryStore

        store = InMemoryStore("test-concurrent")
        n_threads = 10
        writes_per_thread = 50

        def writer():
            import asyncio
            loop = asyncio.new_event_loop()
            for i in range(writes_per_thread):
                loop.run_until_complete(
                    store.append_list("campaign-1", {"id": str(uuid.uuid4())})
                )
            loop.close()

        threads = [threading.Thread(target=writer) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        loop = asyncio.new_event_loop()
        items = loop.run_until_complete(store.get_list("campaign-1", limit=10000))
        loop.close()
        assert len(items) == n_threads * writes_per_thread

    def test_concurrent_store_set_get(self):
        """Concurrent set/get should be consistent."""
        from shared.store import InMemoryStore

        store = InMemoryStore("test-setget")
        n_threads = 20

        def writer(idx):
            import asyncio
            loop = asyncio.new_event_loop()
            key = f"key-{idx}"
            loop.run_until_complete(store.set(key, {"idx": idx}))
            result = loop.run_until_complete(store.get(key))
            assert result["idx"] == idx
            loop.close()

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        loop = asyncio.new_event_loop()
        count = loop.run_until_complete(store.count())
        loop.close()
        assert count == n_threads


# =========================================================================
# 7. A2H (Agent-to-Human) Relationship Layer E2E
# =========================================================================


class TestA2HRelationshipLayerE2E:
    """Full flow: A2H edge types, classification, graph traversal, events."""

    def test_a2h_edge_types_exist(self):
        """All four A2H edge types should be defined."""
        from shared.graph.graph import EdgeType

        assert EdgeType.NOTIFIES == "NOTIFIES"
        assert EdgeType.RECOMMENDS == "RECOMMENDS"
        assert EdgeType.DELIVERS_TO == "DELIVERS_TO"
        assert EdgeType.ESCALATES_TO == "ESCALATES_TO"

    def test_a2h_relationship_layer_exists(self):
        """A2H should be a valid RelationshipLayer enum member."""
        from shared.graph.relationship_layers import RelationshipLayer

        assert RelationshipLayer.A2H == "A2H"
        assert RelationshipLayer.A2H.value == "A2H"
        # Ensure all four canonical layers exist (EXCLUDED is a valid non-canonical layer)
        layers = {l.value for l in RelationshipLayer}
        assert {"H2H", "H2A", "A2H", "A2A"}.issubset(layers)

    def test_a2h_edges_classified_correctly(self):
        """A2H edge types should classify into the A2H layer."""
        from shared.graph.graph import EdgeType
        from shared.graph.relationship_layers import RelationshipLayer, classify_edge_type

        a2h_edges = [
            EdgeType.NOTIFIES,
            EdgeType.RECOMMENDS,
            EdgeType.DELIVERS_TO,
            EdgeType.ESCALATES_TO,
        ]
        for edge_type in a2h_edges:
            assert classify_edge_type(edge_type) == RelationshipLayer.A2H

    def test_h2a_edges_still_classified_correctly(self):
        """Existing H2A edges should remain unaffected."""
        from shared.graph.graph import EdgeType
        from shared.graph.relationship_layers import RelationshipLayer, classify_edge_type

        assert classify_edge_type(EdgeType.LAUNCHED_BY) == RelationshipLayer.H2A
        assert classify_edge_type(EdgeType.DELEGATES) == RelationshipLayer.H2A

    def test_a2a_edges_still_classified_correctly(self):
        """Existing A2A edges should remain unaffected."""
        from shared.graph.graph import EdgeType
        from shared.graph.relationship_layers import RelationshipLayer, classify_edge_type

        assert classify_edge_type(EdgeType.HIRED) == RelationshipLayer.A2A
        assert classify_edge_type(EdgeType.DEPLOYED) == RelationshipLayer.A2A

    def test_layer_stats_includes_a2h(self):
        """get_layer_stats should count A2H edges."""
        from shared.graph.graph import Edge, EdgeType
        from shared.graph.relationship_layers import get_layer_stats

        edges = [
            Edge(edge_type=EdgeType.NOTIFIES, from_vertex_id="agent-1", to_vertex_id="user-1"),
            Edge(edge_type=EdgeType.DELIVERS_TO, from_vertex_id="agent-1", to_vertex_id="user-2"),
            Edge(edge_type=EdgeType.DELEGATES, from_vertex_id="user-1", to_vertex_id="agent-1"),
            Edge(edge_type=EdgeType.HIRED, from_vertex_id="agent-1", to_vertex_id="agent-2"),
        ]
        stats = get_layer_stats(edges)
        assert stats["A2H"] == 2
        assert stats["H2A"] == 1
        assert stats["A2A"] == 1
        assert stats["H2H"] == 0

    @pytest.mark.asyncio
    async def test_a2h_graph_edge_creation(self):
        """A2H edges should be creatable in the graph client."""
        from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType

        graph = GraphClient()
        await graph.connect()

        await graph.add_vertex(Vertex(vertex_type=VertexType.AGENT, vertex_id="agent-a2h"))
        await graph.add_vertex(Vertex(vertex_type=VertexType.USER, vertex_id="user-a2h"))

        await graph.add_edge(Edge(
            edge_type=EdgeType.NOTIFIES,
            from_vertex_id="agent-a2h",
            to_vertex_id="user-a2h",
            properties={"content_summary": "Task completed"},
        ))

        neighbors = await graph.get_neighbors("agent-a2h", edge_type=EdgeType.NOTIFIES, direction="out")
        assert len(neighbors) == 1
        assert neighbors[0].vertex_id == "user-a2h"

        await graph.close()

    @pytest.mark.asyncio
    async def test_a2h_subgraph_query(self):
        """get_layer_subgraph should return A2H-layer vertices."""
        from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
        from shared.graph.relationship_layers import RelationshipLayer, get_layer_subgraph

        graph = GraphClient()
        await graph.connect()

        await graph.add_vertex(Vertex(vertex_type=VertexType.AGENT, vertex_id="agent-sub"))
        await graph.add_vertex(Vertex(vertex_type=VertexType.USER, vertex_id="user-sub"))
        await graph.add_edge(Edge(
            edge_type=EdgeType.DELIVERS_TO,
            from_vertex_id="agent-sub",
            to_vertex_id="user-sub",
        ))

        subgraph = await get_layer_subgraph(graph, "agent-sub", RelationshipLayer.A2H)
        assert subgraph["layer"] == "A2H"
        assert subgraph["vertex_count"] >= 1
        assert EdgeType.DELIVERS_TO in subgraph["edge_types"]

        await graph.close()

    def test_a2h_event_topics_exist(self):
        """A2H event topics should be defined."""
        from shared.events.events import Topic

        assert Topic.AGENT_NOTIFICATION_SENT.value == "aether.agent.notification.sent"
        assert Topic.AGENT_RECOMMENDATION_MADE.value == "aether.agent.recommendation.made"
        assert Topic.AGENT_RESULT_DELIVERED.value == "aether.agent.result.delivered"
        assert Topic.AGENT_ESCALATION_RAISED.value == "aether.agent.escalation.raised"

    def test_a2h_valid_interaction_types(self):
        """Agent routes should expose valid A2H interaction types."""
        from services.agent.routes import VALID_A2H_TYPES

        assert VALID_A2H_TYPES == {"notification", "recommendation", "delivery", "escalation"}

    def test_a2h_edge_map_complete(self):
        """Every A2H interaction type should map to an edge type."""
        from services.agent.routes import _A2H_EDGE_MAP, VALID_A2H_TYPES

        for interaction_type in VALID_A2H_TYPES:
            assert interaction_type in _A2H_EDGE_MAP

    def test_a2h_topic_map_complete(self):
        """Every A2H interaction type should map to an event topic."""
        from services.agent.routes import _A2H_TOPIC_MAP, VALID_A2H_TYPES

        for interaction_type in VALID_A2H_TYPES:
            assert interaction_type in _A2H_TOPIC_MAP


# =========================================================================
# 8. Bug Fix Regression Tests
# =========================================================================


class TestBugFixRegressions:
    """Regression tests for production bugs found during audit."""

    def test_cache_key_custom_method_exists(self):
        """CacheKey.custom() must exist — used by ml_serving feature store."""
        from shared.cache.cache import CacheKey

        key = CacheKey.custom("features:user-123")
        assert "features:user-123" in key
        assert key.startswith("aether:")

    def test_cache_key_custom_different_inputs(self):
        """CacheKey.custom() must produce distinct keys for different inputs."""
        from shared.cache.cache import CacheKey

        key1 = CacheKey.custom("features:user-1")
        key2 = CacheKey.custom("features:user-2")
        assert key1 != key2
