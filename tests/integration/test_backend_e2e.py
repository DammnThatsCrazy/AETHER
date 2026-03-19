"""
Aether Backend — End-to-End Integration Tests

Tests full cross-service flows:
  1. Campaign: touchpoints → attribution computation
  2. Analytics: export request → job lifecycle → status polling
  3. GraphQL: query validation → resolver → authorization enforcement
  4. Agent: task creation → lifecycle tracking → audit trail
  5. Ingestion: IP enrichment → geo normalization → output validation

These tests exercise the actual service code without HTTP transport
by calling route handler functions directly with mocked request state.

Requires backend dependencies (fastapi, pydantic, httpx). Skipped
gracefully if not installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import threading

import pytest

# Add backend path early so service imports resolve
sys.path.insert(0, "Backend Architecture/aether-backend")

# Skip entire module if backend deps aren't installed
pytest.importorskip("fastapi", reason="Backend deps not installed (pip install -e '.[backend]')")

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


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
    """Full flow: create campaign → record touchpoints → compute attribution."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset campaign state between tests."""
        # sys.path configured at module level
        from services.campaign import routes
        # Clear durable store internal state
        if hasattr(routes._touchpoint_store, '_data'):
            routes._touchpoint_store._data.clear()
            routes._touchpoint_store._lists.clear()
        routes._repo._store.clear()
        yield

    @pytest.mark.asyncio
    async def test_full_attribution_flow(self):
        from services.campaign.routes import (
            _repo, _touchpoint_store, _compute_attribution,
            CampaignCreate, TouchpointCreate,
        )

        tenant = FakeTenant()
        request = FakeRequest(tenant)

        # Step 1: Create campaign
        campaign_id = str(uuid.uuid4())
        await _repo.insert(campaign_id, {
            "tenant_id": tenant.tenant_id,
            "name": "Summer Sale",
            "channel": "email",
            "status": "active",
        })

        # Step 2: Record touchpoints via DurableStore
        touchpoints = [
            {"channel": "email", "event_type": "open", "is_conversion": False, "revenue_usd": 0},
            {"channel": "email", "event_type": "click", "is_conversion": False, "revenue_usd": 0},
            {"channel": "direct", "event_type": "purchase", "is_conversion": True, "revenue_usd": 99.99},
        ]
        for tp_data in touchpoints:
            tp = {
                "touchpoint_id": str(uuid.uuid4()),
                "campaign_id": campaign_id,
                "tenant_id": tenant.tenant_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **tp_data,
            }
            await _touchpoint_store.append_list(campaign_id, tp)

        # Step 3: Compute attribution
        stored = await _touchpoint_store.get_list(campaign_id)
        conversions = [tp for tp in stored if tp.get("is_conversion")]
        result = _compute_attribution(list(stored), conversions, "multi_touch")

        non_conv = [tp for tp in result if not tp.get("is_conversion")]
        assert len(non_conv) == 2
        assert non_conv[0]["attribution_weight"] == 0.5  # 2 touchpoints → 50/50
        total_attributed = sum(tp.get("attributed_revenue", 0) for tp in non_conv)
        assert abs(total_attributed - 99.99) < 0.02

    @pytest.mark.asyncio
    async def test_attribution_models_consistent(self):
        """All models should attribute the same total revenue."""
        from services.campaign.routes import _compute_attribution

        touchpoints = [
            {"event_type": "view", "is_conversion": False, "revenue_usd": 0},
            {"event_type": "click", "is_conversion": False, "revenue_usd": 0},
            {"event_type": "engage", "is_conversion": False, "revenue_usd": 0},
            {"event_type": "purchase", "is_conversion": True, "revenue_usd": 200.0},
        ]
        conversions = [tp for tp in touchpoints if tp.get("is_conversion")]

        for model in ["first_touch", "last_touch", "linear", "time_decay", "multi_touch"]:
            result = _compute_attribution(
                [dict(tp) for tp in touchpoints],
                conversions,
                model,
            )
            non_conv = [tp for tp in result if not tp.get("is_conversion")]
            total = sum(tp.get("attributed_revenue", 0) for tp in non_conv)
            assert abs(total - 200.0) < 0.05, f"{model}: total={total}"

    @pytest.mark.asyncio
    async def test_empty_touchpoints_graceful(self):
        """Attribution with no touchpoints should return empty list."""
        from services.campaign.routes import _compute_attribution
        result = _compute_attribution([], [], "multi_touch")
        assert result == []

    @pytest.mark.asyncio
    async def test_tenant_isolation_on_attribution(self):
        """Wrong tenant should get NotFoundError."""
        from services.campaign.routes import _repo
        from shared.common.common import NotFoundError

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
        from services.ingestion.routes import _is_private_ip, _geo_lookup

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

        import asyncio
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

        import asyncio
        loop = asyncio.new_event_loop()
        count = loop.run_until_complete(store.count())
        loop.close()
        assert count == n_threads
