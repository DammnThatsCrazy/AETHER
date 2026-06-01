from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT.parent / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))
pytest.importorskip("fastapi")


class FakeTenant:
    def __init__(self, tenant_id="tenant-route-1"):
        self.tenant_id = tenant_id

    def require_permission(self, perm: str) -> None:
        return None


class FakeRequest:
    def __init__(self, tenant_id="tenant-route-1"):
        self.state = MagicMock()
        self.state.tenant = FakeTenant(tenant_id)


def _set_decision_flags(routes, enabled: bool) -> dict[str, bool]:
    cfg = routes.settings.decision_outcome
    previous = {
        "recommendations_enabled": cfg.recommendations_enabled,
        "decision_records_enabled": cfg.decision_records_enabled,
        "outcome_feedback_enabled": cfg.outcome_feedback_enabled,
        "playbooks_enabled": cfg.playbooks_enabled,
    }
    for key in previous:
        object.__setattr__(cfg, key, enabled)
    return previous


def _restore_decision_flags(routes, previous: dict[str, bool]) -> None:
    for key, value in previous.items():
        object.__setattr__(routes.settings.decision_outcome, key, value)


@pytest.mark.asyncio
async def test_recommend_decide_act_learn_flow_is_tenant_scoped():
    from repositories.repos import reset_in_memory_stores
    from services.intelligence import routes

    reset_in_memory_stores()
    previous_flags = _set_decision_flags(routes, True)
    try:
        request = FakeRequest()
        rec_resp = await routes.generate_entity_recommendation(
            routes.GenerateRecommendationRequest(entity_id="entity-abc", signals={"churn_probability": 0.75}), request
        )
        rec = rec_resp["data"]
        assert rec["tenant_id"] == "tenant-route-1"

        list_resp = await routes.list_intelligence_recommendations(request)
        assert list_resp["data"]["count"] == 1

        other_list = await routes.list_intelligence_recommendations(FakeRequest("other-tenant"))
        assert other_list["data"]["count"] == 0

        decision_resp = await routes.record_decision(
            rec["recommendation_id"],
            routes.DecisionRequest(actor_id="analyst-1", selected_action_key=rec["recommended_action"]["action_key"], decision_status="approved"),
            request,
        )
        decision = decision_resp["data"]
        assert decision["decision_status"] == "approved"

        action_resp = await routes.log_action(
            routes.ActionLogRequest(decision_id=decision["decision_id"], action_type="manual", status="executed", actor_type="human"),
            request,
        )
        action = action_resp["data"]
        assert action["status"] == "executed"

        before = (await routes.get_intelligence_recommendation(rec["recommendation_id"], request))["data"]["confidence"]["overall"]
        outcome_resp = await routes.observe_outcome(
            action["action_id"],
            routes.OutcomeRequest(
                recommendation_id=rec["recommendation_id"],
                entity_id="entity-abc",
                outcome_type="retention",
                label="success",
                observed_window={"start": "2026-05-01T00:00:00Z", "end": "2026-05-31T00:00:00Z"},
            ),
            request,
        )
        assert outcome_resp["data"]["confidence_delta"] > 0
        after = (await routes.get_intelligence_recommendation(rec["recommendation_id"], request))["data"]["confidence"]["overall"]
        assert after > before
    finally:
        _restore_decision_flags(routes, previous_flags)

class PermissionedTenant(FakeTenant):
    def __init__(self, tenant_id="tenant-route-1", permissions=None):
        super().__init__(tenant_id)
        self.permissions = set(permissions or {"read"})

    def require_permission(self, perm: str) -> None:
        from shared.common.common import ForbiddenError
        if perm not in self.permissions and "admin" not in self.permissions:
            raise ForbiddenError(f"Missing permission: {perm}")


class PermissionedRequest(FakeRequest):
    def __init__(self, tenant_id="tenant-route-1", permissions=None):
        self.state = MagicMock()
        self.state.tenant = PermissionedTenant(tenant_id, permissions)


class FakeGraph:
    def __init__(self):
        self.vertices = []
        self.edges = []

    async def upsert_vertex(self, vertex):
        self.vertices.append(vertex)

    async def add_edge(self, edge):
        self.edges.append(edge)


class FakeProducer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class FakeRegistry:
    def __init__(self):
        self.graph = FakeGraph()
        self.producer = FakeProducer()


@pytest.mark.asyncio
async def test_recommendation_preview_is_read_only_and_non_persistent(monkeypatch):
    from repositories.repos import reset_in_memory_stores
    from services.intelligence import routes
    from shared.common.common import ForbiddenError

    reset_in_memory_stores()
    registry = FakeRegistry()
    monkeypatch.setattr(routes, "get_registry", lambda: registry)
    previous_flags = _set_decision_flags(routes, True)
    try:
        request = PermissionedRequest(permissions={"read"})
        body = routes.GenerateRecommendationRequest(entity_id="entity-preview", signals={"churn_probability": 0.8})

        preview = (await routes.preview_entity_recommendation(body, request))["data"]
        assert preview["preview"] is True
        assert preview["tenant_id"] == "tenant-route-1"
        assert (await routes.list_intelligence_recommendations(request))["data"]["count"] == 0
        assert registry.graph.vertices == []
        assert registry.graph.edges == []
        assert registry.producer.events == []

        with pytest.raises(ForbiddenError):
            await routes.generate_entity_recommendation(body, request)
        assert (await routes.list_intelligence_recommendations(request))["data"]["count"] == 0
        assert registry.graph.edges == []
        assert registry.producer.events == []
    finally:
        _restore_decision_flags(routes, previous_flags)


