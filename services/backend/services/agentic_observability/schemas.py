"""Route-layer request/response schemas for agentic observability."""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
from services.agentic_observability.models import (
    ObservationSource, ObservationActor, AgentRef,
    ObservationObject, ObservationAction, ObservationEconomics,
    ObservationRisk, RiskLevel,
)


class AgentEventRequest(BaseModel):
    schema_version: str = "1.0"
    event_name: str
    tenant_id: str
    observed_at: Optional[str] = None
    source: ObservationSource = Field(default_factory=ObservationSource)
    actor: ObservationActor
    agent: Optional[AgentRef] = None
    object: ObservationObject
    action: ObservationAction
    economics: Optional[ObservationEconomics] = None
    risk: Optional[ObservationRisk] = None
    raw_payload: Optional[dict] = None
    execution_by_aether: Literal[False] = False


class AgentAccountRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    agent_id: Optional[str] = None
    external_account_id: str
    provider: str
    account_type: Optional[str] = None
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class AgentToolRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    tool_name: str
    agent_id: Optional[str] = None
    duration_ms: Optional[int] = None
    status: str = "observed"
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class AgentMCPRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    agent_id: Optional[str] = None
    server_name: Optional[str] = None
    server_url: Optional[str] = None
    tools: list[str] = Field(default_factory=list)
    connected_at: Optional[str] = None
    execution_by_aether: Literal[False] = False


class AgentRiskSignalRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    agent_id: Optional[str] = None
    risk_level: RiskLevel
    reason_codes: list[str] = Field(default_factory=list)
    policy_flags: list[str] = Field(default_factory=list)
    execution_by_aether: Literal[False] = False


class ObservationResponse(BaseModel):
    observation_id: str
    received_at: str
    graph_mutations_queued: int = 0
    tenant_id: str
    graph_mutations_built: int = 0
    graph_mutations_persisted: int = 0
    graph_projection_status: str = "not_applicable"
