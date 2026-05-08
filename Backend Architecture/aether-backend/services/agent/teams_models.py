"""
Aether Service — Agent Teams (models)

Worker-team registry data shapes. Teams group agents into the five execution
phases the workers/teams package implements: discovery, enrichment,
verification, commit, recovery.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


VALID_TEAM_NAMES = ["discovery", "enrichment", "verification", "commit", "recovery"]
VALID_TEAM_STATUSES = ["active", "paused", "draining", "stopped"]
VALID_LIFECYCLE_EVENTS = [
    "started", "paused", "resumed", "drained", "stopped",
    "member_joined", "member_left", "coordinator_changed",
]


class TeamMember(BaseModel):
    agent_id: str
    role: str = Field(default="worker", pattern="^(coordinator|worker|observer)$")
    joined_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class TeamCreate(BaseModel):
    name: str = Field(..., description="One of discovery|enrichment|verification|commit|recovery")
    coordinator_agent_id: Optional[str] = None
    member_agent_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TeamMemberAdd(BaseModel):
    agent_id: str
    role: str = Field(default="worker", pattern="^(coordinator|worker|observer)$")


class TeamLifecycleEvent(BaseModel):
    event_type: str = Field(..., description="One of " + "|".join(VALID_LIFECYCLE_EVENTS))
    actor_agent_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class TeamRecord(BaseModel):
    team_id: str
    tenant_id: str
    name: str
    status: str
    coordinator_agent_id: Optional[str]
    members: list[TeamMember]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
