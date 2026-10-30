"""Focused regression tests for durable action dispatch continuity."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from repositories.delivery_repos import DeliveryJobRepository
from intelligence.intelligence.decision_models import ActionDeliveryReceipt
from intelligence.intelligence.repositories import ActionDispatchRepository
from intelligence.intelligence import routes
from shared.graph.graph import Vertex

pytestmark = pytest.mark.asyncio


class _Tenant:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"

    def require_permission(self, _permission: str) -> None:
        return None

    def has_permission(self, _permission: str) -> bool:
        return self.dispatch_permission if _permission == "dispatch" else True


def _request(tenant_id: str, user_id: str | None = None, dispatch_permission: bool = True) -> SimpleNamespace:
    tenant = _Tenant(tenant_id)
    tenant.dispatch_permission = dispatch_permission
    if user_id is not None:
        tenant.user_id = user_id
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


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


async def test_dispatch_policy_uses_tenant_permission_and_binds_denial_to_durable_dispatch(monkeypatch):
    from governance.security.repositories import PolicyDecisionRepository
    from shared.common.common import BadRequestError

    monkeypatch.setattr(routes._action_targets, "get", lambda _name: _Target())
    monkeypatch.setattr(routes, "_load_dispatch_context", lambda _tenant, action_id: _async_context(action_id))
    await routes._actions.insert("action-1", {
        "action_id": "action-1", "tenant_id": "tenant-a", "decision_id": "decision-1",
        "action_type": "review", "status": "planned",
    })
    with pytest.raises(BadRequestError, match="lacks tenant dispatch permission"):
        await routes._dispatch_action(
            "action-1", routes.DispatchActionRequest(target_type="test"),
            _request("tenant-a", dispatch_permission=False),
        )
    rows = await routes._dispatches.find_many({"tenant_id": "tenant-a", "action_id": "action-1"}, limit=1)
    assert len(rows) == 1
    row = rows[0]
    policy = await PolicyDecisionRepository().find_by_id(row["dispatch_policy_decision_id"])
    assert policy["allowed"] is False
    assert policy["actor_id"] == row["dispatch_actor_id"] == "user-tenant-a"
    assert policy["context"]["dispatch_id"] == row["dispatch_id"]
    assert policy["context"]["target_type"] == row["target_type"] == "test"


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
    assert jobs[0]["idempotency_key"] == result["data"]["dispatch"]["dispatch_id"]


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
        "selected_action": {"action_key": "review", "action_type": "review", "label": "Review",
                            "requires_approval_level": "none"},
    }
    action = {
        "action_id": action_id, "tenant_id": "tenant-a", "decision_id": "decision-1",
        "action_type": "review", "authorization_metadata": {},
    }
    return action, decision, recommendation


async def _async_context(action_id: str = "action-1") -> tuple[dict, dict, dict]:
    return _context(action_id)


async def test_journey_dispatch_link_is_validated_and_idempotency_cannot_rebind(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from actions.agent.action_associations import validate_action_association
    from journeys.measurement.episodes.related_authorities import AuthorityFactRead, JourneyActionIntentRecord
    from graph.operational_intelligence.models import EvidenceRef
    from shared.common.common import ConflictError

    now = datetime.now(timezone.utc)
    intent = JourneyActionIntentRecord(record_id="intent-record-1", tenant_id="tenant-a", journey_id="journey-1",
        journey_version_id="version-1", action_intent_id="intent-1", recommendation_id="rec-1", action_key="review",
        action_type="review", label="Review", actor_ref="user-a", occurred_at=now-timedelta(seconds=2),
        recorded_at=now-timedelta(seconds=1), evidence_refs=[EvidenceRef(id="version-1", type="event", source="journey_versions"),
                                                            EvidenceRef(id="step-1", type="event", source="journey_steps")])
    class Journeys:
        async def get_current(self, tenant_id, journey_id):
            return {"tenant_id": tenant_id, "journey_id": journey_id, "journey_version_id": "version-1", "is_current": True}
    class Intents:
        async def list_for_subject(self, *args, **kwargs):
            return AuthorityFactRead(records=(intent.model_dump(mode="json"),), available=True, complete=True)
    async def validate(**kwargs):
        return await validate_action_association(**kwargs, journey_authority=Intents(), journey_repository=Journeys())
    async def context(_tenant, action_id):
        action, decision, recommendation = _context(action_id)
        action["recommendation_id"] = "rec-1"
        decision["selected_action"]["action_key"] = "review"
        return action, decision, recommendation
    target = _Target()
    monkeypatch.setattr(routes._action_targets, "get", lambda _name: target)
    monkeypatch.setattr(routes, "_load_dispatch_context", context)
    monkeypatch.setattr(routes, "validate_action_association", validate)
    action, decision, recommendation = await context("tenant-a", "action-1")
    await routes._actions.insert("action-1", action)
    await routes._decisions.insert("decision-1", decision)
    await routes._recommendations.insert("rec-1", recommendation)
    reference = {"journey_id": "journey-1", "journey_version_id": "version-1", "record_id": "intent-record-1"}
    body = routes.DispatchActionRequest(target_type="test", idempotency_key="journey-key", journey_action_reference=reference)
    result = await routes._dispatch_action("action-1", body, _request("tenant-a"))
    dispatch = result["data"]["dispatch"]
    assert dispatch["journey_action_association_record_id"] == "intent-record-1"
    assert dispatch["journey_action_association"]["recommendation_id"] == "rec-1"
    from actions.agent.journey_dispatch_association import read_journey_dispatches
    rows, complete = await read_journey_dispatches(tenant_id="tenant-a", journey_id="journey-1", version_id="version-1",
        record_id="intent-record-1", action_key="review", action_type="review", recommendation_id="rec-1",
        recorded_at=intent.recorded_at, occurred_at=intent.occurred_at)
    assert complete and rows[0]["dispatchId"] == dispatch["dispatch_id"]
    assert rows[0]["externalEffect"] == "not_independently_verified"
    async def unavailable_validation(**kwargs):
        raise ValueError("journey intent is no longer current")
    monkeypatch.setattr(routes, "validate_action_association", unavailable_validation)
    assert (await routes._dispatch_action("action-1", body, _request("tenant-a")))["data"]["replayed"]
    with pytest.raises(ConflictError):
        await routes._dispatch_action("action-1", body, _request("tenant-a", "different-user"))
    with pytest.raises(ConflictError):
        await routes._dispatch_action("action-1", routes.DispatchActionRequest(target_type="test", idempotency_key="journey-key"), _request("tenant-a"))
    assert target.calls == 1


async def test_risk_dispatch_binding_replays_without_revalidating_and_rejects_rebinding(monkeypatch):
    from actions.agent import risk_dispatch_association
    from shared.common.common import ConflictError

    target = _Target()
    async def context(_tenant, action_id):
        action, decision, recommendation = _context(action_id)
        action["recommendation_id"] = "rec-1"
        decision["selected_action"]["action_key"] = "review"
        recommendation["entity_id"] = "entity-1"
        return action, decision, recommendation
    async def validate(**kwargs):
        return {"kind": "risk_intervention", "record_id": "risk-1", "subject_id": "entity-1",
                "subject_kind": "entity", "intervention_id": "intervention-1", "action_key": "review",
                "link_state": "caller_associated"}
    async def current(*args):
        return None
    monkeypatch.setattr(routes._action_targets, "get", lambda _name: target)
    monkeypatch.setattr(routes, "_load_dispatch_context", context)
    monkeypatch.setattr(routes, "validate_action_association", validate)
    monkeypatch.setattr(risk_dispatch_association, "validate_current_risk_decision", current)
    action, _, _ = await context("tenant-a", "action-1")
    await routes._actions.insert("action-1", action)
    reference = {"record_id": "risk-1", "subject_kind": "entity", "subject_id": "entity-1"}
    with pytest.raises(routes.BadRequestError):
        rebound_ingress = routes.DispatchActionRequest(
            target_type="test", idempotency_key="risk-cross-subject",
            risk_action_reference={"record_id": "risk-1", "subject_kind": "entity", "subject_id": "entity-2"},
        )
        await routes._dispatch_action("action-1", rebound_ingress, _request("tenant-a"))
    body = routes.DispatchActionRequest(target_type="test", idempotency_key="risk-key", risk_action_reference=reference)
    result = await routes._dispatch_action("action-1", body, _request("tenant-a"))
    assert result["data"]["dispatch"]["risk_action_association"]["recommendation_id"] == "rec-1"
    async def unavailable(*args, **kwargs):
        raise AssertionError("replay must use stored binding")
    monkeypatch.setattr(routes, "validate_action_association", unavailable)
    assert (await routes._dispatch_action("action-1", body, _request("tenant-a")))["data"]["replayed"]
    with pytest.raises(ConflictError):
        await routes._dispatch_action("action-1", routes.DispatchActionRequest(target_type="test", idempotency_key="risk-key"), _request("tenant-a"))
    with pytest.raises(ConflictError):
        rebound = routes.DispatchActionRequest(
            target_type="test", idempotency_key="risk-key",
            risk_action_reference={"record_id": "risk-1", "subject_kind": "entity", "subject_id": "entity-2"},
        )
        await routes._dispatch_action("action-1", rebound, _request("tenant-a"))
    stored = (await routes._dispatches.find_many(
        {"tenant_id": "tenant-a", "action_id": "action-1", "idempotency_key": "risk-key"}, limit=1
    ))[0]
    original_recommendation = stored["risk_action_association"]["recommendation_id"]
    stored["risk_action_association"]["recommendation_id"] = "different-rec"
    with pytest.raises(ConflictError):
        await routes._dispatch_action("action-1", body, _request("tenant-a"))
    stored["risk_action_association"]["recommendation_id"] = original_recommendation
    assert target.calls == 1
