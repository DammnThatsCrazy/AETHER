"""Canonical Reconciled Control Plane contract (Python mirror of
``packages/shared/managed-integrations.ts``).

The control plane is Aether's operational authority that continuously converges
every managed integration (SDKs, connectors, provider connections, webhooks,
imports, feeds) toward an authorized, healthy, supportable desired state.
Governing principles: *the SDK observes; the control plane manages; the backend
reasons*; "install once, continuously reconcile".

Phase 0 shipped the ManagedIntegration abstraction + reconcile *skeleton*: no
live reconcile trigger and no actuator; drift was classified and evidence
persisted (CP-08 boundary — a ChangeSet was never applied).

Phase 1 (the additions below) ships the *planning* half of the reconcile loop:
the canonical §33 drift taxonomy, the §34 ChangeSet status vocabulary, the §39
risk classes, the §36 change-action kinds, and the ChangeSet plan / risk-
assessment / blast-radius views. A plan is still never applied — execution
(actuator engine, approval, rollout) is a later phase.

The TS twin and this module are kept in lockstep by
``tests/contracts/test_managed_integrations_parity.py`` (const-array equality on
kinds, source origins/owners, release channels, availability, reconcile results,
provenance, the Phase-0 emitted drift-type subset, and — Phase 1 — the canonical
§33 taxonomy, §34 statuses, §39 risk classes and §36 action kinds, plus the
barrel export).

Vocabulary provenance (Reconciled Control Plane Blueprint):
- Managed integration kinds      §6
- typed availability (CP-12)     §4  — ``missing``, ``empty``, ``zero``,
                                     ``degraded`` and ``not_applicable`` remain
                                     distinct; no operator surface fabricates
                                     zero/empty for missing evidence.
- source origin / owner          §6
- tenant update channels         §28
- reconcile result               §32 (steps 10-11)
- observed-state provenance      §12.2
- drift types (emitted subset)   §33. ``MANAGED_DRIFT_TYPES`` is the Phase-0
                                     *emitted* subset. Every emitted value is a
                                     member of the canonical taxonomy.
- drift taxonomy (canonical)     §33. ``DRIFT_TAXONOMY_TYPES`` is the full
                                     22-type taxonomy. Not every drift requires
                                     a mutation; planning may treat many as
                                     non-actionable.
- ChangeSet status vocabulary    §34. ``CHANGESET_STATUSES`` models the full
                                     state-machine vocabulary; transition
                                     legality is enforced by the executor (a
                                     later phase).
- risk classes                   §39. ``CHANGE_RISK_CLASSES`` = R0 trivial →
                                     R5 destructive/high-consequence, plus the
                                     security-emergency class.
- change-action kinds            §36. ``CHANGE_ACTION_KINDS`` names the typed
                                     operations the Day-1 actuators perform.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── §6 kinds ─────────────────────────────────────────────────────────────────

ManagedIntegrationKind = Literal[
    "sdk_web",
    "sdk_ios",
    "sdk_android",
    "sdk_react_native",
    "sdk_desktop",
    "sdk_node",
    "sdk_python",
    "sdk_rust",
    "sdk_other",
    "connector_aether_hosted",
    "connector_customer_hosted",
    "provider_runtime_connection",
    "webhook",
    "api_ingress",
    "stream_ingress",
    "file_import",
    "warehouse_sync",
    "agent_harness",
    "agent_connector",
    "external_dataset",
    "olympus_curated_feed",
]

MANAGED_INTEGRATION_KINDS: tuple[str, ...] = (
    "sdk_web",
    "sdk_ios",
    "sdk_android",
    "sdk_react_native",
    "sdk_desktop",
    "sdk_node",
    "sdk_python",
    "sdk_rust",
    "sdk_other",
    "connector_aether_hosted",
    "connector_customer_hosted",
    "provider_runtime_connection",
    "webhook",
    "api_ingress",
    "stream_ingress",
    "file_import",
    "warehouse_sync",
    "agent_harness",
    "agent_connector",
    "external_dataset",
    "olympus_curated_feed",
)


# ── §6 source origin / owner ─────────────────────────────────────────────────

IntegrationSourceOrigin = Literal["tenant", "provider", "olympus", "shared_system"]
INTEGRATION_SOURCE_ORIGINS: tuple[str, ...] = ("tenant", "provider", "olympus", "shared_system")

IntegrationSourceOwner = Literal["tenant", "olympus", "provider"]
INTEGRATION_SOURCE_OWNERS: tuple[str, ...] = ("tenant", "olympus", "provider")


# ── §28 tenant update channels (desired release channel) ─────────────────────

ManagedReleaseChannel = Literal[
    "pinned", "security_auto", "patch_auto", "compatible_auto", "managed_stable",
]
MANAGED_RELEASE_CHANNELS: tuple[str, ...] = (
    "pinned", "security_auto", "patch_auto", "compatible_auto", "managed_stable",
)

DEFAULT_MANAGED_RELEASE_CHANNEL = "managed_stable"


# ── CP-12 typed availability ─────────────────────────────────────────────────

IntegrationAvailability = Literal[
    "available", "empty", "missing", "degraded", "not_applicable", "unknown",
]
INTEGRATION_AVAILABILITY_VALUES: tuple[str, ...] = (
    "available", "empty", "missing", "degraded", "not_applicable", "unknown",
)


# ── §32 reconcile results (steps 10-11) ──────────────────────────────────────

ReconcileResult = Literal[
    "match", "acceptable_drift", "actionable_drift", "blocked", "unknown",
]
RECONCILE_RESULT_VALUES: tuple[str, ...] = (
    "match", "acceptable_drift", "actionable_drift", "blocked", "unknown",
)


# ── §33 drift types (Phase-0 emitted subset) ─────────────────────────────────

ManagedDriftType = Literal[
    "version_drift",
    "capability_drift",
    "schema_drift",
    "health_drift",
    "release_support_drift",
    "fleet_identity_drift",
]
MANAGED_DRIFT_TYPES: tuple[str, ...] = (
    "version_drift",
    "capability_drift",
    "schema_drift",
    "health_drift",
    "release_support_drift",
    "fleet_identity_drift",
)


# ── §33 canonical drift taxonomy (full 22-type set) ──────────────────────────

DriftTaxonomyType = Literal[
    "version_drift",
    "capability_drift",
    "contract_drift",
    "schema_drift",
    "mapping_drift",
    "config_drift",
    "policy_drift",
    "authority_drift",
    "consent_drift",
    "platform_permission_drift",
    "provider_scope_drift",
    "provider_terms_drift",
    "endpoint_drift",
    "health_drift",
    "data_quality_drift",
    "release_support_drift",
    "fleet_identity_drift",
    "region_drift",
    "credential_drift",
    "source_authority_drift",
    "volume_drift",
    "cost_drift",
]
DRIFT_TAXONOMY_TYPES: tuple[str, ...] = (
    "version_drift",
    "capability_drift",
    "contract_drift",
    "schema_drift",
    "mapping_drift",
    "config_drift",
    "policy_drift",
    "authority_drift",
    "consent_drift",
    "platform_permission_drift",
    "provider_scope_drift",
    "provider_terms_drift",
    "endpoint_drift",
    "health_drift",
    "data_quality_drift",
    "release_support_drift",
    "fleet_identity_drift",
    "region_drift",
    "credential_drift",
    "source_authority_drift",
    "volume_drift",
    "cost_drift",
)


# ── §34 ChangeSet status vocabulary ──────────────────────────────────────────

ChangeSetStatus = Literal[
    "draft",
    "planned",
    "preparing",
    "validating",
    "simulating",
    "waiting_approval",
    "ready",
    "canary",
    "rolling_out",
    "verifying",
    "committed",
    "rolling_back",
    "rolled_back",
    "cancelled",
    "blocked",
    "failed",
    "superseded",
]
CHANGESET_STATUSES: tuple[str, ...] = (
    "draft",
    "planned",
    "preparing",
    "validating",
    "simulating",
    "waiting_approval",
    "ready",
    "canary",
    "rolling_out",
    "verifying",
    "committed",
    "rolling_back",
    "rolled_back",
    "cancelled",
    "blocked",
    "failed",
    "superseded",
)


# ── §39 change-risk classes ──────────────────────────────────────────────────

ChangeRiskClass = Literal[
    "R0", "R1", "R2", "R3", "R4", "R5", "security_emergency",
]
CHANGE_RISK_CLASSES: tuple[str, ...] = (
    "R0", "R1", "R2", "R3", "R4", "R5", "security_emergency",
)


# ── §36 change-action kinds (Day-1 typed actuator operations) ────────────────

ChangeActionKind = Literal[
    "remote_manifest_change",
    "managed_connector_change",
    "provider_runtime_change",
    "mapping_change",
    "compatibility_projection_change",
    "repository_upgrade",
    "authorization_change",
    "quarantine",
    "replay",
    "backfill",
    "rollback",
    "notification_action",
]
CHANGE_ACTION_KINDS: tuple[str, ...] = (
    "remote_manifest_change",
    "managed_connector_change",
    "provider_runtime_change",
    "mapping_change",
    "compatibility_projection_change",
    "repository_upgrade",
    "authorization_change",
    "quarantine",
    "replay",
    "backfill",
    "rollback",
    "notification_action",
)


# ── §12.15 control-finding kinds (canonical epistemic model) ─────────────────

ControlFindingKind = Literal[
    "observed", "verified", "correlated", "inferred", "predicted",
]
CONTROL_FINDING_KINDS: tuple[str, ...] = (
    "observed", "verified", "correlated", "inferred", "predicted",
)

# ── §32 step 19 verify outcomes (technical + semantic health) ────────────────

VerifyOutcome = Literal["passed", "failed"]
VERIFY_OUTCOMES: tuple[str, ...] = ("passed", "failed")

# ── §12.13 evidence confidence scale (mirrors the §39 rollback-confidence
#    high/medium/low scale) ───────────────────────────────────────────────────

EvidenceConfidence = Literal["high", "medium", "low"]
EVIDENCE_CONFIDENCE_VALUES: tuple[str, ...] = ("high", "medium", "low")

# ── §12.11 rollback-record lifecycle ──────────────────────────────────────────

RollbackStatus = Literal["pending", "rolling_back", "rolled_back", "failed"]
ROLLBACK_STATUSES: tuple[str, ...] = (
    "pending", "rolling_back", "rolled_back", "failed",
)

# ── §12.14 action-required lifecycle ──────────────────────────────────────────

ActionRequiredStatus = Literal["open", "resolved"]
ACTION_REQUIRED_STATUSES: tuple[str, ...] = ("open", "resolved")


# ── §12.2 observed-state provenance ──────────────────────────────────────────

ObservedProvenance = Literal[
    "runtime_reported",
    "backend_verified",
    "provider_reported",
    "operator_supplied",
    "inferred",
    "unknown",
]
OBSERVED_PROVENANCE_VALUES: tuple[str, ...] = (
    "runtime_reported",
    "backend_verified",
    "provider_reported",
    "operator_supplied",
    "inferred",
    "unknown",
)


# ── contracts ─────────────────────────────────────────────────────────────────

class ManagedIntegrationView(BaseModel):
    """A durable ``managed_integrations`` row (Phase-0 operator read surface).

    Health/lifecycle states are strings sourced from the observing authority
    (SDK health, provider runtime, capability activation); they are never
    inferred from row existence.
    """

    managed_integration_id: str
    tenant_id: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    integration_kind: ManagedIntegrationKind
    source_ref: str = Field(..., min_length=1)
    provider_ref: Optional[str] = None
    source_origin: IntegrationSourceOrigin
    source_owner: IntegrationSourceOwner
    release_channel: ManagedReleaseChannel = "managed_stable"
    health_state: str = "unknown"
    lifecycle_state: str = "unknown"
    schema_fingerprint: Optional[str] = None
    desired_state_ref: Optional[str] = None
    observed_state_ref: Optional[str] = None
    first_seen_at: datetime
    last_seen_at: datetime
    last_reconcile_at: Optional[datetime] = None
    last_reconcile_result: Optional[ReconcileResult] = None
    created_at: datetime
    updated_at: datetime


class MinimumCapabilityRequirement(BaseModel):
    capability: str
    required_availability: IntegrationAvailability


class DesiredStateSpec(BaseModel):
    """Authoritative declaration of what should exist (blueprint §12.1 subset)."""

    desired_state_id: str
    managed_integration_ref: str
    tenant_id: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    revision: str
    release_channel: ManagedReleaseChannel = "managed_stable"
    minimum_runtime_version: Optional[str] = None
    minimum_capabilities: list[MinimumCapabilityRequirement] = Field(default_factory=list)
    schema_fingerprint: Optional[str] = None
    health_policy_ref: Optional[str] = None
    integration_contract_ref: Optional[str] = None
    created_at: datetime


class ObservedStateSnapshot(BaseModel):
    """What is actually running (blueprint §12.2 Phase-0 subset)."""

    observed_state_id: str
    managed_integration_ref: str
    tenant_id: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    observed_at: datetime
    received_at: datetime
    provenance: ObservedProvenance = "unknown"
    availability: IntegrationAvailability = "unknown"
    runtime_version: Optional[str] = None
    platform: Optional[str] = None
    schema_fingerprint: Optional[str] = None
    queue_state: Optional[dict[str, Any]] = None
    ingestion_state: Optional[str] = None
    auth_state: Optional[str] = None
    consent_state: Optional[str] = None
    provider_state: Optional[str] = None
    endpoint_state: Optional[str] = None
    health_ref: Optional[str] = None
    health_status: Optional[str] = None
    reported_source_identity: Optional[str] = None
    last_successful_observation_at: Optional[datetime] = None


class DriftRecord(BaseModel):
    """A single typed drift fact (blueprint §12.4 Phase-0 subset)."""

    drift_id: str
    managed_integration_ref: str
    desired_state_ref: Optional[str] = None
    observed_state_ref: Optional[str] = None
    drift_type: ManagedDriftType
    detail: str
    first_seen_at: datetime
    last_seen_at: datetime


class ReconcileRunView(BaseModel):
    """One reconcile execution + its DRAFT change summary.

    ``drift`` is evidence only — never applied by Phase 0 (CP-08 boundary).
    """

    reconcile_id: str
    managed_integration_ref: str
    desired_state_ref: str
    observed_state_ref: str
    desired_revision: str
    observed_revision: str
    freshness_ok: bool
    result: ReconcileResult
    note: Optional[str] = None
    drift: list[DriftRecord] = Field(default_factory=list)
    created_at: datetime


class ChangeSpec(BaseModel):
    """One typed mutation a plan may carry (blueprint §12.5 / §36).

    Vocabulary only in Phase 1 — nothing executes a plan. ``params`` are
    action-specific and typed by the owning actuator in Phase 2.
    """

    action: ChangeActionKind
    target_ref: str = Field(..., min_length=1)
    params: Optional[dict[str, Any]] = None
    reason: Optional[str] = None


class RiskAssessmentView(BaseModel):
    """Risk decision for a candidate change (§32 step 14 / §12.6 subset).

    ``automation_allowed`` True only when the risk class may proceed
    automatically under policy; every other class routes to the
    approval/action authority (§32 step 15).
    """

    risk_class: ChangeRiskClass
    automation_allowed: bool
    required_approval_refs: list[str] = Field(default_factory=list)
    explanation_refs: list[str] = Field(default_factory=list)


class BlastRadiusView(BaseModel):
    """Control-topology blast radius for a candidate change (§32 step 13)."""

    integration_count: int = Field(..., ge=0)
    tenant_count: int = Field(..., ge=0)
    environment_count: int = Field(..., ge=0)
    source_origins: list[IntegrationSourceOrigin] = Field(default_factory=list)
    actionable_drift_types: list[DriftTaxonomyType] = Field(default_factory=list)


class ChangeSetPlanView(BaseModel):
    """A ChangeSet *plan* (§32 step 12 / §12.5 planning subset) — never applied.

    ``status`` reaches at most ``planned`` in Phase 1; a guard invalidation
    moves a plan to ``superseded``. Execution statuses are unreachable while no
    executor exists (illegal transitions fail closed from the start, §34).
    """

    changeset_id: str
    tenant_id: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    integration_scope: list[str] = Field(default_factory=list)
    desired_revision: str
    observed_revision: str
    reconcile_sequence: str
    idempotency_key: str
    changes: list[ChangeSpec] = Field(default_factory=list)
    reason: Optional[str] = None
    initiator: str
    policy_ref: Optional[str] = None
    risk: RiskAssessmentView
    blast_radius: BlastRadiusView
    status: ChangeSetStatus = "draft"
    created_at: datetime
    superseded_at: Optional[datetime] = None


class VerifyReport(BaseModel):
    """§32 step-19 verification of technical + semantic health (§12.9 subset).

    Produced after actuator apply, before commit-or-rollback. A rollback is
    triggered when either dimension fails; LKG is established only when both
    pass (§32 steps 19-21).
    """

    changeset_id: str
    technical_health: VerifyOutcome
    semantic_health: VerifyOutcome
    validation_refs: list[str] = Field(default_factory=list)
    note: Optional[str] = None
    verified_at: datetime


class ChangeEvidenceView(BaseModel):
    """One executed/attempted change's evidence (§32 step 22 / §12.13).

    ``claim_type`` is the §12.15 epistemic status of the before/after claim —
    the control plane never labels a correlation as causality. ``confidence``
    is the evidence-confidence scale. Approval refs identify the §21 authority
    exercised. ``contradictory_evidence_refs`` are recorded, never dropped.
    """

    change_evidence_id: str
    changeset_ref: str
    tenant_id: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    initiator: str
    policy_ref: Optional[str] = None
    before_state_refs: list[str] = Field(default_factory=list)
    after_state_refs: list[str] = Field(default_factory=list)
    reason: Optional[str] = None
    claim_type: ControlFindingKind
    confidence: EvidenceConfidence
    risk_ref: Optional[str] = None
    simulation_ref: Optional[str] = None
    rollout_ref: Optional[str] = None
    validation_refs: list[str] = Field(default_factory=list)
    approval_refs: list[str] = Field(default_factory=list)
    rollback_ref: Optional[str] = None
    tenant_action_required: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    contradictory_evidence_refs: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime


class LastKnownGoodView(BaseModel):
    """Last-known-good state for a managed integration (§32 step 21 / §12.12).

    Established only after verification passes — a completed rollout that did
    not verify never becomes LKG. Refs point at durable states the control
    plane can restore on rollback.
    """

    lkg_id: str
    managed_integration_ref: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    desired_state_ref: Optional[str] = None
    artifact_ref: Optional[str] = None
    runtime_config_ref: Optional[str] = None
    schema_ref: Optional[str] = None
    mapping_refs: list[str] = Field(default_factory=list)
    integration_contract_ref: Optional[str] = None
    policy_ref: Optional[str] = None
    provider_state_ref: Optional[str] = None
    verified_health_ref: Optional[str] = None
    established_at: datetime


class RollbackRecordView(BaseModel):
    """One ChangeSet rollback (§32 steps 20-21 / §12.11).

    References the LKG ref it restores toward and the ordered §36 rollback
    actions executed. ``status`` follows the rollback-record lifecycle
    (pending -> rolling_back -> rolled_back | failed).
    """

    rollback_id: str
    changeset_ref: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    last_known_good_ref: Optional[str] = None
    rollback_actions: list[str] = Field(default_factory=list)
    queue_recovery_policy: Optional[str] = None
    replay_policy: Optional[str] = None
    validation_requirements: list[str] = Field(default_factory=list)
    status: RollbackStatus = "pending"
    created_at: datetime
    completed_at: Optional[datetime] = None


class ChangeSetApprovalView(BaseModel):
    """A §21 role-gated approval attached to a ChangeSet (evidence record).

    Records which authority (role) exercised the approval for which required
    approval ref (``approval:olympus_operator``, ``approval:tenant_owner``,
    ...) and the actor that carried it. Approvals are required before an R3/R4/
    R5/security-emergency plan may move past ``waiting_approval``.
    """

    approval_id: str
    changeset_ref: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    required_approval_ref: str = Field(..., min_length=1)
    granted_role: str = Field(..., min_length=1)  # §21 role name
    granted_by_actor: str = Field(..., min_length=1)  # operator identity
    decision: str = "approved"  # approved | denied
    note: Optional[str] = None
    decided_at: datetime


class ActionRequiredView(BaseModel):
    """An unresolved change surfaced for action (§32 step 23 / §12.14).

    Emitted by the executor/actuator when a change cannot resolve within the
    current authority (missing approval, unavailable substrate, a rollback that
    also failed, a data-loss decision). ``action_type`` is open vocabulary
    emitted by the component that cannot resolve the change.
    """

    action_id: str
    tenant_ref: str = Field(..., min_length=1)
    managed_integration_ref: str = Field(..., min_length=1)
    environment_id: str = Field(..., min_length=1)
    action_type: str
    reason: str
    impact: Optional[str] = None
    deadline: Optional[datetime] = None
    required_actor: str
    required_action: str
    continuity_state: Optional[str] = None
    data_loss_expected: bool = False
    resolution_ref: Optional[str] = None
    status: ActionRequiredStatus = "open"
    created_at: datetime


# Convenience guards mirroring the TS ``is*`` helpers.
def is_managed_integration_kind(value: str) -> bool:
    return value in MANAGED_INTEGRATION_KINDS


def is_integration_availability(value: str) -> bool:
    return value in INTEGRATION_AVAILABILITY_VALUES


def is_reconcile_result(value: str) -> bool:
    return value in RECONCILE_RESULT_VALUES


def is_managed_drift_type(value: str) -> bool:
    return value in MANAGED_DRIFT_TYPES


def is_drift_taxonomy_type(value: str) -> bool:
    return value in DRIFT_TAXONOMY_TYPES


def is_change_set_status(value: str) -> bool:
    return value in CHANGESET_STATUSES


def is_change_risk_class(value: str) -> bool:
    return value in CHANGE_RISK_CLASSES


def is_change_action_kind(value: str) -> bool:
    return value in CHANGE_ACTION_KINDS


def is_control_finding_kind(value: str) -> bool:
    return value in CONTROL_FINDING_KINDS


def is_verify_outcome(value: str) -> bool:
    return value in VERIFY_OUTCOMES


def is_rollback_status(value: str) -> bool:
    return value in ROLLBACK_STATUSES


def is_action_required_status(value: str) -> bool:
    return value in ACTION_REQUIRED_STATUSES


# ── Phase-3 vocabulary: §16 admission / §17 discovery / §8.1 mapping /
# ── §9 source authority / §12.7 simulation / §38 automation gates ─────────────
# Python mirror of the Phase-3 additions to packages/shared/managed-integrations.ts.

ADMISSION_STAGES: tuple[str, ...] = (
    "discover",
    "understand",
    "classify",
    "reconcile_source_authority",
    "authorize",
    "simulate",
    "approve",
    "compile",
    "activate",
    "observe",
)

CONTINUOUS_LIFECYCLE_ACTIONS: tuple[str, ...] = (
    "monitor",
    "drift",
    "reconcile",
    "change",
    "review",
    "suspend",
    "revoke",
)

DISCOVERY_DATA_CLASSES: tuple[str, ...] = (
    "metadata_only",  # §17 default — source code / production values are not
    "source_code",  # uploaded by default
    "production_values",
)

MAPPING_METHOD_VALUES: tuple[str, ...] = (
    "static",
    "provider_known",
    "heuristic",
    "model_assisted",
    "human",
)

# §8.1 confidence policy: >=0.98 auto-propose only; 0.80-0.979 review
# recommended; <0.80 unresolved. Sensitive mappings still require
# authorization regardless of confidence.
MAPPING_REVIEW_STATES: tuple[str, ...] = (
    "auto_propose",
    "review",
    "unresolved",
)

SIMULATION_RESULT_VALUES: tuple[str, ...] = ("pass", "conditional", "fail")

# §38: automatic promotion is allowed only when ALL gates hold; otherwise a
# review/action is generated.
SCHEMA_MAPPING_AUTO_PROMOTE_GATES: tuple[str, ...] = (
    "high_confidence",
    "no_new_data_category",
    "no_new_sensitive_field",
    "no_new_processing_purpose",
    "no_new_platform_provider_permission",
    "no_material_semantic_loss",
    "shadow_result_passes",
    "health_within_gates",
)


def is_admission_stage(value: str) -> bool:
    return value in ADMISSION_STAGES


def is_discovery_data_class(value: str) -> bool:
    return value in DISCOVERY_DATA_CLASSES


def is_mapping_method(value: str) -> bool:
    return value in MAPPING_METHOD_VALUES


def is_mapping_review_state(value: str) -> bool:
    return value in MAPPING_REVIEW_STATES


def is_simulation_result(value: str) -> bool:
    return value in SIMULATION_RESULT_VALUES


def is_schema_mapping_auto_promote_gate(value: str) -> bool:
    return value in SCHEMA_MAPPING_AUTO_PROMOTE_GATES


class DiscoveryManifestView(BaseModel):
    """Metadata-first structural discovery output (§7.4 DiscoveryManifestContract).

    ``uploaded_data_class`` defaults to ``metadata_only`` (§17): source code and
    production values are never uploaded by default.
    """

    discovery_id: str = Field(..., min_length=1)
    source_ref: str = Field(..., min_length=1)
    discovery_engine_version: str = Field(..., min_length=1)
    artifact_hash: str = Field(..., min_length=1)
    frameworks: list[str] = Field(default_factory=list)
    packages: list[str] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    analytics_contracts: list[str] = Field(default_factory=list)
    identity_contracts: list[str] = Field(default_factory=list)
    commerce_contracts: list[str] = Field(default_factory=list)
    payment_contracts: list[str] = Field(default_factory=list)
    consent_contracts: list[str] = Field(default_factory=list)
    agent_contracts: list[str] = Field(default_factory=list)
    network_contracts: list[str] = Field(default_factory=list)
    sensitive_candidates: list[str] = Field(default_factory=list)
    secret_candidates: list[str] = Field(default_factory=list)
    uploaded_data_class: str = "metadata_only"
    tenant_id: Optional[str] = None
    environment_id: Optional[str] = None
    discovered_at: datetime


class SemanticMappingCandidateView(BaseModel):
    """A proposed semantic mapping (§8.1 SemanticMappingCandidateContract).

    Candidates are epistemic proposals, never truth; the §8.1 confidence
    policy decides ``review_state`` and sensitive mappings always require
    authorization regardless of confidence.
    """

    candidate_id: str = Field(..., min_length=1)
    source_ref: str = Field(..., min_length=1)
    source_path: str = Field(..., min_length=1)
    canonical_target: str = Field(..., min_length=1)
    mapping_method: str = "heuristic"
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: Optional[str] = None
    sensitivity_class: Optional[str] = None
    transform_ref: Optional[str] = None
    review_state: str = "review"
    tenant_id: Optional[str] = None
    environment_id: Optional[str] = None
    created_at: datetime


class SourceAuthorityRuleView(BaseModel):
    """Domain/property-specific source precedence (§9.1 SourceAuthorityRuleContract).

    Authority is never a blanket statement that one provider is always
    superior; rules carry ``source_precedence`` per ``property_path``.
    """

    rule_id: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    property_path: str = Field(..., min_length=1)
    source_precedence: list[str] = Field(default_factory=list)
    conflict_strategy: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    policy_ref: Optional[str] = None
    tenant_id: Optional[str] = None
    environment_id: Optional[str] = None


class ObservationEquivalenceKeyView(BaseModel):
    """Semantic-equivalence key separating transport idempotency from semantic
    deduplication (§9.2 ObservationEquivalenceKeyContract)."""

    key_id: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    candidate_types: list[str] = Field(default_factory=list)
    key_components: list[str] = Field(default_factory=list)
    window: Optional[str] = None
    normalization_rules: Optional[list[str]] = None
    semantic_dedupe_policy: Optional[str] = None
    tenant_id: Optional[str] = None
    environment_id: Optional[str] = None


class SimulationResultView(BaseModel):
    """Simulation/digital-twin outcome (§12.7 SimulationResultContract).

    A shadow result never mutates canonical graph state (§37) — it compares an
    authoritative current path against a non-authoritative candidate path and
    reports deltas plus unknowns/warnings.
    """

    simulation_id: str = Field(..., min_length=1)
    changeset_ref: Optional[str] = None
    input_snapshot_refs: list[str] = Field(default_factory=list)
    fixture_refs: list[str] = Field(default_factory=list)
    contract_result: Optional[str] = None
    schema_result: Optional[str] = None
    mapping_result: Optional[str] = None
    privacy_result: Optional[str] = None
    authorization_result: Optional[str] = None
    volume_result: Optional[str] = None
    metric_reconciliation: Optional[str] = None
    identity_continuity: Optional[str] = None
    journey_continuity: Optional[str] = None
    outcome_continuity: Optional[str] = None
    latency_delta: Optional[str] = None
    cost_delta: Optional[str] = None
    unknowns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    result: str = "conditional"
    tenant_id: Optional[str] = None
    environment_id: Optional[str] = None
    simulation_mode: Optional[str] = None  # digital_twin | shadow (§37)
    ran_at: datetime
