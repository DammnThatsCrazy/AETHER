"""Wire models for the principal <-> agent lineage read projection.

These are the seam between the lineage engine/API (producers) and Profile360,
Agent360, Risk360 and Kyber (consumers). The projection is a *derived read
model*: the canonical graph and Bronze/Silver evidence stay authoritative and
every row here is rebuildable from them. Hand-authored TS twin:
``packages/shared/agent-lineage.ts``.

Rules enforced structurally:
  * counts that may be unknown are ``Optional[int]`` — unknown is never 0;
  * every aggregate carries a ``Disclosure`` (as_of / completeness / truncation);
  * confidence is factorized (``ConfidenceFactors``), never one scalar;
  * every principal-agent link carries evidence refs.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfidenceFactors(_Model):
    """Factorized attribution confidence (0..1 each); ``None`` = not assessed."""

    agent_identity_confidence: Optional[float] = None
    instance_binding_confidence: Optional[float] = None
    principal_link_confidence: Optional[float] = None
    operator_link_confidence: Optional[float] = None
    delegation_confidence: Optional[float] = None
    authority_confidence: Optional[float] = None
    execution_link_confidence: Optional[float] = None
    source_quality: Optional[float] = None
    external_effect_confidence: Optional[float] = None
    outcome_confidence: Optional[float] = None


class Disclosure(_Model):
    """Freshness + completeness disclosure carried by every aggregate."""

    as_of: Optional[str] = None
    computed_at: Optional[str] = None
    evidence_window_start: Optional[str] = None
    evidence_window_end: Optional[str] = None
    projection_version: str
    completeness: str  # COMPLETENESS_STATES
    truncated: bool = False
    truncation_reasons: list[str] = Field(default_factory=list)


class ActorContext(_Model):
    """Observation-envelope ``actor_context`` block. Roles never collapse."""

    principal: Optional[str] = None
    initiator: Optional[str] = None
    executor: Optional[str] = None
    operator: Optional[str] = None
    beneficiary: Optional[str] = None
    counterparty: Optional[str] = None
    controller: Optional[str] = None
    reported_principal_ref: Optional[str] = None
    reported_principal_namespace: Optional[str] = None
    canonical_principal_entity_id: Optional[str] = None
    principal_resolution_method: Optional[str] = None
    principal_resolution_status: Optional[str] = None  # PRINCIPAL_RESOLUTION_STATUSES
    principal_confidence: Optional[float] = None
    principal_evidence_refs: list[str] = Field(default_factory=list)


class AuthorityContext(_Model):
    authority_type: Optional[str] = None  # AUTHORITY_TYPES
    authority_ref: Optional[str] = None
    grantor_entity_id: Optional[str] = None
    grantee_entity_id: Optional[str] = None
    scope: Optional[str] = None
    resource_scope: Optional[str] = None
    action_scope: Optional[str] = None
    budget: Optional[str] = None  # decimal string
    currency: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    delegation_allowed: Optional[bool] = None
    maximum_delegation_depth: Optional[int] = None
    policy_id: Optional[str] = None
    policy_version: Optional[str] = None
    approval_ref: Optional[str] = None
    mandate_ref: Optional[str] = None
    revocation_ref: Optional[str] = None
    revoked_at: Optional[str] = None
    authority_resolution_status: Optional[str] = None  # AUTHORITY_RESOLUTION_STATUSES
    authority_evidence_refs: list[str] = Field(default_factory=list)


class ExecutionContext(_Model):
    """Source and canonical identifiers are both kept; source is never overwritten."""

    source_run_id: Optional[str] = None
    canonical_run_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    root_run_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    agent_definition_id: Optional[str] = None
    agent_deployment_id: Optional[str] = None
    agent_instance_id: Optional[str] = None
    task_id: Optional[str] = None
    control_mode: Optional[str] = None  # CONTROL_MODES
    delegation_depth: Optional[int] = None
    external_effect_ref: Optional[str] = None
    execution_verification_state: Optional[str] = None  # EXECUTION_VERIFICATION_STATES


class ProtocolContext(_Model):
    protocol: Optional[str] = None
    protocol_version: Optional[str] = None
    adapter: Optional[str] = None
    adapter_version: Optional[str] = None


class LineageRow(_Model):
    """One principal_agent_lineage row (tenant-scoped, derived, rebuildable)."""

    tenant_id: str
    principal_entity_id: str
    agent_entity_id: str
    agent_definition_id: Optional[str] = None
    agent_instance_id: Optional[str] = None
    root_agent_id: Optional[str] = None
    parent_agent_id: Optional[str] = None
    root_run_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    relationship_type: str  # LINEAGE_RELATIONSHIP_TYPES
    relationship_status: str = "unknown"  # RELATIONSHIP_STATUSES
    depth: int
    direct_or_indirect: str  # "direct" | "indirect"
    authority_ref: Optional[str] = None
    authority_type: Optional[str] = None
    # AUTHORITY_RESOLUTION_STATUSES; out-of-scope / revoked descendants stay
    # in the projection, marked here rather than hidden.
    authority_resolution_status: Optional[str] = None
    attribution_class: str  # ATTRIBUTION_CLASSES
    evidence_class: str  # PRINCIPAL_EVIDENCE_CLASSES (strongest supporting)
    lineage_status: str = "complete"  # LINEAGE_STATUSES
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    active_state: str = "unknown"  # active | inactive | revoked | terminated | unknown
    confidence: ConfidenceFactors = Field(default_factory=ConfidenceFactors)
    evidence_count: int = 0
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_digest: Optional[str] = None
    source_namespaces: list[str] = Field(default_factory=list)
    risk_signal_count: Optional[int] = None
    economic_activity_present: Optional[bool] = None
    communication_activity_present: Optional[bool] = None
    last_reconciled_at: Optional[str] = None
    projection_version: str


class LineageSummary(_Model):
    """Materialized per-principal summary. ``None`` means unknown, not zero."""

    tenant_id: str
    principal_entity_id: str
    unique_agent_definitions: Optional[int] = None
    agent_instances: Optional[int] = None
    agent_runs: Optional[int] = None
    active_agents: Optional[int] = None
    historical_agents: Optional[int] = None
    direct_agents: Optional[int] = None
    indirect_agents: Optional[int] = None
    probabilistic_agents: Optional[int] = None
    unresolved_agents: Optional[int] = None
    revoked_agents: Optional[int] = None
    out_of_scope_agents: Optional[int] = None
    unknown_state_agents: Optional[int] = None
    risk_flagged_agents: Optional[int] = None
    max_delegation_depth: Optional[int] = None
    cyclic_agents: Optional[int] = None
    tools_used: Optional[int] = None
    services_used: Optional[int] = None
    verified_links: Optional[int] = None
    inferred_links: Optional[int] = None
    disclosure: Disclosure


class AgentLineageCounts(_Model):
    """Agent360 descendant roll-up."""

    direct_child_count: Optional[int] = None
    recursive_descendant_count: Optional[int] = None
    active_descendant_count: Optional[int] = None
    risk_descendant_count: Optional[int] = None
    max_descendant_depth: Optional[int] = None
    disclosure: Disclosure


class ClusterBasis(_Model):
    basis: str  # CLUSTER_BASES
    detail: Optional[str] = None
    evidence_refs: list[str] = Field(default_factory=list)


class LineageCluster(_Model):
    """Derived analytic grouping. Never implies common control by itself."""

    cluster_id: str
    kind: str  # CLUSTER_KINDS
    label: Optional[str] = None
    member_count: int
    active_count: Optional[int] = None
    risk_flagged_count: Optional[int] = None
    bases: list[ClusterBasis]  # why members are grouped (non-empty)
    attribution_class: str  # ATTRIBUTION_CLASSES
    implies_common_control: bool = False
    sample_agent_ids: list[str] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class TreeNode(_Model):
    agent_entity_id: str
    depth: int
    descendant_count: Optional[int] = None
    collapsed: bool = False
    lineage_status: str = "complete"
    relationship_type: Optional[str] = None
    attribution_class: str = "unresolved"
    children: list["TreeNode"] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class Page(_Model):
    """Cursor page envelope used by every list endpoint."""

    items: list[dict]
    next_cursor: Optional[str] = None
    page_size: int
    total_estimate: Optional[int] = None
    disclosure: Disclosure


TreeNode.model_rebuild()
