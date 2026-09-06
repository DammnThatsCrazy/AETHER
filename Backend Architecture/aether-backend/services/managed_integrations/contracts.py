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
