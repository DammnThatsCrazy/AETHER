"""Focused regression tests for durable action dispatch continuity."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from repositories.delivery_repos import DeliveryJobRepository
from services.intelligence.decision_models import ActionDeliveryReceipt
from services.intelligence.repositories import ActionDispatchRepository
from services.intelligence import routes
from shared.graph.graph import Vertex

pytestmark = pytest.mark.asyncio


class _Tenant:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"

    def require_permission(self, _permission: str) -> None:
        return None


def _request(tenant_id: str) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant(tenant_id)))


class _Target:
    target_type = "test"
    premium_connector = False

    def __init__(self) -> None:
        self.calls = 0

    def validate_config(self, _config) -> None:
        return None

    def build_payload(self, **_kwargs):
        return {"planned": True}

    async def dispatch(self, dispatch, _config):
        self.calls += 1
        await asyncio.sleep(0.01)
        return ActionDeliveryReceipt(
            receipt_id=f"receipt-{dispatch.dispatch_id}",
            dispatch_id=dispatch.dispatch_id,
            target_type=self.target_type,
            external_id="provider-123",
            delivered_at="2026-09-09T00:00:00+00:00",
            status="delivered",
        )


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_in_memory_stores()


async def test_dispatch_reservation_dedupes_concurrent_requests_and_is_tenant_scoped(monkeypatch):
    target = _Target()
    monkeypatch.setattr(routes._action_targets, "get", lambda _name: target)
    monkeypatch.setattr(
        routes,
        "_load_dispatch_context",
        lambda _tenant, action_id: _async_context(action_id),
    )
    await routes._actions.insert("action-1", {
        "action_id": "action-1", "tenant_id": "tenant-a", "decision_id": "decision-1",
        "action_type": "review", "status": "planned",
    })
    responses = await asyncio.gather(*(
        routes._dispatch_action(
            "action-1",
            routes.DispatchActionRequest(target_type="test", idempotency_key="same-key"),
            _request("tenant-a"),
        )
        for _ in range(2)
    ))
    assert target.calls == 1
    assert all(response["data"]["dispatch"]["tenant_id"] == "tenant-a" for response in responses)
    assert all(response["data"].get("replayed") in (None, True) for response in responses)

    repo = ActionDispatchRepository()
    first, created_a = await repo.reserve("tenant-a", "action-1", "same-key", {
        "dispatch_id": "manual-a", "tenant_id": "tenant-a", "action_id": "action-1",
        "idempotency_key": "same-key", "status": "queued",
    })
    second, created_b = await repo.reserve("tenant-b", "action-1", "same-key", {
        "dispatch_id": "manual-b", "tenant_id": "tenant-b", "action_id": "action-1",
        "idempotency_key": "same-key", "status": "queued",
    })
    assert created_a is False and first["tenant_id"] == "tenant-a"
    assert created_b is True and second["tenant_id"] == "tenant-b"


async def test_missing_connector_keeps_auditable_plan_without_delivery_claim(monkeypatch):
    target = routes._action_targets.get("agent_assist")
    monkeypatch.setattr(routes._action_targets, "get", lambda _name: target)
    monkeypatch.setattr(routes, "_load_dispatch_context", lambda _tenant, action_id: _async_context(action_id))
    await routes._actions.insert("action-2", {
        "action_id": "action-2", "tenant_id": "tenant-a", "decision_id": "decision-1",
        "action_type": "review", "status": "planned",
    })
    result = await routes._dispatch_action(
        "action-2",
        routes.DispatchActionRequest(target_type="agent_assist", idempotency_key="plan-key"),
        _request("tenant-a"),
    )
    assert result["data"]["planned"] is True
    assert result["data"]["external_side_effect"] is False
    assert result["data"]["receipt"] is None
    assert result["data"]["dispatch"]["status"] == "queued"
    jobs = await DeliveryJobRepository().find_many({"tenant_id": "tenant-a"}, limit=10)
    assert len(jobs) == 1
    assert jobs[0]["provider_adapter"] == "agent_assist"
    assert jobs[0]["idempotency_key"] == "plan-key"


async def test_graph_neighbor_authorization_is_explicit_and_tenant_scoped():
    own = Vertex("Entity", "own", {"tenant_id": "tenant-a"})
    other = Vertex("Entity", "other", {"tenant_id": "tenant-b"})
    legacy = Vertex("Entity", "legacy", {})
    assert routes._tenant_authorized_vertex(own, "tenant-a") is True
    assert routes._tenant_authorized_vertex(other, "tenant-a") is False
    assert routes._tenant_authorized_vertex(legacy, "tenant-a") is False


def _context(action_id: str = "action-1") -> tuple[dict, dict, dict]:
    recommendation = {
        "recommendation_id": "rec-1", "tenant_id": "tenant-a",
        "expected_outcome": "review", "candidate_actions": [],
    }
    decision = {
        "decision_id": "decision-1", "tenant_id": "tenant-a",
        "recommendation_id": "rec-1", "decision_status": "approved",
        "selected_action": {"action_type": "review", "label": "Review", "requires_approval_level": "none"},
    }
    action = {
        "action_id": action_id, "tenant_id": "tenant-a", "decision_id": "decision-1",
        "action_type": "review", "authorization_metadata": {},
    }
    return action, decision, recommendation


async def _async_context(action_id: str = "action-1") -> tuple[dict, dict, dict]:
    return _context(action_id)
