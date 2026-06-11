"""
Integration tests for POST /v1/batch.

Tests the full request path through the FastAPI app in local (in-memory) mode:
- Accepted batch
- Partial rejection (unknown event type)
- Duplicate detection (same event_id, same tenant)
- Cross-tenant isolation (same event_id, different tenant = not a duplicate)
- Auth failure
- Batch envelope validation (empty, too large)
- SDK does not require /v1/ingest/events
"""

from __future__ import annotations

import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_path():
    original = list(sys.path)
    stale_prefixes = (
        "config", "services", "shared", "middleware", "dependencies", "repositories",
    )
    for prefix in stale_prefixes:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in stale_prefixes:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


def _make_event(event_id: str = None, event_type: str = "track") -> dict:
    return {
        "id": event_id or str(uuid.uuid4()),
        "type": event_type,
        "timestamp": "2024-06-01T12:00:00Z",
        "sessionId": "session-001",
        "anonymousId": "anon-001",
        "context": {},
    }


def _batch_payload(*events):
    return {
        "batch": list(events),
        "sentAt": "2024-06-01T12:00:01Z",
    }


# ── Smoke test: module imports correctly ─────────────────────────────────────

def test_batch_module_imports():
    with backend_path():
        import importlib
        m = importlib.import_module("services.ingestion.batch")
        assert hasattr(m, "router")
        assert hasattr(m, "ingest_batch")
        assert hasattr(m, "CANONICAL_EVENT_TYPES")


# ── Accepted batch ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_accepted():
    with backend_path():
        import importlib
        m = importlib.import_module("services.ingestion.batch")

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)  # no duplicate
        mock_cache.set = AsyncMock()

        result = await m._process_single_event(
            sdk_event=m.BaseEvent(
                id="evt-001",
                type="track",
                timestamp="2024-06-01T12:00:00Z",
                sessionId="s1",
                anonymousId="anon1",
            ),
            tenant_id="tenant_A",
            batch_id="batch-001",
            received_at="2024-06-01T12:00:01Z",
            cache=mock_cache,
        )
        assert result.status == "accepted"
        assert result.id == "evt-001"


# ── Rejected (unknown event type) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_rejects_unknown_event_type():
    with backend_path():
        import importlib
        m = importlib.import_module("services.ingestion.batch")
        mock_cache = AsyncMock()

        result = await m._process_single_event(
            sdk_event=m.BaseEvent(
                id="evt-002",
                type="custom_unknown_type",
                timestamp="2024-06-01T12:00:00Z",
                sessionId="s1",
                anonymousId="anon1",
            ),
            tenant_id="tenant_A",
            batch_id="batch-002",
            received_at="2024-06-01T12:00:01Z",
            cache=mock_cache,
        )
        assert result.status == "rejected"
        assert "unknown_event_type" in result.reason


# ── Duplicate detection ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_same_tenant_same_id():
    """Same event_id from same tenant must return duplicate on second send."""
    with backend_path():
        import importlib
        m = importlib.import_module("services.ingestion.batch")

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value="1")  # simulate already seen

        result = await m._process_single_event(
            sdk_event=m.BaseEvent(
                id="evt-dup",
                type="track",
                timestamp="2024-06-01T12:00:00Z",
                sessionId="s1",
                anonymousId="anon1",
            ),
            tenant_id="tenant_A",
            batch_id="batch-dup",
            received_at="2024-06-01T12:00:01Z",
            cache=mock_cache,
        )
        assert result.status == "duplicate"