@pytest.mark.asyncio
async def test_write_user_can_generate_persisted_recommendation(monkeypatch):
    from repositories.repos import reset_in_memory_stores
    from services.intelligence import routes

    reset_in_memory_stores()
    registry = FakeRegistry()
    monkeypatch.setattr(routes, "get_registry", lambda: registry)
    previous_flags = _set_decision_flags(routes, True)
    try:
        request = PermissionedRequest(permissions={"read", "write"})
        body = routes.GenerateRecommendationRequest(entity_id="entity-generate", signals={"churn_probability": 0.8})

        rec = (await routes.generate_entity_recommendation(body, request))["data"]
        assert rec["recommendation_id"]
        assert (await routes.list_intelligence_recommendations(request))["data"]["count"] == 1
        assert registry.graph.vertices
        assert registry.graph.edges
        assert len(registry.producer.events) == 1
    finally:
        _restore_decision_flags(routes, previous_flags)


@pytest.mark.asyncio
async def test_outcome_ledger_endpoints_are_tenant_isolated(monkeypatch):
    from repositories.repos import reset_in_memory_stores
    from services.intelligence import routes

    reset_in_memory_stores()
    monkeypatch.setattr(routes, "get_registry", lambda: FakeRegistry())
    previous_flags = _set_decision_flags(routes, True)
    try:
        request = PermissionedRequest(permissions={"read", "write"})
        other_request = PermissionedRequest(tenant_id="other-tenant", permissions={"read"})
        rec = (await routes.generate_entity_recommendation(
            routes.GenerateRecommendationRequest(entity_id="entity-ledger", signals={"churn_probability": 0.9, "ltv_predicted_usd": 1000}),
            request,
        ))["data"]
        decision = (await routes.record_decision(
            rec["recommendation_id"],
            routes.DecisionRequest(actor_id="analyst", selected_action_key=rec["recommended_action"]["action_key"], decision_status="approved"),
            request,
        ))["data"]
        action = (await routes.log_action(
            routes.ActionLogRequest(decision_id=decision["decision_id"], action_type="manual", status="planned"),
            request,
        ))["data"]
        await routes.observe_outcome(
            action["action_id"],
            routes.OutcomeRequest(
                recommendation_id=rec["recommendation_id"],
                entity_id="entity-ledger",
                outcome_type="retention",
                value=125.0,
                label="success",
                observed_window={"start": "2026-05-01T00:00:00Z", "end": "2026-05-31T00:00:00Z"},
            ),
            request,
        )

        summary = (await routes.get_outcome_ledger_summary(request))["data"]
        assert summary["recommendations_generated"] == 1
        assert summary["decisions_recorded"] == 1
        assert summary["actions_logged"] == 1
        assert summary["outcomes_observed"] == 1
        assert summary["success_count"] == 1
        assert summary["observed_value"] == 125.0
        assert summary["pending_value"] >= 0
        assert summary["confidence_delta_total"] == 0.05

        by_type = (await routes.get_outcome_ledger_by_recommendation_type(request))["data"]["items"]
        assert by_type[0]["key"] == "retention"
        assert by_type[0]["observed_value"] == 125.0
        by_playbook = (await routes.get_outcome_ledger_by_playbook(request))["data"]["items"]
        assert by_playbook == []
        other_summary = (await routes.get_outcome_ledger_summary(other_request))["data"]
        assert other_summary["recommendations_generated"] == 0
        assert other_summary["observed_value"] == 0
    finally:
        _restore_decision_flags(routes, previous_flags)


@pytest.mark.asyncio
async def test_profile_outcome_ledger_filters_to_entity(monkeypatch):
    from repositories.repos import reset_in_memory_stores
    from services.intelligence import routes
    from services.profile import routes as profile_routes

    reset_in_memory_stores()
    monkeypatch.setattr(routes, "get_registry", lambda: FakeRegistry())
    previous_flags = _set_decision_flags(routes, True)
    try:
        request = PermissionedRequest(permissions={"read", "write"})
        rec = (await routes.generate_entity_recommendation(
            routes.GenerateRecommendationRequest(entity_id="entity-profile", signals={"churn_probability": 0.9, "ltv_predicted_usd": 500}),
            request,
        ))["data"]
        decision = (await routes.record_decision(
            rec["recommendation_id"],
            routes.DecisionRequest(actor_id="analyst", selected_action_key=rec["recommended_action"]["action_key"], decision_status="approved"),
            request,
        ))["data"]
        action = (await routes.log_action(routes.ActionLogRequest(decision_id=decision["decision_id"], action_type="manual"), request))["data"]
        await routes.observe_outcome(
            action["action_id"],
            routes.OutcomeRequest(
                recommendation_id=rec["recommendation_id"],
                entity_id="entity-profile",
                outcome_type="retention",
                value=50.0,
                label="neutral",
                observed_window={"start": "2026-05-01T00:00:00Z", "end": "2026-05-31T00:00:00Z"},
            ),
            request,
        )

        ledger = (await profile_routes.get_profile_outcome_ledger("entity-profile", request))["data"]
        assert ledger["entity_id"] == "entity-profile"
        assert ledger["summary"]["recommendations_generated"] == 1
        assert ledger["summary"]["actions_logged"] == 1
        assert ledger["summary"]["neutral_count"] == 1
        assert ledger["summary"]["observed_value"] == 50.0
        empty = (await profile_routes.get_profile_outcome_ledger("other-entity", request))["data"]
        assert empty["summary"]["recommendations_generated"] == 0
    finally:
        _restore_decision_flags(routes, previous_flags)
