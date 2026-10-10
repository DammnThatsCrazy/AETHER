"""Customer onboarding and implementation lifecycle contracts."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TenantActivationStage(str, Enum):
    prospect = "prospect"
    signed = "signed"
    tenant_created = "tenant_created"
    sdk_pending = "sdk_pending"
    sdk_live = "sdk_live"
    event_mapping_in_progress = "event_mapping_in_progress"
    graph_building = "graph_building"
    graph_active = "graph_active"
    recommendations_enabled = "recommendations_enabled"
    playbooks_configured = "playbooks_configured"
    integrations_connected = "integrations_connected"
    outcomes_capturing = "outcomes_capturing"
    value_proven = "value_proven"
    expansion_ready = "expansion_ready"


class ImplementationStatus(str, Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    blocked = "blocked"
    live = "live"
    value_proven = "value_proven"
    expansion_ready = "expansion_ready"


class ImplementationStepCategory(str, Enum):
    contract = "contract"
    tenant_setup = "tenant_setup"
    sdk = "sdk"
    events = "events"
    identity = "identity"
    graph = "graph"
    intelligence = "intelligence"
    playbooks = "playbooks"
    integrations = "integrations"
    outcomes = "outcomes"
    training = "training"
    expansion = "expansion"


class ImplementationStepStatus(str, Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    blocked = "blocked"
    completed = "completed"
    skipped = "skipped"


class ImplementationOwnerType(str, Enum):
    olympus = "olympus"
    tenant = "tenant"
    shared = "shared"


class BlockerSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class BlockerStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    waived = "waived"


class CustomerSuccessTriggerType(str, Enum):
    sdk_stalled = "sdk_stalled"
    event_mapping_stalled = "event_mapping_stalled"
    graph_not_activating = "graph_not_activating"
    recommendations_not_viewed = "recommendations_not_viewed"
    decisions_not_recorded = "decisions_not_recorded"
    actions_not_logged = "actions_not_logged"
    outcomes_not_captured = "outcomes_not_captured"
    playbooks_unused = "playbooks_unused"
    integrations_failed = "integrations_failed"
    value_proven = "value_proven"
    expansion_ready = "expansion_ready"


class ImplementationSuccessCriteria(BaseModel):
    required_events_received: list[str] = Field(default_factory=list)
    minimum_event_volume: int = 0
    graph_active: bool = False
    recommendations_generated: bool = False
    playbooks_configured: bool = False
    integrations_connected: bool = False
    outcomes_observed: bool = False
    value_threshold: Optional[float] = None
    training_completed: bool = False
    go_live_approved: bool = False


class ImplementationStep(BaseModel):
    step_id: str
    tenant_id: str
    title: str
    description: str = ""
    category: ImplementationStepCategory
    status: ImplementationStepStatus = ImplementationStepStatus.not_started
    owner_type: ImplementationOwnerType = ImplementationOwnerType.shared
    required: bool = True
    due_date: Optional[str] = None
    completed_at: Optional[str] = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ImplementationBlocker(BaseModel):
    blocker_id: str
    tenant_id: str
    step_id: Optional[str] = None
    severity: BlockerSeverity = BlockerSeverity.medium
    title: str
    description: str = ""
    owner_type: ImplementationOwnerType = ImplementationOwnerType.shared
    status: BlockerStatus = BlockerStatus.open
    created_at: str
    resolved_at: Optional[str] = None


class TenantImplementationPlan(BaseModel):
    implementation_plan_id: str
    tenant_id: str
    package_id: Optional[str] = None
    deployment_mode: Optional[str] = None
    status: ImplementationStatus = ImplementationStatus.not_started
    onboarding_stage: TenantActivationStage = TenantActivationStage.signed
    owner_id: Optional[str] = None
    target_go_live_date: Optional[str] = None
    required_steps: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    success_criteria: ImplementationSuccessCriteria = Field(default_factory=ImplementationSuccessCriteria)
    implementation_health_score: int = 0
    go_live_readiness_score: int = 0
    value_readiness_score: int = 0
    expansion_readiness_score: int = 0
    created_at: str
    updated_at: str


class OnboardingTemplate(BaseModel):
    template_id: str
    package_id: str
    name: str
    description: str = ""
    default_steps: list[dict[str, Any]] = Field(default_factory=list)
    default_success_criteria: ImplementationSuccessCriteria = Field(default_factory=ImplementationSuccessCriteria)
    recommended_playbooks: list[str] = Field(default_factory=list)
    recommended_integrations: list[str] = Field(default_factory=list)
    recommended_audit_exports: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CustomerSuccessTrigger(BaseModel):
    trigger_id: str
    tenant_id: str
    trigger_type: CustomerSuccessTriggerType
    severity: BlockerSeverity = BlockerSeverity.medium
    reason: str
    supporting_metrics: dict[str, Any] = Field(default_factory=dict)
    recommended_action: str
    created_at: str
    resolved_at: Optional[str] = None
