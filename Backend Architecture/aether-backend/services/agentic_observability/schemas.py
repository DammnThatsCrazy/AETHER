"""Route-layer request/response schemas for agentic observability."""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, model_validator
from services.agentic_observability.models import (
    ObservationSource, ObservationActor, AgentRef, RuntimeRef, CorrelationRef,
    MCPObservationContext, AuthorizationContext, VerificationContext, PrivacyContext,
    ObservationObject, ObservationAction, ObservationEconomics,
    ObservationRisk, RiskLevel,
)


class AgentEventRequest(BaseModel):
    schema_version: str = "1.0"
    event_name: Optional[str] = None
    event_type: Optional[str] = None
    tenant_id: str
    observed_at: Optional[str] = None
    source: ObservationSource = Field(default_factory=ObservationSource)
    actor: ObservationActor
    agent: Optional[AgentRef] = None
    runtime: Optional[RuntimeRef] = None
    correlation: Optional[CorrelationRef] = None
    mcp: Optional[MCPObservationContext] = None
    authorization: Optional[AuthorizationContext] = None
    object: ObservationObject
    action: ObservationAction
    economics: Optional[ObservationEconomics] = None
    verification: Optional[VerificationContext] = None
    risk: Optional[ObservationRisk] = None
    privacy: Optional[PrivacyContext] = None
    raw_payload: Optional[dict] = None
    execution_by_aether: Literal[False] = False

    @model_validator(mode="after")
    def _normalize_event_type(self) -> "AgentEventRequest":
        if self.event_name and self.event_type and self.event_name != self.event_type:
            raise ValueError("event_name and event_type must match")
        canonical = self.event_name or self.event_type
        if not canonical:
            raise ValueError("event_name or event_type is required")
        self.event_name = canonical
        self.event_type = canonical
        return self


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
