"""
CIS Telemetry Consumer — Kafka → ClickHouse bridge.

Subscribes to all CIS Kafka topics and writes events to the appropriate
ClickHouse tables. Also pushes events to the CISStreamHub for real-time
WebSocket delivery to Kyber operators.

Pattern mirrors services/profile360_workers (additive subscription model).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from shared.events.events import Event, EventConsumer, Topic
from shared.logger.logger import get_logger

if TYPE_CHECKING:
    from shared.cis.clickhouse import ClickHouseClient
    from services.cis.hub import CISStreamHub

logger = get_logger("aether.cis.telemetry_consumer")


# ─────────────────────────────────────────────────────────────────────────────
# Topic → ClickHouse table routing
# ─────────────────────────────────────────────────────────────────────────────

_TOPIC_TABLE_MAP: dict[str, str] = {
    Topic.CIS_GRAPH_MUTATION_CREATED.value:           "cis_mutation_analytics",
    Topic.CIS_GRAPH_MUTATION_ACCEPTED.value:          "cis_mutation_analytics",
    Topic.CIS_GRAPH_MUTATION_REJECTED.value:          "cis_mutation_analytics",
    Topic.CIS_GRAPH_MUTATION_QUARANTINED.value:       "cis_mutation_analytics",
    Topic.CIS_RETRIEVAL_EXECUTED.value:               "cis_retrieval_traces",
    Topic.CIS_RETRIEVAL_CONTEXT_SELECTED.value:       "cis_retrieval_traces",
    Topic.CIS_RETRIEVAL_INSTABILITY_DETECTED.value:   "cis_retrieval_traces",
    Topic.CIS_RETRIEVAL_CONTAMINATION_DETECTED.value: "cis_retrieval_traces",
    Topic.CIS_GENERATION_STARTED.value:               "cis_generation_telemetry",
    Topic.CIS_GENERATION_COMPLETED.value:             "cis_generation_telemetry",
    Topic.CIS_GENERATION_CLAIM_EXTRACTED.value:       "cis_generation_telemetry",
    Topic.CIS_GENERATION_UNGROUNDED_DETECTED.value:   "cis_generation_telemetry",
    Topic.CIS_SEMANTIC_DRIFT_DETECTED.value:          "cis_semantic_drift_metrics",
    Topic.CIS_SEMANTIC_CLUSTER_INSTABILITY.value:     "cis_semantic_drift_metrics",
    Topic.CIS_SEMANTIC_EMBEDDING_DEFORMATION.value:   "cis_semantic_drift_metrics",
    Topic.CIS_REASONING_CHAIN_CREATED.value:          "cis_reasoning_chains",
    Topic.CIS_REASONING_CONTRADICTION_DETECTED.value: "cis_reasoning_chains",
    Topic.CIS_REASONING_RECURSION_DETECTED.value:     "cis_reasoning_chains",
    Topic.CIS_QUARANTINE_INITIATED.value:             "cis_mutation_analytics",
    Topic.CIS_QUARANTINE_RELEASED.value:              "cis_mutation_analytics",
    Topic.CIS_QUARANTINE_ESCALATED.value:             "cis_mutation_analytics",
}

_CIS_TOPICS = [
    Topic.CIS_GRAPH_MUTATION_CREATED,
    Topic.CIS_GRAPH_MUTATION_ACCEPTED,
    Topic.CIS_GRAPH_MUTATION_REJECTED,
    Topic.CIS_GRAPH_MUTATION_QUARANTINED,
    Topic.CIS_RETRIEVAL_EXECUTED,
    Topic.CIS_RETRIEVAL_CONTEXT_SELECTED,
    Topic.CIS_RETRIEVAL_INSTABILITY_DETECTED,
    Topic.CIS_RETRIEVAL_CONTAMINATION_DETECTED,
    Topic.CIS_GENERATION_STARTED,
    Topic.CIS_GENERATION_COMPLETED,
    Topic.CIS_GENERATION_CLAIM_EXTRACTED,
    Topic.CIS_GENERATION_UNGROUNDED_DETECTED,
    Topic.CIS_SEMANTIC_DRIFT_DETECTED,
    Topic.CIS_SEMANTIC_CLUSTER_INSTABILITY,
    Topic.CIS_SEMANTIC_EMBEDDING_DEFORMATION,
    Topic.CIS_REASONING_CHAIN_CREATED,
    Topic.CIS_REASONING_CONTRADICTION_DETECTED,
    Topic.CIS_REASONING_RECURSION_DETECTED,
    Topic.CIS_QUARANTINE_INITIATED,
    Topic.CIS_QUARANTINE_RELEASED,
    Topic.CIS_QUARANTINE_ESCALATED,
]


# ─────────────────────────────────────────────────────────────────────────────
# Row builders per table
# ─────────────────────────────────────────────────────────────────────────────

def _build_mutation_analytics_row(event: Event) -> dict[str, Any]:
    p = event.payload
    return {
        "event_id": event.event_id,
        "tenant_id": event.tenant_id,
        "mutation_id": p.get("mutation_id", ""),
        "timestamp": event.timestamp,
        "mutation_class": int(p.get("mutation_class", 1)),
        "risk_score": float(p.get("risk_score", 0.0)),
        "risk_band": p.get("risk_band", "allow"),
        "agent_id": p.get("agent_id", ""),
        "entity_id": p.get("entity_id", ""),
        "entity_type": p.get("entity_type", ""),
        "action": event.topic.value.split(".")[-1],
        "latency_ms": float(p.get("latency_ms", 0.0)),
        "source_service": event.source_service,
    }


def _optional_float(value: Any) -> Optional[float]:
    """Coerce to float, preserving ``None`` (unknown) instead of fabricating 0.0."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> Optional[int]:
    """Coerce to int, preserving ``None`` (unknown) instead of fabricating 0/1."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_retrieval_traces_row(event: Event) -> dict[str, Any]:
    p = event.payload
    return {
        "event_id": event.event_id,
        "tenant_id": event.tenant_id,
        "timestamp": event.timestamp,
        "query_hash": p.get("query_hash", ""),
        "model_name": p.get("model_name", ""),
        "retrieved_node_ids": p.get("retrieved_node_ids", []),
        "embedding_model": p.get("embedding_model", ""),
        "reasoning_trace": p.get("reasoning_trace", ""),
        "citations": p.get("citations", []),
        # Honest telemetry: an unknown model confidence / grounding signal stays
        # NULL end-to-end. Never coerce absence to 0.0 or 1 — that would
        # re-manufacture the exact claim the ml-serving layer took care to drop.
        "confidence_score": _optional_float(
            p["confidence_score"] if "confidence_score" in p else p.get("confidence")
        ),
        "generation_hash": p.get("generation_hash", ""),
        "latency_ms": float(p.get("latency_ms", 0.0)),
        "grounded": _optional_int(p.get("grounded")),
        "synthetic_ratio": float(p.get("synthetic_ratio", 0.0)),
        "source_service": event.source_service,
    }


def _build_generation_telemetry_row(event: Event) -> dict[str, Any]:
    p = event.payload
    claim_count = int(p.get("claim_count", 0))
    grounded = int(p.get("grounded_claims", claim_count))
    ungrounded = int(p.get("ungrounded_claims", 0))
    ratio = grounded / max(1, claim_count)
    return {
        "event_id": event.event_id,
        "tenant_id": event.tenant_id,
        "timestamp": event.timestamp,
        "generation_id": p.get("generation_id", event.event_id),
        "model_name": p.get("model_name", ""),
        "claim_count": claim_count,
        "grounded_claims": grounded,
        "ungrounded_claims": ungrounded,
        "grounding_ratio": float(ratio),
        "confidence_curve": p.get("confidence_curve", []),
        "generation_hash": p.get("generation_hash", ""),
        "latency_ms": float(p.get("latency_ms", 0.0)),
        "source_service": event.source_service,
    }


def _build_semantic_drift_row(event: Event) -> dict[str, Any]:
    p = event.payload
    return {
        "event_id": event.event_id,
        "tenant_id": event.tenant_id,
        "cluster_id": p.get("cluster_id", "default"),
        "timestamp": event.timestamp,
        "centroid_migration": float(p.get("centroid_migration", 0.0)),
        "neighborhood_instability": float(p.get("neighborhood_instability", 0.0)),
        "semantic_radius": float(p.get("semantic_radius", 0.0)),
        "graph_entropy_delta": float(p.get("graph_entropy_delta", 0.0)),
        "composite_drift_score": float(p.get("composite_drift_score", 0.0)),
        "triggered_alert": int(p.get("triggered_alert", 0)),
        "node_count": int(p.get("node_count", 0)),
        "source_service": event.source_service,
    }


def _build_reasoning_chain_row(event: Event) -> dict[str, Any]:
    p = event.payload
    return {
        "event_id": event.event_id,
        "tenant_id": event.tenant_id,
        "timestamp": event.timestamp,
        "chain_id": p.get("chain_id", event.event_id),
        "generation_id": p.get("generation_id", ""),
        "steps": p.get("steps", []),
        "step_count": int(p.get("step_count", len(p.get("steps", [])))),
        "contradiction_detected": int(p.get("contradiction_detected", 0)),
        "recursion_detected": int(p.get("recursion_detected", 0)),
        "recursion_depth": int(p.get("recursion_depth", 0)),
        "confidence_start": float(p.get("confidence_start", 0.0)),
        "confidence_end": float(p.get("confidence_end", 0.0)),
        "confidence_inflation": float(p.get("confidence_inflation", 0.0)),
        "agent_id": p.get("agent_id", ""),
        "source_service": event.source_service,
    }


_TABLE_BUILDERS = {
    "cis_mutation_analytics":    _build_mutation_analytics_row,
    "cis_retrieval_traces":      _build_retrieval_traces_row,
    "cis_generation_telemetry":  _build_generation_telemetry_row,
    "cis_semantic_drift_metrics": _build_semantic_drift_row,
    "cis_reasoning_chains":      _build_reasoning_chain_row,
}


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry worker
# ─────────────────────────────────────────────────────────────────────────────

class CISTelemetryWorker:
    def __init__(self, ch_client: "ClickHouseClient", hub: "CISStreamHub") -> None:
        self._ch = ch_client
        self._hub = hub

    async def handle(self, event: Event) -> None:
        table = _TOPIC_TABLE_MAP.get(event.topic.value)
        if table is None:
            return

        builder = _TABLE_BUILDERS.get(table)
        if builder is None:
            return

        try:
            row = builder(event)
            await self._ch.insert(table, [row])
        except Exception as e:
            logger.error(f"CISTelemetryWorker insert failed topic={event.topic.value}: {e}")

        # Broadcast to WebSocket hub (best-effort)
        try:
            await self._hub.broadcast(event.tenant_id, {
                "topic": event.topic.value,
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "payload": event.payload,
            })
        except Exception:
            pass


def attach_cis_telemetry_workers(
    consumer: EventConsumer,
    ch_client: "ClickHouseClient",
    hub: "CISStreamHub",
) -> None:
    """
    Wire CIS telemetry consumer to the shared EventConsumer.
    Mirrors attach_profile360_workers() signature exactly.
    """
    worker = CISTelemetryWorker(ch_client, hub)
    for topic in _CIS_TOPICS:
        consumer.subscribe(topic, worker.handle)
    logger.info(f"CIS telemetry workers attached ({len(_CIS_TOPICS)} topics)")