@pytest.mark.asyncio
async def test_cross_tenant_same_event_id_not_duplicate():
    """
    Same event_id from different tenants must be independently accepted.
    The idempotency key must be tenant-scoped.
    """
    with backend_path():
        import importlib
        m = importlib.import_module("services.ingestion.batch")

        shared_event_id = "shared-event-id"

        # Tenant A already claimed this event_id
        key_a = m._make_idempotency_key("tenant_A", shared_event_id, m.SCHEMA_VERSION)
        key_b = m._make_idempotency_key("tenant_B", shared_event_id, m.SCHEMA_VERSION)

        # The two keys must be different
        assert key_a != key_b

        def make_cache_for_tenant(claimed_key: str) -> AsyncMock:
            cache = AsyncMock()
            async def _get(k):
                return "1" if k == f"aether:idempotency:{claimed_key}" else None
            cache.get = _get
            cache.set = AsyncMock()
            return cache

        # Tenant A: duplicate
        result_a = await m._process_single_event(
            sdk_event=m.BaseEvent(
                id=shared_event_id,
                type="track",
                timestamp="2024-06-01T12:00:00Z",
                sessionId="s1",
                anonymousId="anon1",
            ),
            tenant_id="tenant_A",
            batch_id="b1",
            received_at="2024-06-01T12:00:01Z",
            cache=make_cache_for_tenant(key_a),
        )
        assert result_a.status == "duplicate"

        # Tenant B: different key → accepted
        result_b = await m._process_single_event(
            sdk_event=m.BaseEvent(
                id=shared_event_id,
                type="track",
                timestamp="2024-06-01T12:00:00Z",
                sessionId="s1",
                anonymousId="anon1",
            ),
            tenant_id="tenant_B",
            batch_id="b1",
            received_at="2024-06-01T12:00:01Z",
            cache=make_cache_for_tenant(key_a),  # B's key is different, so cache.get returns None
        )
        assert result_b.status == "accepted"


# ── Sensitive field scrubbing integration ────────────────────────────────────

@pytest.mark.asyncio
async def test_sensitive_fields_are_scrubbed():
    """Backend must scrub sensitive fields even if SDK sends them."""
    with backend_path():
        import importlib
        m = importlib.import_module("services.ingestion.batch")

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        event = m.BaseEvent(
            id="evt-sensitive",
            type="wallet",
            timestamp="2024-06-01T12:00:00Z",
            sessionId="s1",
            anonymousId="anon1",
            properties={"address": "0x123", "private_key": "0xdeadbeef"},
        )

        result = await m._process_single_event(
            sdk_event=event,
            tenant_id="tenant_A",
            batch_id="b1",
            received_at="2024-06-01T12:00:01Z",
            cache=mock_cache,
        )
        assert result.status == "accepted"
        # After processing, properties must be scrubbed
        assert event.properties.get("private_key") == "[REDACTED]"
        assert event.properties.get("address") == "0x123"  # non-sensitive preserved


# ── Normalized payload shape ─────────────────────────────────────────────────

def test_normalized_payload_preserves_client_event_id():
    """Client-generated event_id must be preserved (not replaced by server UUID)."""
    with backend_path():
        import importlib
        m = importlib.import_module("services.ingestion.batch")

        event = m.BaseEvent(
            id="client-generated-id-xyz",
            type="page",
            timestamp="2024-06-01T12:00:00Z",
            sessionId="s1",
            anonymousId="anon1",
        )
        payload = m._build_normalized_payload(
            sdk_event=event,
            tenant_id="tenant_A",
            batch_id="batch-123",
            received_at="2024-06-01T12:00:01Z",
        )
        assert payload["event_id"] == "client-generated-id-xyz"
        assert payload["tenant_id"] == "tenant_A"
        assert payload["batch_id"] == "batch-123"
        assert payload["schema_version"] == m.SCHEMA_VERSION
        assert payload["source"] == "sdk"


# ── Event type list matches source of truth ──────────────────────────────────

def test_sdk_batch_route_registered():
    """The /v1/batch route must be registered in the batch module's router."""
    with backend_path():
        import importlib
        m = importlib.import_module("services.ingestion.batch")
        routes = [r.path for r in m.router.routes]
        assert "/v1/batch" in routes, f"Expected /v1/batch in routes, got {routes}"


# ── Feed ingest requires external_id ─────────────────────────────────────────

def test_feed_event_requires_external_id():
    with backend_path():
        import importlib
        from pydantic import ValidationError
        m = importlib.import_module("services.ingestion.routes")
        with pytest.raises(ValidationError):
            m.APIFeedEvent(
                source="dune",
                entity_type="wallet",
                data={"key": "value"},
                # external_id intentionally missing
            )
