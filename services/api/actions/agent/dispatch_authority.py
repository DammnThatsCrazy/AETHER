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
        or evaluated > created
        or created > now
    ):
        return None
    return {
        "decision_id": decision_id,
        "evaluated_at": evaluated.isoformat(),
        "uri": f"store://security_policy_decisions/{quote(decision_id, safe='')}",
    }
