"""Bounded joins between risk intervention decisions and dispatch lifecycle rows."""
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from shared.temporal.instant import parse_instant_strict


def recommendation_matches_risk_subject(recommendation: Any, subject_kind: str, subject_id: str) -> bool:
    return bool(
        isinstance(recommendation, dict)
        and subject_kind == "entity"
        and isinstance(subject_id, str)
        and subject_id
        and recommendation.get("entity_id") == subject_id
        and not recommendation.get("population_id")
    )


async def validate_current_risk_decision(tenant_id: str, link: dict[str, str], repository: Any = None) -> None:
    from intelligence.risk360.store import RiskInterventionRepository

    now = datetime.now(timezone.utc)
    try:
        result = await (repository or RiskInterventionRepository()).list_for_subject(
            tenant_id, link["subject_kind"], link["subject_id"], as_of=now, limit=500
        )
        if any(row.tenant_id != tenant_id or row.subject_kind != link["subject_kind"]
               or row.subject_id != link["subject_id"] or row.recorded_at > now or row.observed_at > now
               for row in result.records):
            raise ValueError("risk intervention decision history out of scope")
        decisions = [row for row in result.records if row.record_kind == "decision"
                     and row.intervention_id == link["intervention_id"] and row.effective_at <= now]
        if not result.complete or not decisions:
            raise ValueError("risk intervention decision history incomplete")
        latest = max(row.effective_at for row in decisions)
        current = [row for row in decisions if row.effective_at == latest]
        if (len(current) != 1 or current[0].record_id != link["record_id"]
                or current[0].decision_state != "approved"
                or current[0].intervention_type != link["action_key"]):
            raise ValueError("risk intervention is not the current approved decision")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("risk intervention decision history unavailable") from exc


async def read_risk_dispatches(*, tenant_id: str, record: Any, dispatches: Any = None,
                               actions: Any = None, decisions: Any = None,
                               recommendations: Any = None, policy_decisions: Any = None,
                               delivery_evidence_reader: Any = None,
                               limit: int = 20) -> tuple[list[dict[str, Any]], bool]:
    from intelligence.intelligence.repositories import (
        ActionDispatchRepository, ActionFeedbackRepository, DecisionRepository, RecommendationRepository,
    )

    dispatches = dispatches or ActionDispatchRepository()
    actions = actions or ActionFeedbackRepository()
    decisions = decisions or DecisionRepository()
    recommendations = recommendations or RecommendationRepository()
    from actions.agent.dispatch_authority import read_dispatch_authorization
    from actions.agent.action_delivery_evidence import read_action_delivery_evidence
    bounded = min(max(limit, 1), 20)
    try:
        if (record.tenant_id != tenant_id or record.record_kind != "decision"
                or record.decision_state != "approved"):
            return [], False
        rows = await dispatches.find_many(filters={"tenant_id": tenant_id,
            "risk_action_association_record_id": record.record_id}, limit=bounded + 1)
        if not isinstance(rows, list) or len(rows) > bounded:
            return [], False
        output, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                return [], False
            link = row.get("risk_action_association")
            dispatch_id, action_id, decision_id, recommendation_id = (row.get(key) for key in
                ("dispatch_id", "action_id", "decision_id", "recommendation_id"))
            if (not isinstance(link, dict) or row.get("tenant_id") != tenant_id
                    or row.get("id") != dispatch_id
                    or not all(isinstance(value, str) and value.strip() for value in
                               (dispatch_id, action_id, decision_id, recommendation_id))
                    or dispatch_id in seen or row.get("risk_action_association_record_id") != record.record_id
                    or link.get("kind") != "risk_intervention" or link.get("link_state") != "caller_associated"
                    or link.get("record_id") != record.record_id or link.get("subject_id") != record.subject_id
                    or link.get("subject_kind") != record.subject_kind or link.get("intervention_id") != record.intervention_id
                    or link.get("action_key") != record.intervention_type or link.get("recommendation_id") != recommendation_id
                    or row.get("status") not in {"queued", "dispatched", "delivered", "failed", "cancelled"}):
                return [], False
            created = parse_instant_strict(row.get("created_at"))
            if (created < record.recorded_at or created < record.observed_at
                    or created < record.effective_at or created > datetime.now(timezone.utc)):
                return [], False
            action = await actions.find_by_id(action_id)
            decision = await decisions.find_by_id(decision_id)
            recommendation = await recommendations.find_by_id(recommendation_id)
            selected = decision.get("selected_action") if isinstance(decision, dict) else None
            if (not isinstance(action, dict) or not isinstance(decision, dict) or not isinstance(recommendation, dict)
                    or action.get("tenant_id") != tenant_id or action.get("action_id") != action_id
                    or action.get("decision_id") != decision_id or action.get("recommendation_id") != recommendation_id
                    or action.get("action_type") != link.get("action_type") or decision.get("tenant_id") != tenant_id
                    or decision.get("decision_id") != decision_id or decision.get("recommendation_id") != recommendation_id
                    or decision.get("decision_status") != "approved" or not isinstance(selected, dict)
                    or selected.get("action_key") != record.intervention_type
                    or selected.get("action_type") != link.get("action_type")
                    or recommendation.get("tenant_id") != tenant_id or recommendation.get("recommendation_id") != recommendation_id
                    or not recommendation_matches_risk_subject(recommendation, record.subject_kind, record.subject_id)):
                return [], False
            dispatch_authorization = await read_dispatch_authorization(
                tenant_id=tenant_id, action_id=action_id, dispatch=row, policy_decisions=policy_decisions,
            )
            if dispatch_authorization is None:
                return [], False
            evidence, delivery_complete = await (delivery_evidence_reader or read_action_delivery_evidence)(
                tenant_id=tenant_id, dispatch=row,
            )
            if not delivery_complete:
                return [], False
            evidence_refs = [
                {"id": dispatch_id, "type": "event", "source": "action_dispatches",
                 "observedAt": created.isoformat(), "uri": f"store://action_dispatches/{quote(dispatch_id, safe='')}"},
                {"id": action_id, "type": "event", "source": "action_feedback"},
                {"id": decision_id, "type": "event", "source": "decision_records"},
                {"id": recommendation_id, "type": "model_output", "source": "recommendations"},
                {"id": dispatch_authorization["decision_id"], "type": "event",
                 "source": "security_policy_decisions", "observedAt": dispatch_authorization["evaluated_at"],
                 "uri": dispatch_authorization["uri"]},
                *(delivery["evidenceRef"] for delivery in evidence["connectorReportedDeliveries"]),
                *(callback["evidenceRef"] for callback in evidence["verifiedCallbacks"]),
            ]
            seen.add(dispatch_id)
            output.append({"dispatchId": dispatch_id, "status": row["status"], "createdAt": created.isoformat(),
                           "externalEffect": "not_independently_verified", "evidenceRefs": evidence_refs,
                           "dispatchAuthorization": dispatch_authorization,
                           **evidence})
        return output, True
    except Exception:
        return [], False
