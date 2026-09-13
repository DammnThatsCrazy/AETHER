"""Tests for NoesisCircuitBreaker (P3.1)."""

from __future__ import annotations

import asyncio

import pytest

from services.noesis.circuit_breaker import (
    NoesisCircuitBreaker,
    _STATE_CLOSED,
    _STATE_HALF_OPEN,
    _STATE_OPEN,
)


async def _fail():
    raise RuntimeError("boom")


async def _succeed():
    return "ok"


@pytest.mark.asyncio
async def test_circuit_opens_after_failure_threshold():
    cb = NoesisCircuitBreaker("test", failure_threshold=3, recovery_timeout_s=60.0)
    for _ in range(3):
        result = await cb.call(_fail(), "fallback")
        assert result == "fallback"
    assert cb.state == _STATE_OPEN


@pytest.mark.asyncio
async def test_circuit_returns_fallback_immediately_when_open():
    cb = NoesisCircuitBreaker("test", failure_threshold=1, recovery_timeout_s=999.0)
    await cb.call(_fail(), "fallback")
    assert cb.state == _STATE_OPEN

    # Verify fallback is returned without error when OPEN
    result = await cb.call(_fail(), "fallback")
    assert result == "fallback"
    # State remains OPEN (no successful call was made)
    assert cb.state == _STATE_OPEN


@pytest.mark.asyncio
async def test_circuit_transitions_to_half_open_after_timeout():
    cb = NoesisCircuitBreaker("test", failure_threshold=1, recovery_timeout_s=0.01)
    await cb.call(_fail(), None)
    assert cb.state == _STATE_OPEN

    await asyncio.sleep(0.05)
    # Accessing _current_state via a call should transition to HALF_OPEN
    result = await cb.call(_succeed(), "fallback")
    assert result == "ok"
    assert cb.state == _STATE_CLOSED


@pytest.mark.asyncio
async def test_circuit_closes_after_successful_probe():
    cb = NoesisCircuitBreaker("test", failure_threshold=2, recovery_timeout_s=0.01)
    await cb.call(_fail(), None)
    await cb.call(_fail(), None)
    assert cb.state == _STATE_OPEN

    await asyncio.sleep(0.05)

    result = await cb.call(_succeed(), "fallback")
    assert result == "ok"
    assert cb.state == _STATE_CLOSED


@pytest.mark.asyncio
async def test_circuit_reset_clears_state():
    cb = NoesisCircuitBreaker("test", failure_threshold=1, recovery_timeout_s=999.0)
    await cb.call(_fail(), None)
    assert cb.state == _STATE_OPEN

    cb.reset()
    assert cb.state == _STATE_CLOSED

    result = await cb.call(_succeed(), "fallback")
    assert result == "ok"


@pytest.mark.asyncio
async def test_circuit_success_does_not_open():
    cb = NoesisCircuitBreaker("test", failure_threshold=5, recovery_timeout_s=30.0)
    for _ in range(10):
        result = await cb.call(_succeed(), "fallback")
        assert result == "ok"
    assert cb.state == _STATE_CLOSED


@pytest.mark.asyncio
async def test_graph_unavailability_returns_fallback_not_exception():
    """Verifies service graph calls return fallback (None/[]) when graph raises."""
    from unittest.mock import AsyncMock, MagicMock
    from services.noesis.service import NoesisService
    from services.noesis.models import NoesisQueryRequest
    from shared.auth.auth import TenantContext, Role
    from shared.graph.graph import GraphClient

    graph = MagicMock(spec=GraphClient)
    graph.get_vertex = AsyncMock(side_effect=RuntimeError("graph down"))
    graph.get_neighbors = AsyncMock(side_effect=RuntimeError("graph down"))
    graph.get_edges = AsyncMock(side_effect=RuntimeError("graph down"))

    analytics = MagicMock()
    analytics.dashboard_summary = AsyncMock(return_value={})

    service = NoesisService(graph=graph, analytics=analytics)

    tenant = MagicMock(spec=TenantContext)
    tenant.tenant_id = "t-cb-test"
    tenant.role = Role.VIEWER
    tenant.permissions = ["read"]
    tenant.has_permission = lambda p: p in ("read",)
    tenant.require_permission = lambda p: None

    req = NoesisQueryRequest(message="show graph for entity ent_123", surface="aether")
    resp = await service.query(req, tenant)
    # Should NOT raise — circuit breaker absorbs the error and returns degraded response
    assert resp is not None
    assert resp.graph is not None
