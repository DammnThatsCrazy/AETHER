"""Server-validated associations between agent requests and owning records.

An accepted association is a caller-reported link to an Aether lifecycle row.
It does not prove that a runtime dispatched an action or an effect occurred.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _recorded_delegation_decision(row: dict[str, Any], created: datetime,
                                  as_of: datetime) -> dict[str, Any] | None:
    """Return only the execution's time-scoped recorded decision, not a new authorization."""
    from shared.temporal.instant import parse_instant_strict

    policy = row.get("policy_log")
    decision = policy.get("delegation_check") if isinstance(policy, dict) else None
    if (not isinstance(decision, dict) or not isinstance(decision.get("allowed"), bool)
            or not row.get("tenant_id") or policy.get("delegation_check_tenant_id") != row["tenant_id"]):
        return None
    try:
        evaluated = parse_instant_strict(decision.get("evaluated_at"))
    except (TypeError, ValueError):
        return None
    delegation_id = decision.get("delegation_id")
    if (
        evaluated > created or evaluated > as_of
        or delegation_id != row.get("delegation_id")
        or (decision["allowed"] and (not isinstance(delegation_id, str) or not delegation_id.strip()))
        or (not decision["allowed"] and row.get("status") != "revoked")
        or (decision["allowed"] and row.get("status") == "revoked")
    ):
        return None
    return {
        "decision": "allow" if decision["allowed"] else "deny",
        "evaluatedAt": evaluated.isoformat(),
        "delegationId": delegation_id,
        "semantics": "recorded_request_time_decision_not_current_authorization",
        "evidenceRef": {"id": row["execution_id"], "type": "event", "source": "agent_executions",
                        "observedAt": created.isoformat()},
    }


def action_association_read_authorized(request: Any, context: Any, *, surface: str, slot: str, consumer: str) -> bool:
    """Require the frame runtime's exact slot-scoped authorization."""
    return bool(
        context.tenantId == request.tenantId
        and context.projectionId == consumer
        and any(
            item.tenantId == request.tenantId
            and item.sourceSurfaceId == surface
            and item.sourceSubject == request.subject
            and item.sourceSlotId == slot
            and item.consumerProjectionId == consumer
            and item.targetProjectionId == "agent360"
            and item.capabilityKey == "agent360.read"
            and item.policyState == "allowed"
            and bool(item.policyIds)
            and bool(item.policyEvaluatedAt)
            for item in context.experience360ReadAuthorizations
        )
    )


class JourneyActionReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    journey_id: str = Field(min_length=1, max_length=256)
    journey_version_id: str = Field(min_length=1, max_length=256)
    record_id: str = Field(min_length=8, max_length=128)


class RiskActionReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    record_id: str = Field(min_length=1, max_length=256)
    subject_kind: str = Field(min_length=1, max_length=128)
    subject_id: str = Field(min_length=1, max_length=256)


async def validate_action_association(
    *, tenant_id: str, action: str, resource: str,
    journey: JourneyActionReference | None = None,
    risk: RiskActionReference | None = None,
    journey_authority: Any = None, journey_repository: Any = None,
    risk_repository: Any = None, now: datetime | None = None,
    recommendation_id: str | None = None, action_type: str | None = None,
) -> dict[str, str] | None:
    """Resolve and validate exactly one caller reference against owning records."""
    if journey is not None and risk is not None:
        raise ValueError("only one action association may be supplied")
    if journey is None and risk is None:
        return None
    anchor = now or datetime.now(timezone.utc)
    if not tenant_id or not action or not resource or anchor.tzinfo is None:
        raise ValueError("tenant, action, resource, and current time are required")
    if journey is not None:
        from journeys.measurement.episodes.related_authorities import EpisodeJourneyAuthorityRepository
        from journeys.measurement.repositories.journey_repo import JourneyRepository

        reader = journey_authority or EpisodeJourneyAuthorityRepository()
        owner = journey_repository or JourneyRepository()
        current = await owner.get_current(tenant_id, journey.journey_id)
        if (
            not isinstance(current, dict) or current.get("tenant_id") != tenant_id
            or str(current.get("journey_id") or "") != journey.journey_id
            or str(current.get("journey_version_id") or "") != journey.journey_version_id
            or current.get("is_current") is not True or resource != journey.journey_id
        ):
            raise ValueError("exact current tenant journey version required")
        read = await reader.list_for_subject(
            tenant_id, "journey", journey.journey_id, "journey_action_intent", limit=201
        )
        if not read.available or not read.complete or len(read.records) > 200:
            raise ValueError("complete journey action intent read required")
        matches = [row for row in read.records if row.get("record_id") == journey.record_id]
        if len(matches) != 1:
            raise ValueError("exact journey action intent required")
        from journeys.measurement.episodes.related_authorities import JourneyActionIntentRecord

        record = JourneyActionIntentRecord.model_validate(matches[0])
        if (
            record.tenant_id != tenant_id or record.journey_id != journey.journey_id
            or record.journey_version_id != journey.journey_version_id
            or record.action_key != action or record.status != "proposed"
            or (recommendation_id is not None and record.recommendation_id != recommendation_id)
            or (action_type is not None and record.action_type != action_type)
            or record.occurred_at > anchor or record.recorded_at > anchor
        ):
            raise ValueError("journey intent does not match action or scope")
        return {"kind": "journey_action_intent", "record_id": record.record_id,
                "subject_id": record.journey_id, "version_id": record.journey_version_id,
                "action_key": record.action_key, "link_state": "caller_associated"}
    from intelligence.risk360.store import RiskInterventionRepository

    assert risk is not None
    record = await (risk_repository or RiskInterventionRepository()).get(tenant_id, risk.record_id)
    if (
        record is None or record.tenant_id != tenant_id or record.record_id != risk.record_id
        or record.record_kind != "decision" or record.decision_state != "approved"
        or record.subject_kind != risk.subject_kind or record.subject_id != risk.subject_id
        or record.intervention_type != action or resource != risk.subject_id
        or record.effective_at > anchor or record.recorded_at > anchor
    ):
        raise ValueError("exact approved risk intervention decision and action scope required")
    return {"kind": "risk_intervention", "record_id": record.record_id,
            "subject_id": record.subject_id, "subject_kind": record.subject_kind,
            "intervention_id": record.intervention_id, "action_key": record.intervention_type,
            "link_state": "caller_associated"}


