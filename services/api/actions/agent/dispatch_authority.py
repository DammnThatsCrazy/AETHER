"""Validation for persisted tenant action-dispatch permission decisions."""
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from shared.temporal.instant import parse_instant_strict


async def read_dispatch_authorization(
    *, tenant_id: str, action_id: str, dispatch: dict[str, Any], policy_decisions: Any = None,
) -> dict[str, str] | None:
    decision_id = dispatch.get("dispatch_policy_decision_id")
    if not isinstance(decision_id, str) or not decision_id.strip():
        return None
    if policy_decisions is None:
        from governance.security.repositories import PolicyDecisionRepository

        policy_decisions = PolicyDecisionRepository()
    decision = await policy_decisions.find_by_id(decision_id)
    if not isinstance(decision, dict):
        return None
    try:
        evaluated = parse_instant_strict(decision.get("evaluated_at"))
        created = parse_instant_strict(dispatch.get("created_at"))
        dispatched = parse_instant_strict(dispatch.get("dispatched_at")) if dispatch.get("dispatched_at") else created
    except (TypeError, ValueError):
        return None
    now = datetime.now(timezone.utc)
    if (
        decision.get("decision_id") != decision_id
        or decision.get("tenant_id") != tenant_id
        or decision.get("policy_key") != "action.dispatch"
        or decision.get("actor_type") != "tenant_user"
        or not isinstance(decision.get("actor_id"), str)
        or not decision["actor_id"].strip()
        or decision.get("action") != "dispatch"
        or decision.get("resource_type") != "action"
        or decision.get("resource_id") != action_id
        or decision.get("allowed") is not True
        or not isinstance(dispatch.get("dispatch_actor_id"), str)
        or not dispatch.get("dispatch_actor_id", "").strip()
        or decision.get("actor_id") != dispatch.get("dispatch_actor_id")
        or dispatch.get("dispatch_requires_elevation") not in {True, False}
        or not isinstance(dispatch.get("dispatch_action_key"), str)
        or not dispatch.get("dispatch_action_key", "").strip()
        or not isinstance(dispatch.get("dispatch_action_type"), str)
        or not dispatch.get("dispatch_action_type", "").strip()
        or dispatch.get("target_type") is None
        or not isinstance(decision.get("context"), dict)
        or decision.get("context") != {
            "dispatch_id": dispatch.get("dispatch_id"),
            "target_type": dispatch.get("target_type"),
            "selected_action_key": dispatch.get("dispatch_action_key"),
            "selected_action_type": dispatch.get("dispatch_action_type"),
            "is_elevated": dispatch.get("dispatch_requires_elevation"),
            "approval_id": dispatch.get("dispatch_approval_id"),
            "association_record_id": (
                dispatch.get("journey_action_association_record_id")
                or dispatch.get("risk_action_association_record_id")
            ),
        }
        or (dispatch.get("dispatch_requires_elevation") is True
            and not dispatch.get("dispatch_approval_id"))
        # A recoverable authorization-persistence retry can evaluate policy
        # after the reservation was created. It must still precede delivery.
        or evaluated > dispatched
        or created > now
    ):
        return None
    return {
        "decision_id": decision_id,
        "evaluated_at": evaluated.isoformat(),
        "uri": f"store://security_policy_decisions/{quote(decision_id, safe='')}",
    }
