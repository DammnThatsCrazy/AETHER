"""
Aether Service — Agent Teams (routes)

Worker-team registry covering the five execution phases of the agent layer:
discovery, enrichment, verification, commit, recovery.

Endpoints:
    GET    /v1/agent/teams                              List teams
    POST   /v1/agent/teams                              Create team
    GET    /v1/agent/teams/{team_id}                    Team detail (members + load)
    PATCH  /v1/agent/teams/{team_id}                    Update status / coordinator
    POST   /v1/agent/teams/{team_id}/members            Add member
    DELETE /v1/agent/teams/{team_id}/members/{agent_id} Remove member
    GET    /v1/agent/teams/{team_id}/lifecycle          List lifecycle events
    POST   /v1/agent/teams/{team_id}/lifecycle          Record lifecycle event
    GET    /v1/agent/teams/{team_id}/load               Throughput / error-rate snapshot
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store

from services.agent.teams_models import (
    TeamCreate,
    TeamLifecycleEvent,
    TeamMember,
    TeamMemberAdd,
    VALID_LIFECYCLE_EVENTS,
    VALID_TEAM_NAMES,
    VALID_TEAM_STATUSES,
)

logger = get_logger("aether.service.agent.teams")
router = APIRouter(prefix="/v1/agent/teams", tags=["Agent Teams"])

_team_store = get_store("agent_teams")
_team_lifecycle_store = get_store("agent_team_lifecycle")
_task_store = get_store("agent_tasks")


class TeamUpdate(BaseModel):
    status: str | None = None
    coordinator_agent_id: str | None = None
    metadata: dict[str, Any] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _team_key(tenant_id: str, team_id: str) -> str:
    return f"{tenant_id}:{team_id}"


async def _load_team(tenant_id: str, team_id: str) -> dict:
    record = await _team_store.get(_team_key(tenant_id, team_id))
    if not record:
        raise NotFoundError(f"Team not found: {team_id}")
    return record


async def _compute_load(tenant_id: str, team_name: str) -> dict[str, Any]:
    """Compute throughput / error-rate snapshot from agent_tasks store.

    Tasks are bucketed by worker_type. We treat the team `name` as a logical
    grouping prefix; callers pass `team_name` and we count tasks whose
    worker_type matches the team's phase. This is intentionally a thin
    aggregation — production wires this to the metrics pipeline.
    """
    tasks = await _task_store.find(tenant_id=tenant_id)
    in_team = [t for t in tasks if str(t.get("worker_type", "")).startswith(team_name)]
    completed = [t for t in in_team if t.get("status") == "completed"]
    failed = [t for t in in_team if t.get("status") == "failed"]
    total = len(in_team)
    return {
        "total_tasks": total,
        "completed": len(completed),
        "failed": len(failed),
        "in_flight": total - len(completed) - len(failed),
        "error_rate": (len(failed) / total) if total else 0.0,
    }


# ── Routes ─────────────────────────────────────────────────────────────


@router.get("")
async def list_teams(request: Request, name: str = "", status: str = ""):
    """List teams for the current tenant, optionally filtered by name/status."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")

    filters: dict[str, Any] = {"tenant_id": tenant.tenant_id}
    if name:
        filters["name"] = name
    if status:
        filters["status"] = status

    teams = await _team_store.find(**filters)
    return APIResponse(data={"teams": teams, "count": len(teams)}).to_dict()


@router.post("")
async def create_team(body: TeamCreate, request: Request):
    """Create a new team. `name` must be one of the five execution phases."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")

    if body.name not in VALID_TEAM_NAMES:
        raise BadRequestError(
            f"Invalid team name '{body.name}'. Valid: {VALID_TEAM_NAMES}"
        )

    team_id = str(uuid.uuid4())
    members = [
        TeamMember(agent_id=aid, role="worker").model_dump()
        for aid in body.member_agent_ids
    ]
    if body.coordinator_agent_id and body.coordinator_agent_id not in body.member_agent_ids:
        members.append(
            TeamMember(agent_id=body.coordinator_agent_id, role="coordinator").model_dump()
        )

    record = {
        "team_id": team_id,
        "tenant_id": tenant.tenant_id,
        "name": body.name,
        "status": "active",
        "coordinator_agent_id": body.coordinator_agent_id,
        "members": members,
        "metadata": body.metadata,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await _team_store.set(_team_key(tenant.tenant_id, team_id), record)
    metrics.increment("agent_teams_created", labels={"team_name": body.name})
    logger.info(f"Team created: id={team_id} name={body.name} tenant={tenant.tenant_id}")
    return APIResponse(data=record).to_dict()


@router.get("/{team_id}")
async def get_team(team_id: str, request: Request):
    """Return the full team record plus a load snapshot."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    record = await _load_team(tenant.tenant_id, team_id)
    record["load"] = await _compute_load(tenant.tenant_id, record["name"])
    return APIResponse(data=record).to_dict()


