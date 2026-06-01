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
