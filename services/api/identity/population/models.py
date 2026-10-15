"""
Population data models — groups, memberships, and evidence.

All population objects use the existing BaseRepository pattern for persistence.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now


class PopulationType(str, Enum):
    """Types of population objects supported."""
    SEGMENT = "segment"           # Rule-based, operator-defined
    COHORT = "cohort"             # Saved, scheduled, or dynamic
    CLUSTER = "cluster"           # ML-derived (similarity, behavior)
    COMMUNITY = "community"       # Graph-derived (topology)
    BATCH = "batch"               # One-time analysis
    ARCHETYPE = "archetype"       # Behavior archetype label
    ANOMALY_GROUP = "anomaly"     # Anomaly-detected group
    LOOKALIKE = "lookalike"       # Similar to a seed set
    RISK_GROUP = "risk"           # Risk-tier grouping
    LIFECYCLE = "lifecycle"       # Lifecycle stage group


class MembershipBasis(str, Enum):
    """How membership was determined."""
    RULE = "rule"                 # Rule/filter match
    GRAPH = "graph"               # Graph topology
    ML_MODEL = "ml_model"         # Model scoring
    SIMILARITY = "similarity"     # Feature similarity
    MANUAL = "manual"             # Operator assignment
    INFERRED = "inferred"         # Confidence-weighted inference


class MembershipState(str, Enum):
    """Lifecycle state of a governed membership (population360 P3.1)."""
    ACTIVE = "active"             # Currently a member
    LEFT = "left"                 # Voluntarily left / removed (close-and-append, no hard delete)
    EXPIRED = "expired"           # Membership lapsed (definition recompute no longer matches)


class PopulationCreate(BaseModel):
    """Request to create a population object."""
    name: str
    population_type: PopulationType
    description: str = ""
    definition: dict = Field(default_factory=dict, description="Rules, filters, or config that define this group")
    source_tag: str = ""
    metadata: dict = Field(default_factory=dict)
    consent_purpose: str = Field(
        default="analytics",
        description="Registry consent purpose under which membership in this "
        "population is processed (population360 P3.2). A governed membership "
        "write evaluates server consent for the member under this purpose.",
    )


class DefinitionRevision(BaseModel):
    """Request to publish a NEW immutable population-definition version (P3.2).

    Revisions never edit a definition in place: ``revise_definition`` appends a
    new immutable version and advances the population's current-definition
    projection with a documented transition. ``reason`` is required so no
    transition is silent.
    """
    definition: dict
    reason: str = Field(..., min_length=1, description="Documented reason for the revision (required — no silent redefinition)")
    metadata: dict = Field(default_factory=dict)


class MembershipAdd(BaseModel):
    """Request to add members to a population."""
    entity_ids: list[str]
    entity_type: str = "user"
    basis: MembershipBasis = MembershipBasis.RULE
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""
    source_tag: str = ""


class PopulationQuery(BaseModel):
    """Query for population objects."""
    population_type: Optional[PopulationType] = None
    name_contains: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)


def make_population_record(
    name: str,
    population_type: PopulationType,
    description: str = "",
    definition: Optional[dict] = None,
    source_tag: str = "",
    tenant_id: str = "",
    metadata: Optional[dict] = None,
    definition_version: str = "1",
    consent_purpose: str = "analytics",
) -> dict:
    """Create a canonical population object record.

    ``definition`` is the population's *current* definition projection; the
    authoritative, immutable definition contract lives in the append-only
    ``population_definition_versions`` ledger (population360 P3.2). The
    population row's ``definition`` only ever changes through a governed
    ``revise_definition`` that appends a new version — never in place.
    """
    now = utc_now().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "population_type": population_type.value,
        "description": description,
        "definition": definition or {},
        "definition_version": definition_version,
        "consent_purpose": consent_purpose,
        "source_tag": source_tag,
        "tenant_id": tenant_id,
        "metadata": metadata or {},
        "member_count": 0,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }


def make_definition_version_record(
    population_id: str,
    definition_version: str,
    definition: dict,
    *,
    reason: str,
    created_by: str,
    supersedes_version: Optional[str] = None,
) -> dict:
    """Create an immutable population-definition version record (P3.2).

    The record id is deterministic over ``(population_id, version)`` so a
    version can be appended at most once — the definition contract is immutable
    once published. ``definition_hash`` (sha256 over canonical JSON) lets a
    reader detect any drift between a version row and what it claims to hold.
    """
    now = utc_now().isoformat()
    canonical = json.dumps(definition or {}, sort_keys=True, separators=(",", ":"))
    record_id = hashlib.sha256(
        f"{population_id}:{definition_version}".encode()
    ).hexdigest()[:24]
    return {
        "id": record_id,
        "population_id": population_id,
        "definition_version": str(definition_version),
        "definition": definition or {},
        "definition_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "supersedes_version": supersedes_version,
        "reason": reason,
        "created_by": created_by,
        "status": "active",
        "created_at": now,
    }


def make_membership_record(
    population_id: str,
    entity_id: str,
    entity_type: str = "user",
    basis: MembershipBasis = MembershipBasis.RULE,
    confidence: float = 1.0,
    reason: str = "",
    source_tag: str = "",
    tenant_id: str = "",
    membership_state: str = MembershipState.ACTIVE.value,
    definition_version: str = "1",
    evidence_refs: Optional[list[str]] = None,
    left_at: str = "",
    leave_reason: str = "",
) -> dict:
    """Create a canonical membership record (population360 P3.1 governed form).

    The record is the *materialized* current state of a governed membership;
    the authoritative, history-bearing fact is the ``MEMBER_OF`` graph edge
    written through the mutation gateway (close-and-append into the ledger).
    Leaves are state transitions (``membership_state=left`` + ``left_at``),
    never hard deletes, so the row stays a rebuildable materialization.
    """
    now = utc_now().isoformat()
    record_id = hashlib.sha256(f"{population_id}:{entity_id}".encode()).hexdigest()[:24]
    return {
        "id": record_id,
        "population_id": population_id,
        "entity_id": entity_id,
        "entity_type": entity_type,
        "basis": basis.value,
        "confidence": confidence,
        "reason": reason,
        "source_tag": source_tag,
        "tenant_id": tenant_id,
        "status": membership_state,
        "membership_state": membership_state,
        "definition_version": definition_version,
        "evidence_refs": evidence_refs or [],
        "joined_at": now,
        "left_at": left_at,
        "leave_reason": leave_reason,
        "created_at": now,
        "updated_at": now,
    }
