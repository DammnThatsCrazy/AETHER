"""Read explicit journey-intent links to canonical decision action dispatches."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from shared.temporal.instant import parse_instant_strict


async def read_journey_dispatches(*, tenant_id: str, journey_id: str, version_id: str,
                                  record_id: str, action_key: str, action_type: str,
                                  recommendation_id: str, recorded_at: datetime, occurred_at: datetime,
                                  dispatches: Any = None, actions: Any = None,
                                  decisions: Any = None, recommendations: Any = None,
                                  policy_decisions: Any = None,
                                  limit: int = 20) -> tuple[list[dict[str, Any]], bool]:
    """Project bounded current dispatch state after exact tenant/decision joins.

    A dispatch status is a recorded lifecycle state; it is not an independently
    verified external effect. Historical replay and complete coverage are absent.
    """
    from intelligence.intelligence.repositories import (
        ActionDispatchRepository, ActionFeedbackRepository, DecisionRepository, RecommendationRepository,
    )
    dispatches = dispatches or ActionDispatchRepository()
    actions = actions or ActionFeedbackRepository()
    decisions = decisions or DecisionRepository()
    recommendations = recommendations or RecommendationRepository()
    from actions.agent.dispatch_authority import read_dispatch_authorization
    bounded = min(max(limit, 1), 20)
    try:
        rows = await dispatches.find_many(filters={"tenant_id": tenant_id,
            "journey_action_association_record_id": record_id}, limit=bounded + 1)
        if not isinstance(rows, list) or len(rows) > bounded:
            return [], False
        output, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                return [], False
            link = row.get("journey_action_association")
            dispatch_id, action_id, decision_id = (row.get(k) for k in ("dispatch_id", "action_id", "decision_id"))
            if (row.get("tenant_id") != tenant_id or not isinstance(link, dict)
                    or row.get("id") != dispatch_id or not all(isinstance(v, str) and v.strip() for v in (dispatch_id, action_id, decision_id))
                    or dispatch_id in seen or row.get("journey_action_association_record_id") != record_id
                    or link.get("kind") != "journey_action_intent" or link.get("link_state") != "caller_associated"
                    or link.get("record_id") != record_id or link.get("subject_id") != journey_id
                    or link.get("version_id") != version_id or link.get("action_key") != action_key
                    or link.get("action_type") != action_type or link.get("recommendation_id") != recommendation_id
                    or row.get("recommendation_id") != recommendation_id
                    or row.get("status") not in {"queued", "dispatched", "delivered", "failed", "cancelled"}):
                return [], False
            created = parse_instant_strict(row.get("created_at"))
            if created < recorded_at or created < occurred_at or created > datetime.now(timezone.utc):
                return [], False
            action = await actions.find_by_id(action_id)
            decision = await decisions.find_by_id(decision_id)
            recommendation = await recommendations.find_by_id(recommendation_id)
            selected = decision.get("selected_action") if isinstance(decision, dict) else None
            if (not isinstance(action, dict) or not isinstance(decision, dict) or not isinstance(recommendation, dict)
                    or action.get("tenant_id") != tenant_id or action.get("action_id") != action_id
                    or action.get("decision_id") != decision_id or action.get("recommendation_id") != recommendation_id
                    or action.get("action_type") != action_type or decision.get("tenant_id") != tenant_id
                    or decision.get("decision_id") != decision_id or decision.get("recommendation_id") != recommendation_id
                    or decision.get("decision_status") != "approved"
                    or not isinstance(selected, dict) or selected.get("action_key") != action_key
                    or selected.get("action_type") != action_type or recommendation.get("tenant_id") != tenant_id
                    or recommendation.get("recommendation_id") != recommendation_id):
                return [], False
            dispatch_authorization = await read_dispatch_authorization(
                tenant_id=tenant_id, action_id=action_id, dispatch=row, policy_decisions=policy_decisions,
            )
            if dispatch_authorization is None:
                return [], False
            seen.add(dispatch_id)
            output.append({"dispatchId": dispatch_id, "status": row["status"], "createdAt": created.isoformat(),
                           "externalEffect": "not_independently_verified", "evidenceRefs": [
                               {"id": dispatch_id, "type": "event", "source": "action_dispatches",
                                "observedAt": created.isoformat(), "uri": f"store://action_dispatches/{quote(dispatch_id, safe='')}"},
                               {"id": action_id, "type": "event", "source": "action_feedback"},
                               {"id": decision_id, "type": "event", "source": "decision_records"},
                               {"id": recommendation_id, "type": "model_output", "source": "recommendations"},
                               {"id": dispatch_authorization["decision_id"], "type": "event",
                                "source": "security_policy_decisions",
                                "observedAt": dispatch_authorization["evaluated_at"],
                                "uri": dispatch_authorization["uri"]}],
                           "dispatchAuthorization": dispatch_authorization})
        return output, True
    except Exception:  # noqa: BLE001 - authority failures are partial and never fabricate dispatch
        return [], False
