"""Graph ↔ Suggestion adapter."""

from __future__ import annotations

from typing import Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.suggestions.models import (
    SuggestionClass,
    SuggestionCreate,
    SuggestionSource,
    SuggestionSubject,
)

logger = get_logger("aether.suggestions.adapters.graph")

_GRAPH_EVENT_MAP: dict[str, dict] = {
    "identity_merge_candidate": {
        "suggestion_class": SuggestionClass.IDENTITY,
        "title": "Identity merge candidate detected",
        "confidence": 0.85,
        "risk": 0.65,
        "urgency": 0.70,
        "reversible": False,
        "requires_approval": True,
    },
    "graph_health_degradation": {
        "suggestion_class": SuggestionClass.GRAPH_HEALTH,
        "title": "Graph health degradation detected",
        "confidence": 0.80,
        "risk": 0.50,
        "urgency": 0.60,
        "reversible": True,
        "requires_approval": False,
    },
    "anomalous_cluster_growth": {
        "suggestion_class": SuggestionClass.GRAPH_HEALTH,
        "title": "Anomalous cluster growth detected",
        "confidence": 0.75,
        "risk": 0.55,
        "urgency": 0.65,
        "reversible": True,
        "requires_approval": False,
    },
}


def create_suggestion_from_graph_event(
    event_type: str,
    entity: dict,
    tenant_id: str,
) -> Optional[SuggestionCreate]:
    """Map a graph intelligence event to a SuggestionCreate."""
    params = _GRAPH_EVENT_MAP.get(event_type)
    if params is None:
        logger.debug(f"No suggestion mapping for graph event type {event_type!r}")
        return None

    entity_id = entity.get("id") or entity.get("entity_id") or "unknown"
    event_id = entity.get("event_id") or f"{event_type}:{entity_id}"

    return SuggestionCreate(
        tenant_id=tenant_id,
        subject=SuggestionSubject(
            kind="graph",
            id=entity_id,
            display_name=entity.get("display_name") or entity.get("label"),
        ),
        source=SuggestionSource.GRAPH,
        source_ref={"service": "graph", "id": event_id},
        suggestion_class=params["suggestion_class"],
        title=params["title"],
        summary=f"{params['title']} for entity {entity_id[:24]!r}.",
        what=entity.get("description") or f"Graph event {event_type!r} detected.",
        why="The graph intelligence layer detected an anomalous pattern requiring review.",
        impact="Graph health and identity integrity may be affected.",
        recommended_action="Review the entity graph and validate the flagged relationship.",
        confidence_score=params["confidence"],
        urgency_score=params["urgency"],
        risk_score=params["risk"],
        reversible=params.get("reversible", True),
        evidence=[
            {
                "id": event_id,
                "type": "event",
                "source": "graph",
                "observedAt": entity.get("detected_at") or utc_now().isoformat(),
                "confidence": params["confidence"],
            }
        ],
        lineage_event_ids=[event_id] if event_id else [],
    )
