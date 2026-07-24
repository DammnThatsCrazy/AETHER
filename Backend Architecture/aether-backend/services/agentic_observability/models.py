"""
Agentic Observability — Pydantic models.

INVARIANT: AETHER observes. AETHER does not execute.
execution_by_aether is always False. Any payload with True is rejected.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Literal, Optional
import uuid

from pydantic import BaseModel, Field, field_validator, model_validator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decimal_str_from_provider(value: Any, field_name: str) -> Optional[str]:
    """Parse a provider money value without accepting binary floating point.

    Mirrors ``services.derivatives.models.decimal_from_provider``: accepts
    ``str`` / ``int`` / ``Decimal`` and REJECTS ``float`` (binary floats lose
    precision on money). Returns the canonical decimal STRING (or ``None``) so
    the value round-trips through JSON without ever becoming a binary float.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass — never a money value
        raise ValueError(f"{field_name} must not be a boolean")
    if isinstance(value, float):
        raise ValueError(f"{field_name} must not be a binary float; send a decimal string")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, int):
        return str(Decimal(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field_name} is empty")
        try:
            return str(Decimal(stripped))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name} is not a valid decimal: {stripped!r}") from exc
    raise ValueError(f"{field_name} has unsupported type {type(value).__name__}")


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


class RuntimeRef(BaseModel):
    runtime_id: Optional[str] = None
    environment: Optional[str] = None
    instance_id: Optional[str] = None


class CorrelationRef(BaseModel):
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    session_id: Optional[str] = None
    parent_observation_id: Optional[str] = None


class MCPObservationContext(BaseModel):
    server_name: Optional[str] = None
    server_url: Optional[str] = None
    tool_name: Optional[str] = None
    protocol_version: Optional[str] = None


class AuthorizationContext(BaseModel):
    grant_id: Optional[str] = None
    scope: list[str] = Field(default_factory=list)
    delegated_by: Optional[str] = None
    expires_at: Optional[str] = None


class VerificationContext(BaseModel):
    verified_by: Optional[str] = None
    verification_method: Optional[str] = None
    verification_status: Optional[str] = None
    verified_at: Optional[str] = None


class PrivacyContext(BaseModel):
    privacy_class: str = "behavioral"
    consent_snapshot_id: Optional[str] = None
    dsr_applicable: bool = False


class AgentRef(BaseModel):
    agent_id: Optional[str] = None
    external_agent_id: Optional[str] = None
    model: Optional[str] = None
    framework: Optional[str] = None
    autonomy_level: Optional[AutonomyLevel] = None
    agent_version: Optional[str] = None
    model_version: Optional[str] = None
    framework_version: Optional[str] = None
    runtime_id: Optional[str] = None
    environment: Optional[str] = None
    owner_id: Optional[str] = None
    organization_id: Optional[str] = None


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
    # Decimal-safe money: accepts str/int/Decimal, rejects binary float, and is
    # stored/serialized as a canonical decimal STRING (never a binary float).
    amount: Optional[str] = None
    currency: Optional[str] = None
    asset: Optional[str] = None
    network: Optional[str] = None
    rail: Optional[str] = None
    direction: Optional[str] = None
    is_execution_by_aether: Literal[False] = False

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, value: Any) -> Optional[str]:
        return decimal_str_from_provider(value, "economics.amount")

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
    """Canonical stored document for any agentic observation (Contract v2)."""
    observation_id: str = Field(default_factory=_new_id)
    event_name: str
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
    received_at: str = Field(default_factory=_utc_now)
    source: ObservationSource = Field(default_factory=ObservationSource)
    actor: ObservationActor
    agent: Optional[AgentRef] = None
    # External Agent Telemetry Plane V1: registry deployment this observation
    # was emitted from (additive; optional).
    deployment_id: Optional[str] = None
    object: ObservationObject
    action: ObservationAction
    economics: Optional[ObservationEconomics] = None
    risk: Optional[ObservationRisk] = None
    provenance: ObservationProvenance
    runtime: Optional[RuntimeRef] = None
    correlation: Optional[CorrelationRef] = None
    mcp: Optional[MCPObservationContext] = None
    authorization: Optional[AuthorizationContext] = None
    verification: Optional[VerificationContext] = None
    privacy: Optional[PrivacyContext] = None

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
