"""Consume server-authored agent execution events for the lifecycle graph.

The public SDK does not emit agent lifecycle contracts. Only events published
by the backend agent service are eligible here; tenant, event ID, agent ID and
execution ID are required before a lifecycle projection is made.
"""

from __future__ import annotations

from shared.events.events import Event, Topic
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.agent.lifecycle_consumer")

_EXECUTION_EVENT_TYPES = {
    Topic.AGENT_EXECUTION_STARTED: "agent_task_started",
    Topic.AGENT_EXECUTION_COMPLETED: "agent_task_completed",
    Topic.AGENT_EXECUTION_FAILED: "agent_task_failed",
}


async def project_agent_execution_lifecycle(event: Event) -> None:
    """Project trusted agent execution state into canonical lifecycle objects."""
    event_type = _EXECUTION_EVENT_TYPES.get(event.topic)
    if event_type is None:
        return
    if event.source_service != "agents":
        metrics.increment(
            "agent_lifecycle_projection_deferred_total",
            labels={"reason": "untrusted_source"},
        )
        return

    payload = dict(event.payload or {})
    tenant_id = str(event.tenant_id or "").strip()
    agent_id = str(payload.get("agent_id") or "").strip()
    execution_id = str(payload.get("execution_id") or "").strip()
    if not tenant_id or not agent_id or not execution_id:
        metrics.increment(
            "agent_lifecycle_projection_skipped_total",
            labels={"reason": "missing_required_identity"},
        )
        return

    from services.agent.lifecycle_mapper import AgentLifecycleMapper

    mapped = {
        **payload,
        "agent_id": agent_id,
        "task_id": execution_id,
        "execution_id": execution_id,
        "timestamp": event.timestamp,
        "source_event_id": event.event_id,
        "source_event_type": event.topic.value,
        "evidence_status": "server_observed",
    }
    result = await AgentLifecycleMapper().handle_event(event_type, mapped, tenant_id)
    metrics.increment(
        "agent_lifecycle_projection_total",
        labels={"event_type": event_type},
    )
    logger.info(
        "agent execution lifecycle projected",
        extra={
            "tenant_id": tenant_id,
            "event_id": event.event_id,
            "event_type": event_type,
            "result_status": result.get("status"),
        },
    )
