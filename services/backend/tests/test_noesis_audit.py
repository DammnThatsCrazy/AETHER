"""Tests for the Noesis audit ledger integration (P0.5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.noesis.models import NoesisQueryRequest
from services.noesis.service import NoesisService
from shared.auth.auth import TenantContext, Role
from shared.graph.graph import GraphClient


def _make_service(**kwargs) -> NoesisService:
    graph = MagicMock(spec=GraphClient)
    analytics = MagicMock()
    analytics.dashboard_summary = AsyncMock(return_value={})
    return NoesisService(graph=graph, analytics=analytics, **kwargs)


def _tenant(surface="aether") -> TenantContext:
    tc = MagicMock(spec=TenantContext)
    tc.tenant_id = "tenant-audit"
    tc.role = Role.VIEWER
    tc.permissions = ["read"]
    tc.has_permission = lambda p: p in ("read",)
    tc.require_permission = lambda p: None
    return tc


@pytest.mark.asyncio
async def test_audit_ledger_called_on_success():
    """On a successful query, AuditLedger.record() is called with event_type='noesis.query'."""
    mock_ledger = MagicMock()
    mock_ledger.record = AsyncMock()

    service = _make_service(audit_ledger=mock_ledger)

    # Mock entity search
    service.entities = MagicMock()
    service.entities.find_many = AsyncMock(return_value=[])

    req = NoesisQueryRequest(message="show me entities", surface="aether")
    await service.query(req, _tenant())

    mock_ledger.record.assert_called_once()
    call_kwargs = mock_ledger.record.call_args.kwargs
    assert call_kwargs["event_type"] == "noesis.query"
    assert call_kwargs["outcome"] == "allowed"
    assert call_kwargs["tenant_id"] == "tenant-audit"


@pytest.mark.asyncio
async def test_audit_ledger_called_on_unsupported_after_llm_fallback():
    """When LLM provider returns None, audit must still be called with intent=unsupported."""
    mock_ledger = MagicMock()
    mock_ledger.record = AsyncMock()
    mock_provider = MagicMock()
    mock_provider.plan = AsyncMock(return_value=None)
    mock_provider.provider_name = "test-provider"

    service = _make_service(audit_ledger=mock_ledger, provider=mock_provider)

    req = NoesisQueryRequest(message="zzz totally unknown request xyz", surface="aether")
    resp = await service.query(req, _tenant())
    assert resp.intent == "unsupported"

    mock_ledger.record.assert_called_once()
    call_kwargs = mock_ledger.record.call_args.kwargs
    assert call_kwargs["action"] == "unsupported"


@pytest.mark.asyncio
async def test_audit_ledger_records_surface():
    """Audit record must contain the correct surface (aether vs kyber)."""
    mock_ledger = MagicMock()
    mock_ledger.record = AsyncMock()

    service = _make_service(audit_ledger=mock_ledger)
    service.entities = MagicMock()
    service.entities.find_many = AsyncMock(return_value=[])

    req = NoesisQueryRequest(message="find entities", surface="aether")
    await service.query(req, _tenant())

    call_kwargs = mock_ledger.record.call_args.kwargs
    assert call_kwargs["metadata"]["surface"] == "aether"
    assert call_kwargs["actor_type"] == "tenant_user"


@pytest.mark.asyncio
async def test_audit_ledger_failure_does_not_break_response():
    """If audit_ledger.record raises, the query response is still returned."""
    mock_ledger = MagicMock()
    mock_ledger.record = AsyncMock(side_effect=RuntimeError("ledger down"))

    service = _make_service(audit_ledger=mock_ledger)
    service.entities = MagicMock()
    service.entities.find_many = AsyncMock(return_value=[])

    req = NoesisQueryRequest(message="list entities", surface="aether")
    resp = await service.query(req, _tenant())
    # Response is still valid despite audit failure
    assert resp.intent is not None
