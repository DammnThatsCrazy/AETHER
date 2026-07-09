"""
Aether Service — Profile 360 External Deployment Activity

Summarizes external agent deployment activity for an agent entity from the
deployment registry (External Agent Telemetry Plane V1). Read-only composition
over AgentDeploymentRepository — no new persistence, tenant-scoped throughout.
"""

from __future__ import annotations

from typing import Any

from services.agent.deployments import get_deployment_repository


async def get_external_deployment_activity(tenant_id: str, entity_id: str) -> dict[str, Any]:
    """Deployment activity summary for deployments operated by an agent entity.

    Returns counts by status, the set of external platforms, the most recent
    last_seen_at, and a per-deployment summary (no tenant metadata payloads).
    """
    deployments = await get_deployment_repository().list(tenant_id, agent_id=entity_id)

    status_counts: dict[str, int] = {}
    platforms: set[str] = set()
    last_seen_at: str | None = None
    rows: list[dict[str, Any]] = []
    for record in deployments:
        status = record.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        platform = record.get("external_platform")
        if platform:
            platforms.add(platform)
        seen = record.get("last_seen_at")
        if seen and (last_seen_at is None or seen > last_seen_at):
            last_seen_at = seen
        rows.append({
            "id": record.get("id"),
            "display_name": record.get("display_name"),
            "external_platform": platform,
            "environment": record.get("environment"),
            "status": status,
            "last_seen_at": seen,
            "last_event_at": record.get("last_event_at"),
            "event_count_24h": record.get("event_count_24h", 0),
            "health_score": record.get("health_score"),
        })

    return {
        "entity_id": entity_id,
        "deployments": rows,
        "count": len(rows),
        "platforms": sorted(platforms),
        "status_counts": status_counts,
        "last_seen_at": last_seen_at,
    }
