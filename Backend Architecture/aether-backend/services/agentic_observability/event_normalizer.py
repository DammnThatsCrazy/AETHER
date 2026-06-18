"""Normalizes provider-specific payloads into AgenticObservationRecord."""
from __future__ import annotations

from typing import Any
from services.agentic_observability.models import (
    AgenticObservationRecord, ObservationSource, ObservationActor,
    ObservationObject, ObservationAction, ObservationProvenance,
    ObservationEconomics, ActorType, ActionStatus, ObservationProvider,
)


_NORMALIZER_ID = "agentic_observability.event_normalizer"


def normalize(raw: dict, provider: str, tenant_id: str, event_name: str) -> AgenticObservationRecord:
    """Normalize a provider-specific payload into a canonical AgenticObservationRecord."""
    raw_hash = AgenticObservationRecord.hash_payload(raw)

    source = ObservationSource(
        provider=_to_provider(provider),
        provider_event_id=raw.get("event_id") or raw.get("id"),
        integration_id=raw.get("integration_id"),
        webhook_id=raw.get("webhook_id"),
    )

    actor_data = raw.get("actor", {})
    actor = ObservationActor(
        actor_type=ActorType(actor_data.get("actor_type", "agent")),
        actor_id=actor_data.get("actor_id") or raw.get("agent_id"),
        external_actor_id=actor_data.get("external_actor_id"),
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
    if "economics" in raw:
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
        schema_version="1.0",
    )

    return AgenticObservationRecord(
        event_name=event_name,
        tenant_id=tenant_id,
        observed_at=raw.get("observed_at") or raw.get("timestamp"),
        source=source,
        actor=actor,
        object=obj,
        action=action,
        economics=economics,
        provenance=provenance,
    )


def _to_provider(p: str) -> ObservationProvider:
    try:
        return ObservationProvider(p.lower())
    except ValueError:
        return ObservationProvider.UNKNOWN
