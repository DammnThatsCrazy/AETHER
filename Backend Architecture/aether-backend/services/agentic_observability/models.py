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
    agent_version: Optional[str] = None
    model: Optional[str] = None
    model_version: Optional[str] = None
    framework: Optional[str] = None
    framework_version: Optional[str] = None
    runtime_id: Optional[str] = None
    environment: Optional[str] = None
    autonomy_level: Optional[AutonomyLevel] = None
    owner_id: Optional[str] = None
    organization_id: Optional[str] = None


class RuntimeRef(BaseModel):
    runtime_id: Optional[str] = None
    environment: Optional[str] = None
    region: Optional[str] = None
    sdk_name: Optional[str] = None
    sdk_version: Optional[str] = None


class CorrelationRef(BaseModel):
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    task_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    connection_id: Optional[str] = None
    session_id: Optional[str] = None
    invocation_id: Optional[str] = None
    provider_request_id: Optional[str] = None
    external_object_id: Optional[str] = None
    campaign_id: Optional[str] = None
    journey_id: Optional[str] = None


class MCPObservationContext(BaseModel):
    protocol: Optional[str] = None
    protocol_version: Optional[str] = None
    transport: Optional[str] = None
    client_name: Optional[str] = None
    client_version: Optional[str] = None
    server_name: Optional[str] = None
    server_version: Optional[str] = None
    server_identity_hash: Optional[str] = None
    connection_state: Optional[str] = None
    negotiated_capabilities: list[str] = Field(default_factory=list)
    tool_catalog_revision: Optional[str] = None
    resource_catalog_revision: Optional[str] = None
    prompt_catalog_revision: Optional[str] = None
    reconnect_count: Optional[int] = None
    disconnect_reason: Optional[str] = None
    tool_name: Optional[str] = None
    tool_id: Optional[str] = None
    tool_schema_hash: Optional[str] = None
    invocation_phase: Optional[str] = None
    attempt: Optional[int] = None
    duration_ms: Optional[int] = None
    error_code: Optional[str] = None
    error_class: Optional[str] = None
    cancelled: Optional[bool] = None
    arguments_policy: Optional[str] = None
    arguments_hash: Optional[str] = None
    result_policy: Optional[str] = None
    result_hash: Optional[str] = None
    result_ref: Optional[str] = None


class AuthorizationContext(BaseModel):
    authorization_id: Optional[str] = None
    credential_ref: Optional[str] = None
    external_account_id: Optional[str] = None
    workspace_id: Optional[str] = None
    grantor_id: Optional[str] = None
    grantee_id: Optional[str] = None
    scopes: list[str] = Field(default_factory=list)
    scope_hash: Optional[str] = None
    approved_at: Optional[str] = None
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revocation_reason: Optional[str] = None
    approval_evidence_ref: Optional[str] = None


class VerificationContext(BaseModel):
    verification_status: Optional[str] = None
    verification_source: Optional[str] = None
    verification_confidence: Optional[float] = None
    verified_at: Optional[str] = None
    provider_request_id: Optional[str] = None
    external_object_id: Optional[str] = None
    evidence_ref: Optional[str] = None
    contradiction_reason: Optional[str] = None


class PrivacyContext(BaseModel):
    content_capture_mode: Optional[str] = None
    redaction_policy_id: Optional[str] = None
    privacy_class: Optional[str] = None
    retention_class: Optional[str] = None
    consent_reference: Optional[str] = None
    contains_sensitive_data: Optional[bool] = None


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
