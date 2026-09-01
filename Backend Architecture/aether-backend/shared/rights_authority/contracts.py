"""Hand-authored IRRL contracts; vocabulary comes from generated_registry."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.rights_authority.generated_registry import (
    RIGHTS_ACTIONS,
    RIGHTS_ACTIVATION_STATES,
    RIGHTS_CLASSES,
    RIGHTS_DECISION_OUTCOMES,
    RIGHTS_PROFILES,
    RIGHTS_TRANSFORMS,
)

RightsAction = Literal[
    "ingest", "store", "read", "graph_mutate", "derive", "train", "evaluate",
    "aggregate", "disclose", "export", "retain", "delete", "operate_kyber",
]
RightsClass = Literal[
    "tenant_contributed_data", "tenant_confidential_intelligence",
    "aether_computational_artifact", "olympus_sourced_data",
    "olympus_generalized_intelligence", "platform_operational_data",
    "retained_compliance_record",
]
RightsProfile = Literal[
    "legacy_restricted", "secure_tenant", "collaborative_learning",
    "strategic_data_exchange",
]
DecisionOutcome = Literal[
    "allow", "deny", "allow_with_obligations", "pending_review", "unavailable",
]
RightsActivationState = Literal[
    "rights_pending", "rights_review", "rights_active", "rights_restricted",
    "rights_revoked",
]
ActorKind = Literal["tenant_user", "service", "operator", "system"]
DisclosureLevel = Literal["none", "masked", "tenant_scoped", "aggregate", "raw"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class RightsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RightsSubject(RightsModel):
    subject_type: Literal["tenant", "source", "artifact", "model", "deployment"]
    subject_id: str
    tenant_id: Optional[str] = None


class ActorRef(RightsModel):
    kind: ActorKind
    id: str
    tenant_id: Optional[str] = None


class ArtifactRef(RightsModel):
    kind: str
    id: str
    version: Optional[str] = None
    tenant_id: Optional[str] = None

    @property
    def ref(self) -> str:
        return f"{self.kind}:{self.id}:{self.version or ''}"


class DestinationRef(RightsModel):
    kind: Literal["tenant", "aether_internal", "olympus_plane", "external_recipient"]
    id: Optional[str] = None
    disclosure_level: DisclosureLevel = "tenant_scoped"
    region: Optional[str] = None


class UseGrant(RightsModel):
    action: RightsAction
    purpose: str = "*"
    rights_classes: list[RightsClass] = Field(default_factory=list)
    destinations: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    expires_at: Optional[str] = None


class RetentionRule(RightsModel):
    retention_class: str
    artifact_classes: list[RightsClass] = Field(default_factory=list)
    days: Optional[int] = None
    legal_hold_allowed: bool = True


class AgreementRef(RightsModel):
    contract_id: str
    contract_version: str
    accepted_at: str


class RightsPolicySet(RightsModel):
    policy_set_id: str = Field(default_factory=lambda: _id("rps"))
    tenant_id: str
    agreement_ref: AgreementRef
    rights_profile: RightsProfile
    effective_from: str = Field(default_factory=_now)
    effective_to: Optional[str] = None
    deployment_constraints: dict[str, Any] = Field(default_factory=dict)
    allowed_uses: list[UseGrant] = Field(default_factory=list)
    retention_rules: list[RetentionRule] = Field(default_factory=list)
    approval_refs: list[str] = Field(default_factory=list)
    activation_state: RightsActivationState = "rights_pending"
    created_at: str = Field(default_factory=_now)

    @field_validator("rights_profile")
    @classmethod
    def valid_profile(cls, value: str) -> str:
        if value not in RIGHTS_PROFILES:
            raise ValueError(f"unknown rights profile: {value}")
        return value


class RightsHolder(RightsModel):
    kind: Literal["tenant", "olympus", "licensor", "subject"]
    id: str
    role: Literal["title", "control", "service_license", "disclosure"]


class ArtifactRightsEnvelope(RightsModel):
    envelope_id: str = Field(default_factory=lambda: _id("rae"))
    artifact_ref: ArtifactRef
    primary_rights_class: RightsClass
    rights_holders: list[RightsHolder] = Field(default_factory=list)
    tenant_id: Optional[str] = None
    source_grant_refs: list[str] = Field(default_factory=list)
    consent_snapshot_refs: list[str] = Field(default_factory=list)
    source_license_refs: list[str] = Field(default_factory=list)
    classification_refs: list[str] = Field(default_factory=list)
    lineage_root_refs: list[str] = Field(default_factory=list)
    retention_class: str = "tenant_event_90d"
    retention_deadline: Optional[str] = None
    effective_from: str = Field(default_factory=_now)
    effective_to: Optional[str] = None
    legal_hold_ref: Optional[str] = None
    policy_set_ref: str
    evidence_manifest_refs: list[str] = Field(default_factory=list)
    lineage_set_hash: str = ""
    disclosure_ceiling: DisclosureLevel = "tenant_scoped"
    deletion_state: Literal["active", "suppressed", "quarantined", "deleted", "retained"] = "active"

    @field_validator("lineage_set_hash")
    @classmethod
    def default_lineage_hash(cls, value: str) -> str:
        return value


class RightsUseRequest(RightsModel):
    request_id: str = Field(default_factory=lambda: _id("rur"))
    action: RightsAction
    actor: ActorRef
    purpose: str
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    envelope_refs: list[str] = Field(default_factory=list)
    destination: DestinationRef = Field(default_factory=lambda: DestinationRef(kind="tenant"))
    transform: Optional[str] = None
    tenant_id: Optional[str] = None
    policy_set_ref: Optional[str] = None
    source_grant_refs: list[str] = Field(default_factory=list)
    evidence_manifest_refs: list[str] = Field(default_factory=list)
    at: str = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Obligation(RightsModel):
    kind: Literal[
        "stamp_lineage", "minimize_fields", "suppress_pii", "tenant_partition",
        "ttl", "approval", "provenance", "export_restriction", "cache_invalidation",
        "recompute", "retrain", "purpose_logging", "recipient_binding",
    ]
    value: Optional[Any] = None


class RightsDecision(RightsModel):
    decision_id: str = Field(default_factory=lambda: _id("rdec"))
    outcome: DecisionOutcome
    reasons: list[str] = Field(default_factory=list)
    obligations: list[Obligation] = Field(default_factory=list)
    envelope_refs: list[str] = Field(default_factory=list)
    evidence_manifest_refs: list[str] = Field(default_factory=list)
    lineage_root_refs: list[str] = Field(default_factory=list)
    purpose: Optional[str] = None
    policy_set_ref: Optional[str] = None
    decision_version: str = "1"
    evaluated_at: str = Field(default_factory=_now)
    expires_at: Optional[str] = None
    signature: str = ""
    signature_key_id: str = "rights-v1"
    request_id: Optional[str] = None
    tenant_id: Optional[str] = None


class DerivationEdge(RightsModel):
    edge_id: str = Field(default_factory=lambda: _id("redge"))
    parent_refs: list[ArtifactRef]
    child_ref: ArtifactRef
    transform_ref: str
    transform_version: str = "1"
    rights_decision_ref: str
    lineage_set_hash: str
    created_at: str = Field(default_factory=_now)


class TransformEvidence(RightsModel):
    transform_ref: str
    input_refs: list[str]
    evidence: dict[str, Any] = Field(default_factory=dict)
    output_class: RightsClass
    approved: bool = False
    release_proof: Optional[str] = None


class RightsImpactNode(RightsModel):
    artifact_ref: ArtifactRef
    status: Literal["affected", "blocked", "remediated", "unavailable"] = "affected"
    remediation_action: Optional[str] = None


class RightsImpactGraph(RightsModel):
    impact_graph_id: str = Field(default_factory=lambda: _id("rig"))
    tenant_id: Optional[str] = None
    root_refs: list[str]
    nodes: list[RightsImpactNode] = Field(default_factory=list)
    edges: list[DerivationEdge] = Field(default_factory=list)
    status: Literal["open", "in_progress", "completed", "blocked"] = "open"
    reason: str
    remediation_receipt_refs: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)


class RightsEvidenceManifest(RightsModel):
    """Signed, durable references supporting a rights decision."""

    manifest_id: str = Field(default_factory=lambda: _id("rem"))
    tenant_id: Optional[str] = None
    subject_refs: list[str] = Field(default_factory=list)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    attested_by: ActorRef
    attested_at: str = Field(default_factory=_now)
    expires_at: Optional[str] = None
    status: Literal["active", "expired", "revoked"] = "active"
    signature: str = ""
    signature_key_id: str = "rights-v1"


class RightsRemediationStep(RightsModel):
    """Append-only execution state for one impacted artifact."""

    step_id: str = Field(default_factory=lambda: _id("rrs"))
    impact_graph_id: str
    artifact_ref: ArtifactRef
    action: str
    status: Literal["pending", "running", "completed", "failed", "blocked"] = "pending"
    attempt: int = 1
    receipt_refs: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=_now)


class RightsRemediationReceipt(RightsModel):
    """Durable evidence of an attempted remediation side effect."""

    receipt_id: str = Field(default_factory=lambda: _id("rrc"))
    impact_graph_id: str
    step_id: str
    artifact_ref: ArtifactRef
    action: str
    outcome: Literal["completed", "failed", "blocked"]
    evidence_refs: list[str] = Field(default_factory=list)
    detail: Optional[str] = None
    completed_at: str = Field(default_factory=_now)


class IssueRightsPolicySet(RightsModel):
    tenant_id: str
    agreement_ref: AgreementRef
    rights_profile: RightsProfile
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    deployment_constraints: dict[str, Any] = Field(default_factory=dict)
    allowed_uses: list[UseGrant] = Field(default_factory=list)
    retention_rules: list[RetentionRule] = Field(default_factory=list)
    approval_refs: list[str] = Field(default_factory=list)
    activation_state: RightsActivationState = "rights_pending"


class AttachRightsEnvelope(RightsModel):
    artifact_ref: ArtifactRef
    primary_rights_class: RightsClass
    policy_set_ref: str
    tenant_id: Optional[str] = None
    rights_holders: list[RightsHolder] = Field(default_factory=list)
    source_grant_refs: list[str] = Field(default_factory=list)
    consent_snapshot_refs: list[str] = Field(default_factory=list)
    source_license_refs: list[str] = Field(default_factory=list)
    classification_refs: list[str] = Field(default_factory=list)
    lineage_root_refs: list[str] = Field(default_factory=list)
    retention_class: str = "tenant_event_90d"
    retention_deadline: Optional[str] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    legal_hold_ref: Optional[str] = None
    disclosure_ceiling: DisclosureLevel = "tenant_scoped"
    evidence_manifest_refs: list[str] = Field(default_factory=list)


class RevokeRightsAuthority(RightsModel):
    root_refs: list[str]
    reason: str
    actor: ActorRef
    tenant_id: Optional[str] = None


def lineage_hash(refs: list[str]) -> str:
    """Stable hash for the complete lineage-root set carried by an artifact."""
    payload = json.dumps(sorted(set(refs)), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "ActorKind", "ActorRef", "AgreementRef", "ArtifactRef", "ArtifactRightsEnvelope",
    "AttachRightsEnvelope", "DecisionOutcome", "DerivationEdge", "DestinationRef",
    "DisclosureLevel", "IssueRightsPolicySet", "Obligation", "RevokeRightsAuthority",
    "RightsAction", "RightsClass", "RightsDecision", "RightsImpactGraph",
    "RightsPolicySet", "RightsProfile", "RightsSubject", "RightsUseRequest",
    "RightsEvidenceManifest", "RightsRemediationReceipt", "RightsRemediationStep",
    "RetentionRule", "TransformEvidence", "UseGrant", "lineage_hash",
]
