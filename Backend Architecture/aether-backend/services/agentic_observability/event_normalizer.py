"""Normalizes provider-specific payloads into AgenticObservationRecord."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from services.agentic_observability.models import (
    AgenticObservationRecord, ObservationSource, ObservationActor, AgentRef,
    ObservationObject, ObservationAction, ObservationProvenance,
    ObservationEconomics, ObservationRisk, ActorType, ActionStatus,
    AutonomyLevel, ObservationProvider,
)


_NORMALIZER_ID = "agentic_observability.event_normalizer"


def normalize(raw: dict, provider: str, tenant_id: str, event_name: str) -> AgenticObservationRecord:
    """Normalize a provider-specific payload into a canonical AgenticObservationRecord."""
    raw_hash = AgenticObservationRecord.hash_payload(raw)

    # source: read nested source dict first, fall back to top-level keys
    source_data = raw.get("source") or {}
    source = ObservationSource(
        provider=_to_provider(source_data.get("provider") or provider),
        provider_event_id=source_data.get("provider_event_id") or raw.get("event_id") or raw.get("id"),
        integration_id=source_data.get("integration_id") or raw.get("integration_id"),
        webhook_id=source_data.get("webhook_id") or raw.get("webhook_id"),
    )

    actor_data = raw.get("actor") or {}
    actor = ObservationActor(
        actor_type=ActorType(actor_data.get("actor_type", "agent")),
        actor_id=actor_data.get("actor_id") or raw.get("agent_id"),
        external_actor_id=actor_data.get("external_actor_id"),
    )

    # agent metadata: carry model/framework/autonomy_level into stored record
    agent: Any = None
    agent_data = raw.get("agent") or {}
    if agent_data:
        autonomy_raw = agent_data.get("autonomy_level")
        try:
            autonomy = AutonomyLevel(autonomy_raw) if autonomy_raw else None
        except ValueError:
            autonomy = None
        agent = AgentRef(
            agent_id=agent_data.get("agent_id"),
            external_agent_id=agent_data.get("external_agent_id"),
            agent_version=agent_data.get("agent_version"),
            model=agent_data.get("model"),
            model_version=agent_data.get("model_version"),
            framework=agent_data.get("framework"),
            framework_version=agent_data.get("framework_version"),
            runtime_id=agent_data.get("runtime_id") or (raw.get("runtime") or {}).get("runtime_id"),
            environment=agent_data.get("environment") or (raw.get("runtime") or {}).get("environment"),
            autonomy_level=autonomy,
            owner_id=agent_data.get("owner_id"),
            organization_id=agent_data.get("organization_id"),
        )

    obj_data = raw.get("object", {})
    obj = ObservationObject(
        object_type=obj_data.get("object_type", "resource"),
        object_id=obj_data.get("object_id"),
        external_object_id=obj_data.get("external_object_id"),
    )

    action_data = raw.get("action", {})
    action = ObservationAction(
        name=action_data.get("name", event_name),
        status=ActionStatus(action_data.get("status", "observed")),
        intent=action_data.get("intent"),
        outcome=action_data.get("outcome"),
    )

    economics = None
    if "economics" in raw and raw["economics"]:
        econ = raw["economics"]
        if econ.get("is_execution_by_aether") is True:
            raise ValueError("execution_by_aether must be False")
        economics = ObservationEconomics(
            amount=econ.get("amount"),
            currency=econ.get("currency"),
            asset=econ.get("asset"),
            network=econ.get("network"),
            rail=econ.get("rail"),
            direction=econ.get("direction"),
            is_execution_by_aether=False,
        )

    provenance = ObservationProvenance(
        raw_event_hash=raw_hash,
        normalized_by=_NORMALIZER_ID,
        schema_version=str(raw.get("schema_version") or "1.0"),
    )

    caller_risk = raw.get("risk")
    risk: Any = None
    if caller_risk and isinstance(caller_risk, dict):
        risk = ObservationRisk(
            risk_level=caller_risk.get("risk_level"),
            reason_codes=caller_risk.get("reason_codes", []),
            policy_flags=caller_risk.get("policy_flags", []),
            requires_review=caller_risk.get("requires_review", False),
        )

    _now = datetime.now(timezone.utc).isoformat()
    return AgenticObservationRecord(
        event_name=event_name,
        tenant_id=tenant_id,
        observed_at=raw.get("observed_at") or raw.get("timestamp") or _now,
        source=source,
        actor=actor,
        agent=agent,
        runtime=raw.get("runtime"),
        correlation=raw.get("correlation"),
        mcp=raw.get("mcp"),
        authorization=raw.get("authorization"),
        object=obj,
        action=action,
        economics=economics,
        verification=raw.get("verification"),
        risk=risk,
        privacy=raw.get("privacy"),
        provenance=provenance,
    )


def _to_provider(p: str) -> ObservationProvider:
    try:
        return ObservationProvider(p.lower())
    except ValueError:
        return ObservationProvider.UNKNOWN
