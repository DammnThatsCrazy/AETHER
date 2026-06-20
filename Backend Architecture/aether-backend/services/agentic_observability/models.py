"""
Agentic Observability — Pydantic models.

INVARIANT: AETHER observes. AETHER does not execute.
execution_by_aether is always False. Any payload with True is rejected.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
import uuid

from pydantic import BaseModel, Field, model_validator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class ObservationProvider(str, Enum):
    ROBINHOOD = "robinhood"
    AGENTMAIL = "agentmail"
    X402 = "x402"
    MCP = "mcp"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class ActorType(str, Enum):
    HUMAN = "human"
    AGENT = "agent"
    SERVICE = "service"
    ORGANIZATION = "organization"


class AutonomyLevel(str, Enum):
    MANUAL = "manual"
    ASSISTED = "assisted"
    SEMI_AUTONOMOUS = "semi_autonomous"
    AUTONOMOUS_OBSERVED = "autonomous_observed"


class ActionStatus(str, Enum):
    OBSERVED = "observed"
    SUCCEEDED_OBSERVED = "succeeded_observed"
    FAILED_OBSERVED = "failed_observed"
    DENIED_OBSERVED = "denied_observed"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ObservationSource(BaseModel):
    provider: ObservationProvider = ObservationProvider.UNKNOWN
    provider_event_id: Optional[str] = None
    integration_id: Optional[str] = None
    webhook_id: Optional[str] = None
    sdk_name: Optional[str] = None
    sdk_version: Optional[str] = None


class ObservationActor(BaseModel):
    actor_type: ActorType
    actor_id: Optional[str] = None
    external_actor_id: Optional[str] = None


class AgentRef(BaseModel):
    agent_id: Optional[str] = None
    external_agent_id: Optional[str] = None
    model: Optional[str] = None
    framework: Optional[str] = None
    autonomy_level: Optional[AutonomyLevel] = None


class ObservationObject(BaseModel):
    object_type: str
    object_id: Optional[str] = None
    external_object_id: Optional[str] = None


class ObservationAction(BaseModel):
    name: str
    status: ActionStatus = ActionStatus.OBSERVED
    intent: Optional[str] = None
    outcome: Optional[str] = None


class ObservationEconomics(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = None
    asset: Optional[str] = None
    network: Optional[str] = None
    rail: Optional[str] = None
    direction: Optional[str] = None
    is_execution_by_aether: Literal[False] = False

    @model_validator(mode="after")
    def _enforce_no_execution(self) -> "ObservationEconomics":
        if self.is_execution_by_aether is not False:
            raise ValueError("execution_by_aether must always be False")
        return self


class ObservationRisk(BaseModel):
    risk_level: Optional[RiskLevel] = None
    reason_codes: list[str] = Field(default_factory=list)
    policy_flags: list[str] = Field(default_factory=list)
    requires_review: bool = False


class ObservationProvenance(BaseModel):
    raw_event_hash: str
    raw_payload_ref: Optional[str] = None
    normalized_by: str
    schema_version: str = "1.0"


class AgenticObservationRecord(BaseModel):
    """Canonical stored document for any agentic observation."""
    observation_id: str = Field(default_factory=_new_id)
    event_name: str
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
    received_at: str = Field(default_factory=_utc_now)
    source: ObservationSource = Field(default_factory=ObservationSource)
    actor: ObservationActor
    agent: Optional[AgentRef] = None
    object: ObservationObject
    action: ObservationAction
    economics: Optional[ObservationEconomics] = None
    risk: Optional[ObservationRisk] = None
    provenance: ObservationProvenance

    @classmethod
    def hash_payload(cls, raw: dict) -> str:
        return hashlib.sha256(
            json.dumps(raw, sort_keys=True, default=str).encode()
        ).hexdigest()


class MCPConnectionObserved(BaseModel):
    connection_id: str = Field(default_factory=_new_id)
    agent_id: Optional[str] = None
    external_agent_id: Optional[str] = None
    server_name: Optional[str] = None
    server_url: Optional[str] = None
    tools: list[str] = Field(default_factory=list)
    connected_at: Optional[str] = None
    disconnected_at: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
    execution_by_aether: Literal[False] = False


class AgentToolInvocationObserved(BaseModel):
    invocation_id: str = Field(default_factory=_new_id)
    tool_name: str
    agent_id: Optional[str] = None
    duration_ms: Optional[int] = None
    status: ActionStatus = ActionStatus.OBSERVED
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
    execution_by_aether: Literal[False] = False


class AgentRiskSignalRecord(BaseModel):
    signal_id: str = Field(default_factory=_new_id)
    agent_id: Optional[str] = None
    risk_level: RiskLevel
    reason_codes: list[str] = Field(default_factory=list)
    policy_flags: list[str] = Field(default_factory=list)
    detected_at: str = Field(default_factory=_utc_now)
    tenant_id: str
