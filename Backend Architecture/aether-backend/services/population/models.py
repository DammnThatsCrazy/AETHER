"""
Population data models — groups, memberships, and evidence.

All population objects use the existing BaseRepository pattern for persistence.
"""

from __future__ import annotations

import hashlib
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
) -> dict:
    """Create a canonical population object record."""
    now = utc_now().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "population_type": population_type.value,
        "description": description,
        "definition": definition or {},
        "definition_version": definition_version,
        "source_tag": source_tag,
        "tenant_id": tenant_id,
        "metadata": metadata or {},
        "member_count": 0,
        "status": "active",
        "created_at": now,
        "updated_at": now,
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