async def read_associated_executions(
    *, tenant_id: str, kind: str, record_id: str, subject_id: str, action: str,
    recorded_at: datetime, as_of: datetime, version_id: str | None = None,
    subject_kind: str | None = None, intervention_id: str | None = None,
    repository: Any = None, limit: int = 20,
) -> tuple[list[dict[str, Any]], bool]:
    """Read bounded server lifecycle rows only for the exact association.

    Returned rows are recorded requests, not independently verified actions.
    A truncated, malformed, or unavailable read is incomplete.
    """
    from repositories.repos import AgentExecutionRepository
    from shared.temporal.instant import parse_instant_strict
    from urllib.parse import quote

    if kind not in {"journey_action_intent", "risk_intervention"} or not all(
        (tenant_id, record_id, subject_id, action)
    ):
        return [], False
    bounded = min(max(limit, 1), 20)
    try:
        rows = await (repository or AgentExecutionRepository()).find_many(
            filters={"tenant_id": tenant_id, "action_association_kind": kind,
                     "action_association_record_id": record_id},
            limit=bounded + 1,
        )
    except Exception:  # noqa: BLE001 - association failure stays unknown
        return [], False
    if not isinstance(rows, list) or len(rows) > bounded:
        return [], False
    projected = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            return [], False
        link = row.get("action_association")
        snapshot = row.get("input_snapshot")
        execution_id = row.get("execution_id")
        try:
            created = parse_instant_strict(row.get("created_at"))
        except (TypeError, ValueError):
            return [], False
        if (
            row.get("tenant_id") != tenant_id or not isinstance(link, dict)
            or not isinstance(snapshot, dict) or not isinstance(execution_id, str)
            or not execution_id.strip() or execution_id in seen
            or not isinstance(row.get("agent_id"), str) or not row["agent_id"].strip()
            or row.get("status") not in {"running", "revoked", "failed", "succeeded", "completed"}
            or row.get("id") != execution_id
            or row.get("action_association_kind") != kind
            or row.get("action_association_record_id") != record_id
            or link.get("kind") != kind or link.get("record_id") != record_id
            or link.get("subject_id") != subject_id or link.get("action_key") != action
            or link.get("link_state") != "caller_associated"
            or snapshot.get("action") != action or snapshot.get("resource") != subject_id
            or created < recorded_at
            or (kind == "journey_action_intent" and link.get("version_id") != version_id)
            or (kind == "risk_intervention" and (
                link.get("subject_kind") != subject_kind or link.get("intervention_id") != intervention_id
            ))
        ):
            return [], False
        if created > as_of:
            continue
        seen.add(execution_id)
        projected.append({
            "executionId": execution_id,
            "recordedAt": created.isoformat(), "associationState": "caller_associated",
            "recordedDelegationDecision": _recorded_delegation_decision(row, created, as_of),
            "dispatchState": "not_established", "externalEffectState": "unknown",
            "evidenceRef": {"id": execution_id, "type": "event", "source": "agent_executions",
                            "observedAt": created.isoformat(),
                            "uri": f"store://agent_executions/{quote(execution_id, safe='')}"},
        })
    return projected, True