@router.patch("/{team_id}")
async def update_team(team_id: str, body: TeamUpdate, request: Request):
    """Update status, coordinator, or metadata."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    record = await _load_team(tenant.tenant_id, team_id)

    if body.status is not None:
        if body.status not in VALID_TEAM_STATUSES:
            raise BadRequestError(
                f"Invalid status '{body.status}'. Valid: {VALID_TEAM_STATUSES}"
            )
        record["status"] = body.status

    if body.coordinator_agent_id is not None:
        record["coordinator_agent_id"] = body.coordinator_agent_id

    if body.metadata is not None:
        record["metadata"] = {**record.get("metadata", {}), **body.metadata}

    record["updated_at"] = _now()
    await _team_store.set(_team_key(tenant.tenant_id, team_id), record)
    return APIResponse(data=record).to_dict()


@router.post("/{team_id}/members")
async def add_member(team_id: str, body: TeamMemberAdd, request: Request):
    """Add an agent to the team."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    record = await _load_team(tenant.tenant_id, team_id)

    if any(m["agent_id"] == body.agent_id for m in record["members"]):
        raise BadRequestError(f"Agent {body.agent_id} already in team {team_id}")

    member = TeamMember(agent_id=body.agent_id, role=body.role).model_dump()
    record["members"].append(member)
    if body.role == "coordinator":
        record["coordinator_agent_id"] = body.agent_id
    record["updated_at"] = _now()
    await _team_store.set(_team_key(tenant.tenant_id, team_id), record)

    await _record_lifecycle(
        tenant.tenant_id,
        team_id,
        TeamLifecycleEvent(event_type="member_joined", actor_agent_id=body.agent_id),
    )
    return APIResponse(data=record).to_dict()


@router.delete("/{team_id}/members/{agent_id}")
async def remove_member(team_id: str, agent_id: str, request: Request):
    """Remove an agent from the team."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    record = await _load_team(tenant.tenant_id, team_id)

    before = len(record["members"])
    record["members"] = [m for m in record["members"] if m["agent_id"] != agent_id]
    if before == len(record["members"]):
        raise NotFoundError(f"Agent {agent_id} not in team {team_id}")

    if record.get("coordinator_agent_id") == agent_id:
        record["coordinator_agent_id"] = None

    record["updated_at"] = _now()
    await _team_store.set(_team_key(tenant.tenant_id, team_id), record)

    await _record_lifecycle(
        tenant.tenant_id,
        team_id,
        TeamLifecycleEvent(event_type="member_left", actor_agent_id=agent_id),
    )
    return APIResponse(data=record).to_dict()


@router.get("/{team_id}/lifecycle")
async def list_lifecycle(team_id: str, request: Request, limit: int = 100):
    """Return recent lifecycle events for the team."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    await _load_team(tenant.tenant_id, team_id)  # existence check

    events = await _team_lifecycle_store.get_list(
        _team_key(tenant.tenant_id, team_id), limit=limit
    )
    return APIResponse(data={"events": events, "count": len(events)}).to_dict()


@router.post("/{team_id}/lifecycle")
async def record_lifecycle(team_id: str, body: TeamLifecycleEvent, request: Request):
    """Append a lifecycle event."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    await _load_team(tenant.tenant_id, team_id)

    if body.event_type not in VALID_LIFECYCLE_EVENTS:
        raise BadRequestError(
            f"Invalid event_type '{body.event_type}'. Valid: {VALID_LIFECYCLE_EVENTS}"
        )

    payload = await _record_lifecycle(tenant.tenant_id, team_id, body)
    return APIResponse(data=payload).to_dict()


@router.get("/{team_id}/load")
async def get_load(team_id: str, request: Request):
    """Throughput / error-rate snapshot for the team."""
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    record = await _load_team(tenant.tenant_id, team_id)
    return APIResponse(data=await _compute_load(tenant.tenant_id, record["name"])).to_dict()


async def _record_lifecycle(
    tenant_id: str, team_id: str, body: TeamLifecycleEvent
) -> dict[str, Any]:
    payload = body.model_dump()
    payload["team_id"] = team_id
    payload["tenant_id"] = tenant_id
    await _team_lifecycle_store.append_list(_team_key(tenant_id, team_id), payload)
    metrics.increment("agent_team_lifecycle_events", labels={"event": body.event_type})
    return payload
