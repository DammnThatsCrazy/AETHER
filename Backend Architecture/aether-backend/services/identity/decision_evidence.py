"""Identity decision evidence records (prompt §3.3).

Every identity decision the resolver (or an operator flow) makes should leave a
durable, queryable *evidence* trail: which signals were used, which were
excluded, what events/connectors sourced them, the consent snapshot in force,
the policy decision it came from, and the confidence that backed it.

This module is intentionally additive and fail-closed:

* The record is an append-only :class:`IdentityDecisionEvidence` dataclass.
* Persistence goes through :class:`IdentityDecisionEvidenceRepository`, which
  subclasses the shared tenant-scoped ``_ScopedRepo`` so reads stay isolated.
* :class:`IdentityDecisionEvidenceService.record_decision` builds and stores a
  record; callers wrap it so a persistence failure never breaks resolution.

Nothing here mutates the identity graph — it only observes decisions.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from shared.common.common import utc_now

from services.security.repositories import _ScopedRepo

from .hashing import hash_value
from .models import ConfidenceTier, MergeDecision


# Version of the merge-policy logic that produced a decision. Bumped when the
# policy's decision surface changes so evidence rows remain interpretable.
MERGE_POLICY_VERSION = "1.0.0"

# Backing table for evidence rows (JSONB, tenant-scoped).
EVIDENCE_TABLE = "identity_decision_evidence"


class DecisionType(str, Enum):
    """Canonical decision types that can produce an evidence record."""

    AUTO_LINK = "auto_link"
    CANDIDATE_LINK = "candidate_link"
    MANUAL_LINK = "manual_link"
    MERGE = "merge"
    SPLIT = "split"
    SUPPRESS = "suppress"
    REJECT = "reject"
    CONFLICT = "conflict"
    FREEZE = "freeze"
    RECOMPUTE = "recompute"


# Review status defaults keyed by decision type. Automatic, terminal decisions
# need no human review; ambiguous ones are queued ("pending"); operator-driven
# ones are already human-approved.
_DEFAULT_REVIEW_STATUS: dict[DecisionType, str] = {
    DecisionType.AUTO_LINK: "auto",
    DecisionType.MERGE: "auto",
    DecisionType.REJECT: "auto",
    DecisionType.SUPPRESS: "auto",
    DecisionType.RECOMPUTE: "auto",
    DecisionType.CANDIDATE_LINK: "pending",
    DecisionType.CONFLICT: "pending",
    DecisionType.FREEZE: "pending",
    DecisionType.MANUAL_LINK: "approved",
    DecisionType.SPLIT: "approved",
}


def coerce_decision_type(value: Any) -> DecisionType:
    """Coerce a str/DecisionType into a DecisionType (fail-closed → CONFLICT).

    An unrecognised value is treated as CONFLICT so an unknown decision is
    routed to review rather than silently recorded as benign.
    """
    if isinstance(value, DecisionType):
        return value
    try:
        return DecisionType(str(getattr(value, "value", value)))
    except ValueError:
        return DecisionType.CONFLICT


def decision_type_from_merge_decision(
    decision: MergeDecision, has_conflict: bool = False
) -> DecisionType:
    """Map a policy :class:`MergeDecision` onto an evidence :class:`DecisionType`.

    * ``CREATE`` / ``LINK`` → ``auto_link`` (signals auto-bound to an entity).
    * ``MERGE`` → ``merge``.
    * ``CANDIDATE`` → ``conflict`` when a conflicting strong alias was found,
      otherwise ``candidate_link``.
    * ``REJECT`` / ``BLOCKED`` → ``reject`` (nothing was linked).
    * ``NOOP`` → ``reject`` (defensive; the resolver returns before recording).
    """
    mapping = {
        MergeDecision.CREATE: DecisionType.AUTO_LINK,
        MergeDecision.LINK: DecisionType.AUTO_LINK,
        MergeDecision.MERGE: DecisionType.MERGE,
        MergeDecision.REJECT: DecisionType.REJECT,
        MergeDecision.BLOCKED: DecisionType.REJECT,
        MergeDecision.NOOP: DecisionType.REJECT,
    }
    if decision == MergeDecision.CANDIDATE:
        return DecisionType.CONFLICT if has_conflict else DecisionType.CANDIDATE_LINK
    return mapping.get(decision, DecisionType.CONFLICT)


def _default_review_status(decision_type: DecisionType, operator_id: str) -> str:
    status = _DEFAULT_REVIEW_STATUS.get(decision_type, "pending")
    # An operator initiating an otherwise-automatic decision means it is
    # already human-approved.
    if operator_id and status == "auto":
        return "approved"
    return status


def hash_consent_snapshot(consent_snapshot: Optional[dict]) -> str:
    """Deterministic hash of a consent snapshot (empty string when absent)."""
    if not consent_snapshot:
        return ""
    canonical = json.dumps(consent_snapshot, sort_keys=True, default=str)
    return hash_value(canonical, scope="consent_snapshot")


def _dedupe(items: Optional[list[str]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items or []:
        s = str(getattr(it, "value", it))
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


@dataclass
class IdentityDecisionEvidence:
    """Append-only evidence for a single identity decision (prompt §3.3)."""

    decision_id: str
    tenant_id: str
    entity_id: str
    decision_type: DecisionType
    subject_entity_id: str = ""
    signals_used: list[str] = field(default_factory=list)
    signals_excluded: list[str] = field(default_factory=list)
    source_events: list[str] = field(default_factory=list)
    source_connectors: list[str] = field(default_factory=list)
    consent_snapshot_hash: str = ""
    policy_decision_id: Optional[str] = None
    confidence_score: float = 0.0
    confidence_tier: str = ""
    merge_policy_version: str = MERGE_POLICY_VERSION
    operator_id: str = ""
    review_status: str = "pending"
    created_at: str = ""

    def to_record(self) -> dict[str, Any]:
        """Serialize to a JSONB-friendly persistence record."""
        return {
            "decision_id": self.decision_id,
            "id": self.decision_id,
            "tenant_id": self.tenant_id,
            "entity_id": self.entity_id,
            "subject_entity_id": self.subject_entity_id,
            "decision_type": self.decision_type.value,
            "signals_used": list(self.signals_used),
            "signals_excluded": list(self.signals_excluded),
            "source_events": list(self.source_events),
            "source_connectors": list(self.source_connectors),
            "consent_snapshot_hash": self.consent_snapshot_hash,
            "policy_decision_id": self.policy_decision_id,
            "confidence_score": self.confidence_score,
            "confidence_tier": self.confidence_tier,
            "merge_policy_version": self.merge_policy_version,
            "operator_id": self.operator_id,
            "review_status": self.review_status,
            "created_at": self.created_at,
        }


class IdentityDecisionEvidenceRepository(_ScopedRepo):
    """Tenant-scoped persistence for identity decision evidence rows."""

    def __init__(self) -> None:
        super().__init__(EVIDENCE_TABLE)

    async def record(self, evidence: IdentityDecisionEvidence) -> dict:
        return await self.insert(evidence.decision_id, evidence.to_record())

    async def list_for_entity(
        self, tenant_id: str, entity_id: str, limit: int = 100
    ) -> list[dict]:
        return await self.list_for_tenant(
            tenant_id, limit=limit, extra={"entity_id": entity_id}
        )

    async def get_for_tenant(
        self, tenant_id: str, decision_id: str
    ) -> Optional[dict]:
        record = await self.find_by_id(decision_id)
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return record


class IdentityDecisionEvidenceService:
    """Builds and persists :class:`IdentityDecisionEvidence` records."""

    def __init__(
        self, repo: Optional[IdentityDecisionEvidenceRepository] = None
    ) -> None:
        self._repo = repo or IdentityDecisionEvidenceRepository()

    async def record_decision(
        self,
        *,
        tenant_id: str,
        entity_id: str,
        decision_type: Any,
        subject_entity_id: str = "",
        signals_used: Optional[list] = None,
        signals_excluded: Optional[list] = None,
        source_events: Optional[list[str]] = None,
        source_connectors: Optional[list[str]] = None,
        consent_snapshot: Optional[dict] = None,
        consent_snapshot_hash: Optional[str] = None,
        policy_decision_id: Optional[str] = None,
        confidence_score: float = 0.0,
        confidence_tier: Any = "",
        merge_policy_version: str = MERGE_POLICY_VERSION,
        operator_id: str = "",
        review_status: Optional[str] = None,
        decision_id: Optional[str] = None,
    ) -> IdentityDecisionEvidence:
        """Build an evidence record, persist it, and return it.

        Fail-closed on decision-type: an unrecognised type is recorded as
        ``conflict`` (queued for review) rather than silently dropped.
        """
        dtype = coerce_decision_type(decision_type)
        tier = str(getattr(confidence_tier, "value", confidence_tier) or "")
        chash = (
            consent_snapshot_hash
            if consent_snapshot_hash is not None
            else hash_consent_snapshot(consent_snapshot)
        )
        evidence = IdentityDecisionEvidence(
            decision_id=decision_id or str(uuid.uuid4()),
            tenant_id=tenant_id,
            entity_id=entity_id,
            subject_entity_id=subject_entity_id or entity_id,
            decision_type=dtype,
            signals_used=_dedupe(signals_used),
            signals_excluded=_dedupe(signals_excluded),
            source_events=_dedupe(source_events),
            source_connectors=_dedupe(source_connectors),
            consent_snapshot_hash=chash,
            policy_decision_id=policy_decision_id,
            confidence_score=float(confidence_score),
            confidence_tier=tier,
            merge_policy_version=merge_policy_version,
            operator_id=operator_id,
            review_status=(
                review_status
                if review_status is not None
                else _default_review_status(dtype, operator_id)
            ),
            created_at=utc_now().isoformat(),
        )
        await self._repo.record(evidence)
        return evidence

    async def list_for_entity(
        self, tenant_id: str, entity_id: str, limit: int = 100
    ) -> list[dict]:
        return await self._repo.list_for_entity(tenant_id, entity_id, limit=limit)
