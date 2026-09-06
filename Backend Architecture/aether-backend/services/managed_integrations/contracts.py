"""Canonical Reconciled Control Plane contract (Python mirror of
``packages/shared/managed-integrations.ts``).

The control plane is Aether's operational authority that continuously converges
every managed integration (SDKs, connectors, provider connections, webhooks,
imports, feeds) toward an authorized, healthy, supportable desired state.
Governing principles: *the SDK observes; the control plane manages; the backend
reasons*; "install once, continuously reconcile".

Phase 0 ships the ManagedIntegration abstraction + reconcile *skeleton* only.
Nothing here enables a mutation: there is no live reconcile trigger and no
actuator. Drift is classified and evidence is persisted; applying a ChangeSet
is explicitly deferred (CP-08 boundary).

The TS twin and this module are kept in lockstep by
``tests/contracts/test_managed_integrations_parity.py`` (const-array equality on
kinds, source origins/owners, release channels, availability, reconcile results,
provenance and the Phase-0 emitted drift-type subset, plus the barrel export).

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
- drift types                    §33. ``MANAGED_DRIFT_TYPES`` is the Phase-0
                                     *emitted* subset (six dimensions the
                                     Phase-0 reconciler actually diffs); the
                                     full §33 taxonomy (contract/mapping/
                                     config/policy/consent/... drift) is
                                     reserved for later phases.
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


# Convenience guards mirroring the TS ``is*`` helpers.
def is_managed_integration_kind(value: str) -> bool:
    return value in MANAGED_INTEGRATION_KINDS


def is_integration_availability(value: str) -> bool:
    return value in INTEGRATION_AVAILABILITY_VALUES


def is_reconcile_result(value: str) -> bool:
    return value in RECONCILE_RESULT_VALUES


def is_managed_drift_type(value: str) -> bool:
    return value in MANAGED_DRIFT_TYPES
