"""Rights Authority — canonical contracts (Part 1: Effective Rights Resolver + durable decisions).

Implements the frozen field contract in
``docs/source-of-truth/RIGHTS_AUTHORITY_BLUEPRINT.md`` §4 (``RightsDecision``),
§5.2 (``RightsLineage``), §11/§19 (``to_envelope_ref``), §12 (``RightsContext``)
and §10 (``RightsImpact``).

Fail-closed doctrine is encoded structurally:
- ``RightsDecision.allowed`` has **no** default — a decision struct must declare
  allow/deny explicitly. There is intentionally no ``allowed=False`` default that
  a caller could forget to override, and no implicit allow.
- Unknown/new fields are ignored on load (``extra="ignore"``) rather than being
  given a permissive meaning.

Disposition and lifecycle enums are owned by the P-A stream in
``services.integrations.data_rights.models`` (canonical snake_case values); this
module imports them rather than re-defining a competing vocabulary (blueprint
"no parallel registries" rule).
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from services.security.contracts import now_iso
from services.integrations.data_rights.models import (
    LifecycleAction,
    RightsDecisionDisposition,
    RightsDerivationClass,
)

__all__ = [
    "RightsDecisionRequest",
    "RightsDecision",
    "RightsLineage",
    "RightsContext",
    "RightsImpact",
    "ALLOWED_REMEDIATION_STATES",
]


def _rdec_id() -> str:
    return f"rdec_{uuid.uuid4().hex}"


def _rimp_id() -> str:
    return f"rimp_{uuid.uuid4().hex}"


# Blueprint §10 — remediation_state vocabulary. A value outside this set is
# "unknown", which must never be treated as complete.
ALLOWED_REMEDIATION_STATES: frozenset[str] = frozenset({
    "pending", "in_progress", "complete", "blocked", "unknown",
})


class RightsDecisionRequest(BaseModel):
    """A resolved authorization question (blueprint §16 resolver input).

    ``as_of`` is an optional historical ISO timestamp; when omitted the decision
    is evaluated "now". ``artifact_ref`` / ``artifact_class`` are optional context
    used for ownership/derivation classification (a grant can be checked before
    any artifact exists, e.g. a store permission).
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    source_id: str
    artifact_ref: Optional[str] = None
    artifact_class: Optional[str] = None
    actor: str
    actor_role: Optional[str] = None
    requested_use: str
    purpose: str
    destination: str
    subject_ref: Optional[str] = None
    as_of: Optional[str] = None


class RightsDecision(BaseModel):
    """Durable, immutable, temporally-effective rights decision (blueprint §4).

    ``tenant_id`` is a documented superset of the §4 field list: the durable
    store is tenant-scoped and every record is isolated by tenant, so the scoping
    key must travel on the record itself (sibling governance records follow the
    same convention — a ``tenant_id`` column plus JSONB body).
    """

    model_config = ConfigDict(extra="ignore")

    decision_id: str = Field(default_factory=_rdec_id)
    tenant_id: str
    allowed: bool  # no default: allow/deny must be declared explicitly
    disposition: RightsDecisionDisposition
    reason_codes: list[str] = Field(default_factory=list)
    source_grant_refs: list[str] = Field(default_factory=list)
    consent_decision_refs: list[str] = Field(default_factory=list)
    ownership_class: Optional[str] = None
    permitted_uses: list[str] = Field(default_factory=list)
    permitted_derivations: list[str] = Field(default_factory=list)
    permitted_learning: list[str] = Field(default_factory=list)
    permitted_disclosures: list[str] = Field(default_factory=list)
    retention: Optional[str] = None
    deletion: Optional[str] = None
    survival: Optional[str] = None
    evaluated_at: str = Field(default_factory=now_iso)
    effective_as_of: Optional[str] = None
    policy_version: str = "irrl-2"
    evidence_refs: list[str] = Field(default_factory=list)

    def to_envelope_ref(self) -> dict[str, str]:
        """Lightweight rights ref for observation envelopes (blueprint §11/§19).

        Envelopes carry the durable ref + policy version + evaluation time, not
        the full decision.
        """
        return {
            "rights_decision_ref": self.decision_id,
            "rights_policy_version": self.policy_version,
            "evaluated_at": self.evaluated_at,
        }


class RightsLineage(BaseModel):
    """Artifact → parent/source/decision rights lineage (blueprint §5.2).

    Reuses canonical lineage/evidence references; no duplicate evidence system.
    ``tenant_id`` is an optional scoping superset so lineage rows can be isolated
    by tenant where the artifact is tenant-scoped.
    """

    model_config = ConfigDict(extra="ignore")

    artifact_id: str
    parent_artifact_refs: list[str] = Field(default_factory=list)
    source_grant_refs: list[str] = Field(default_factory=list)
    rights_decision_refs: list[str] = Field(default_factory=list)
    derivation_class: RightsDerivationClass
    semantic_level: Optional[str] = None
    trust_class: Optional[str] = None
    computation_ref: Optional[str] = None
    model_refs: list[str] = Field(default_factory=list)
    generated_output_rights_ref: Optional[str] = None
    effective_rights_decision_ref: Optional[str] = None
    tenant_id: Optional[str] = None


class RightsContext(BaseModel):
    """Rights context attached to projection/exploration outputs (§12).

    A projection never upgrades rights by rendering data; these fields describe
    the availability, restrictions and suppressions that were applied.
    """

    model_config = ConfigDict(extra="ignore")

    availability: str = "available"
    restrictions: list[str] = Field(default_factory=list)
    source_rights_refs: list[str] = Field(default_factory=list)
    effective_decision_ref: Optional[str] = None
    exportable: bool = False
    suppressions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class RightsImpact(BaseModel):
    """Rights-impact record for revocation/deletion/restatement (§10).

    ``tenant_id`` is an optional scoping superset. ``required_action`` uses the
    canonical lifecycle vocabulary (blueprint §9). ``remediation_state`` is one
    of :data:`ALLOWED_REMEDIATION_STATES`; anything else is "unknown" and is
    never treated as complete.
    """

    model_config = ConfigDict(extra="ignore")

    impact_id: str = Field(default_factory=_rimp_id)
    tenant_id: Optional[str] = None
    grant_id: Optional[str] = None
    artifact_ref: str
    dependency_kind: Optional[str] = None
    required_action: Optional[LifecycleAction] = None
    remediation_state: Optional[str] = None
    responsible_authority: Optional[str] = None
    current_state: Optional[str] = None
    evidence_refs: list[str] = Field(default_factory=list)

    def normalize_remediation_state(self, state: str) -> str:
        """Coerce a remediation state into the canonical vocabulary.

        Unknown values become ``"unknown"`` (fail closed — never silently
        "complete").
        """
        normalized = (state or "").strip().lower()
        return normalized if normalized in ALLOWED_REMEDIATION_STATES else "unknown"
