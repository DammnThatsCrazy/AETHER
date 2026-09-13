"""Relationship promotion -> graph mutation gateway (Social360 + Relationship Fidelity M6).

Milestone M6 (blueprint §§29-30). Relationship promotion is a small, honest
state machine that turns an evidence-backed relationship-predicate candidate
into a governed graph edge -- written ONLY through the canonical
:class:`shared.graph.mutation_gateway.GraphMutationGateway` (via
:func:`shared.graph.mutation_intents.edge_intent` and
:func:`revocation_intent`), mirroring the canonical
``services/semantic_intelligence/graph_projector.py``. It never writes a graph
edge directly and it never writes durable Gold tables (no DDL / no alembic).

The decision is bounded and evidence-honest:

* A candidate whose evidence does not clear its predicate's registry
  ``defaultEvidenceRequirements`` is reported BELOW_FLOOR / INSUFFICIENT and is
  never promoted -- unknown is never treated as zero, and a contested candidate
  (supporting AND contradicting observations) is surfaced as CONTRADICTED, never
  silently resolved.
* A declared evidence requirement the promotion code cannot evaluate (because
  the upstream evidence surface did not provide it, e.g. incentive-exposure
  context for ``CO_EXPOSED``) yields an explicit ``unevaluable`` reason -- the
  edge is not written and the reason records that the requirement was NOT met
  *because it was not assessed*, which is distinct from "assessed and absent".
* Promotion of a derived predicate (``MUTUAL_SOCIAL_CONNECTION``,
  ``RECIPROCAL_COMMUNICATION``, ...) is fed by the motif matcher
  (``motifs.py``), which supplies the upstream satisfied-conditions and binds
  the evidence refs to the motif's component edges.
* Every write is idempotent: the edge carries a deterministic
  ``idempotency_key`` derived from its natural key so re-promotion converges,
  and :func:`project_assertion` skips a live edge already carrying the same key.
* Revocation is a soft revoke through the gateway (never a hard delete).

Runtime is ROLLOUT-GATED OFF by default (``flags.relationship_promotion_enabled``);
with the flag off, :func:`evaluate_promotion` still returns its honest verdict
but the write helpers no-op with ``DISABLED`` so nothing reaches the graph.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from shared.common.common import utc_now
from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, get_graph_client
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, revocation_intent

from .evidence import EvidenceGroup
from .flags import relationship_promotion_enabled
from .relationship_registry import (
    is_registered,
    live_graph_edge_type,
    predicate_entry,
)

# WS-D item 1: typed RelationshipFact evidence carry to the mutation ledger.
from shared.backend_interpretation.flags import (  # noqa: E402
    correlation_first_class_enabled,
    relationship_fact_enabled,
)

# Canonical promotion policy ref recorded on every promoted assertion. The
# registry's per-predicate ``defaultEvidenceRequirements`` is the substantive
# policy; this ref names the M6 promotion policy that evaluates them.
PROMOTION_POLICY_REF = "promotion/evidence-group-v1"

# The registry's declared requirement keys the promotion evaluator understands.
# Every requirement a predicate declares must be accounted for -- either computed
# from the evidence group or supplied by the upstream (motif) caller -- before a
# candidate may be promoted.
_NUMERIC_FLOOR_KEYS = ("minimumIndependentObservations", "minimumIndependentContexts")
_BOOL_REQ_KEYS = (
    "requiresBidirectionalEvidence",
    "requiresOppositeDirectedEvidence",
    "corroborationRequired",
    "sharedMembershipRequired",
    "episodeIndependenceRequired",
    "incentiveExposureRequired",
    "agentChainRequired",
    "limitationsRecorded",
    "interactionVarietyConsidered",
)
_TEMPORAL_DISPERSION_KEYS = ("temporalDispersionRequired",)
_PROOF_FLOOR_KEY = "proofLevelFloor"

# Minimal temporal dispersion (distinct active days) accepted when a predicate
# declares ``temporalDispersionRequired``. Registry entries carry no day-count,
# so M6 promotion policy fixes a floor of 2 distinct days -- a single burst on
# one day is not "dispersion".
MIN_DISPERSION_DAYS = 2

# Proof-level acceptance for a raw observation against a predicate's
# ``proofLevelFloor``. ``aggregated_independent`` is an AGGREGATE standing (many
# independent raw observations), so raw observations at provider_observed and
# above satisfy it; ``verified_authoritative`` requires authoritative
# verification; ``inferred_with_limitations`` admits the flagged-limitation
# level. provider_declared is weaker than observed and does not satisfy an
# observed-or-better floor.
_PROOF_ACCEPT: dict[str, frozenset[str]] = {
    "provider_declared": frozenset(
        {"provider_declared", "provider_observed", "verified_authoritative", "aggregated_independent"}
    ),
    "provider_observed": frozenset({"provider_observed", "verified_authoritative", "aggregated_independent"}),
    "verified_authoritative": frozenset({"verified_authoritative"}),
    "aggregated_independent": frozenset({"provider_observed", "verified_authoritative", "aggregated_independent"}),
    "inferred_with_limitations": frozenset(
        {"provider_observed", "verified_authoritative", "aggregated_independent", "inferred_with_limitations"}
    ),
}


class PromotionVerdict(str, Enum):
    """Honest promotion decision for one relationship-predicate candidate."""

    PROMOTE = "promote"                      # floor cleared; edge should be written
    BELOW_FLOOR = "below_floor"              # evidence present but below the registry floor
    CONTRADICTED = "contradicted"            # supporting AND contradicting observations
    INSUFFICIENT = "insufficient"            # no/too-little evidence (unknown != zero)
    NOT_REGISTERED = "not_registered"        # predicate has no REGISTERED graph edge
    UNKNOWN_PREDICATE = "unknown_predicate"  # predicate not in the registry
    DISABLED = "disabled"                    # rollout flag off; write helpers no-op


# Reason codes attached to a verdict (dimension-style honest reasons).
class PromotionReason(str, Enum):
    FLOOR_MET = "evidence_floor_met"
    BELOW_INDEPENDENT_SOURCES = "below_minimum_independent_sources"
    BELOW_INDEPENDENT_CONTEXTS = "below_minimum_independent_contexts"
    BELOW_PROOF_FLOOR = "below_proof_level_floor"
    INSUFFICIENT_TEMPORAL_DISPERSION = "insufficient_temporal_dispersion"
    CONTRADICTION_PRESENT = "contradiction_present"
    NO_SUPPORTING_EVIDENCE = "no_supporting_evidence"
    NO_REGISTERED_EDGE = "no_registered_graph_edge"
    UNKNOWN_PREDICATE_ENTRY = "unknown_predicate_entry"
    REQ_UNEVALUABLE = "requirement_unevaluable_not_assessed"
    REQ_NOT_MET = "requirement_assessed_not_met"


# Sentinel used to mark a supplied-requirement that was NOT provided upstream:
# "unknown" is never conflated with "false" (unknown != zero doctrine).
_UNEVALUATED = object()


@dataclass(frozen=True)
class RelationshipAssertion:
    """A governed, evidence-backed relationship claim ready for the gateway.

    Produced only by an :class:`EvaluationResult` whose verdict is PROMOTE.
    """

    assertion_id: str
    tenant_id: str
    predicate: str
    edge_type: str
    source_entity_id: str
    target_entity_id: str
    confidence: float
    valid_from: str
    claim_ceiling: str
    promotion_policy: str
    evidence_refs: list[str] = field(default_factory=list)
    provenance: str = "relationship_promotion"
    actor_kind: str = "system"
    actor_id: str = "relationship_promotion"

    def idempotency_source_event_id(self) -> str:
        """Stable natural-key event id driving the edge's deterministic key."""
        return self.assertion_id


def assertion_natural_key(
    tenant_id: str, predicate: str, source_entity_id: str, target_entity_id: str
) -> str:
    raw = f"{tenant_id}:{predicate}:{source_entity_id}:{target_entity_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class EvaluationResult:
    """Outcome of evaluating one evidence group against its predicate's floor."""

    verdict: PromotionVerdict
    predicate: str
    source_entity_id: str
    target_entity_id: str
    reason: str
    unmet_requirements: list[str] = field(default_factory=list)
    effective_independent_sources: float = 0.0
    distinct_independent_sources: int = 0
    distinct_active_days: int = 0
    assertion: Optional[RelationshipAssertion] = None

    @property
    def promoted(self) -> bool:
        return self.verdict == PromotionVerdict.PROMOTE

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "predicate": self.predicate,
            "source_entity_id": self.source_entity_id,
            "target_entity_id": self.target_entity_id,
            "reason": self.reason,
            "unmet_requirements": self.unmet_requirements,
            "effective_independent_sources": self.effective_independent_sources,
            "distinct_independent_sources": self.distinct_independent_sources,
            "distinct_active_days": self.distinct_active_days,
            "assertion_id": self.assertion.assertion_id if self.assertion else None,
        }


def _claim_ceiling_for(entry: Optional[dict]) -> str:
    return str((entry or {}).get("claimTypeFloor") or "observed")


def evaluate_promotion(
    group: EvidenceGroup,
    *,
    tenant_id: str = "default",
    registry_entry: Optional[dict] = None,
    supplied_requirements: Optional[dict[str, bool]] = None,
) -> EvaluationResult:
    """Honestly evaluate one evidence group against its predicate's registry floor.

    ``supplied_requirements`` lets an upstream caller (the motif matcher, or a
    future IncentiveContext / context resolver) attest requirements the evidence
    group alone cannot compute -- ``requiresOppositeDirectedEvidence`` for a
    mutual motif, ``incentiveExposureRequired`` context, shared-membership /
    episode-independence context, etc. A declared requirement that is neither
    computed here nor supplied is ``REQ_UNEVALUABLE`` (never silently treated as
    met or unmet-as-false).
    """
    predicate = group.predicate
    if registry_entry is None:
        registry_entry = predicate_entry(predicate)
    if registry_entry is None:
        return EvaluationResult(
            verdict=PromotionVerdict.UNKNOWN_PREDICATE,
            predicate=predicate,
            source_entity_id=group.source_entity_id,
            target_entity_id=group.target_entity_id,
            reason=PromotionReason.UNKNOWN_PREDICATE_ENTRY.value,
        )
    if not is_registered(predicate):
        return EvaluationResult(
            verdict=PromotionVerdict.NOT_REGISTERED,
            predicate=predicate,
            source_entity_id=group.source_entity_id,
            target_entity_id=group.target_entity_id,
            reason=PromotionReason.NO_REGISTERED_EDGE.value,
        )
    edge_type = live_graph_edge_type(predicate)
    if edge_type is None:
        return EvaluationResult(
            verdict=PromotionVerdict.NOT_REGISTERED,
            predicate=predicate,
            source_entity_id=group.source_entity_id,
            target_entity_id=group.target_entity_id,
            reason=PromotionReason.NO_REGISTERED_EDGE.value,
        )

    supplied = dict(supplied_requirements or {})
    effective = group.effective_independent_sources
    unmet: list[str] = []

    # Honest contradiction gate first: a contested candidate never promotes.
    if group.has_contradiction:
        return EvaluationResult(
            verdict=PromotionVerdict.CONTRADICTED,
            predicate=predicate,
            source_entity_id=group.source_entity_id,
            target_entity_id=group.target_entity_id,
            reason=PromotionReason.CONTRADICTION_PRESENT.value,
            unmet_requirements=["contradiction_present"],
            effective_independent_sources=effective,
            distinct_independent_sources=group.distinct_support_sources,
            distinct_active_days=group.distinct_active_days,
        )
    if not group.supporting:
        return EvaluationResult(
            verdict=PromotionVerdict.INSUFFICIENT,
            predicate=predicate,
            source_entity_id=group.source_entity_id,
            target_entity_id=group.target_entity_id,
            reason=PromotionReason.NO_SUPPORTING_EVIDENCE.value,
            unmet_requirements=["no_supporting_evidence"],
            effective_independent_sources=effective,
            distinct_independent_sources=group.distinct_support_sources,
            distinct_active_days=group.distinct_active_days,
        )

    reqs = dict(registry_entry.get("defaultEvidenceRequirements") or {})
    reasons: list[str] = []

    def _unmet(label: str, reason: str) -> None:
        unmet.append(label)
        reasons.append(reason)

    # Numeric floors.
    for key in _NUMERIC_FLOOR_KEYS:
        raw = reqs.get(key)
        if raw is None:
            continue
        try:
            floor = float(raw)
        except (TypeError, ValueError):
            _unmet(key, PromotionReason.REQ_UNEVALUABLE.value)
            continue
        if key == "minimumIndependentObservations":
            if effective < floor:
                _unmet(key, PromotionReason.BELOW_INDEPENDENT_SOURCES.value)
        else:  # minimumIndependentContexts
            ctx_floor = int(floor)
            contexts = group.supplied_or_computed_contexts if hasattr(group, "supplied_or_computed_contexts") else None
            # Independent contexts are not computable from a plain evidence
            # group; only an upstream caller can attest them.
            contexts_value = supplied.get("minimumIndependentContexts", _UNEVALUATED)
            if contexts_value is _UNEVALUATED:
                _unmet(key, PromotionReason.REQ_UNEVALUABLE.value)
            elif int(contexts_value) < ctx_floor:
                _unmet(key, PromotionReason.BELOW_INDEPENDENT_CONTEXTS.value)

    # Temporal dispersion.
    if reqs.get("temporalDispersionRequired"):
        if group.distinct_active_days < MIN_DISPERSION_DAYS:
            _unmet("temporalDispersionRequired", PromotionReason.INSUFFICIENT_TEMPORAL_DISPERSION.value)

    # Proof-level floor.
    floor = reqs.get(_PROOF_FLOOR_KEY)
    if floor is not None:
        acceptable = _PROOF_ACCEPT.get(str(floor))
        if acceptable is None:
            _unmet(_PROOF_FLOOR_KEY, PromotionReason.REQ_UNEVALUABLE.value)
        elif not any(o.proof_level in acceptable for o in group.supporting):
            _unmet(_PROOF_FLOOR_KEY, PromotionReason.BELOW_PROOF_FLOOR.value)

    # Boolean requirements (computed here only when the evidence group carries
    # the state; otherwise supplied by upstream).
    for key in _BOOL_REQ_KEYS:
        if not reqs.get(key):
            continue
        value = supplied.get(key, _UNEVALUATED)
        if value is _UNEVALUATED:
            _unmet(key, PromotionReason.REQ_UNEVALUABLE.value)
        elif not value:
            _unmet(key, PromotionReason.REQ_NOT_MET.value)

    if unmet:
        return EvaluationResult(
            verdict=PromotionVerdict.BELOW_FLOOR,
            predicate=predicate,
            source_entity_id=group.source_entity_id,
            target_entity_id=group.target_entity_id,
            reason=reasons[0] if reasons else PromotionReason.REQ_NOT_MET.value,
            unmet_requirements=unmet,
            effective_independent_sources=effective,
            distinct_independent_sources=group.distinct_support_sources,
            distinct_active_days=group.distinct_active_days,
        )

    confidence = min(1.0, 0.5 + 0.1 * min(effective, 5.0))
    entry = registry_entry
    claim_ceiling = _claim_ceiling_for(entry)
    assertion = RelationshipAssertion(
        assertion_id=assertion_natural_key(tenant_id, predicate, group.source_entity_id, group.target_entity_id),
        tenant_id=tenant_id,
        predicate=predicate,
        edge_type=edge_type,
        source_entity_id=group.source_entity_id,
        target_entity_id=group.target_entity_id,
        confidence=round(confidence, 4),
        valid_from=utc_now().isoformat(),
        claim_ceiling=claim_ceiling,
        promotion_policy=PROMOTION_POLICY_REF,
        evidence_refs=[o.observation_id for o in group.supporting],
    )
    return EvaluationResult(
        verdict=PromotionVerdict.PROMOTE,
        predicate=predicate,
        source_entity_id=group.source_entity_id,
        target_entity_id=group.target_entity_id,
        reason=PromotionReason.FLOOR_MET.value,
        unmet_requirements=[],
        effective_independent_sources=effective,
        distinct_independent_sources=group.distinct_support_sources,
        distinct_active_days=group.distinct_active_days,
        assertion=assertion,
    )


def edge_from_assertion(assertion: RelationshipAssertion) -> Edge:
    """Build the governed, canonical edge for one assertion (graph_projector mirror)."""
    props = build_edge_properties(
        tenant_id=assertion.tenant_id,
        edge_type=assertion.edge_type,
        from_vertex_id=assertion.source_entity_id,
        to_vertex_id=assertion.target_entity_id,
        actor_kind=assertion.actor_kind,
        actor_id=assertion.actor_id,
        provenance=assertion.provenance,
        valid_from=assertion.valid_from,
        confidence=assertion.confidence,
        source_event_id=assertion.idempotency_source_event_id(),
        correlation_id=assertion.idempotency_source_event_id(),
    )
    extras: dict[str, Any] = {
        "tenantId": assertion.tenant_id,
        "relationship_predicate": assertion.predicate,
        "claim_ceiling": assertion.claim_ceiling,
        "promotion_policy": assertion.promotion_policy,
        "evidence_refs": assertion.evidence_refs,
    }
    props.update({k: v for k, v in extras.items() if v is not None})
    return Edge(
        edge_type=assertion.edge_type,
        from_vertex_id=assertion.source_entity_id,
        to_vertex_id=assertion.target_entity_id,
        properties=props,
    )


async def _already_projected(
    graph_client: Any,
    tenant_id: str,
    source: str,
    target: str,
    edge_type: str,
    idempotency_key: str,
) -> bool:
    existing = await graph_client.get_edges(source, edge_type=edge_type)
    return any(
        e.to_vertex_id == target
        and not (e.properties or {}).get("revoked")
        and str((e.properties or {}).get("tenant_id") or "") == tenant_id
        and str((e.properties or {}).get("idempotency_key") or "") == idempotency_key
        for e in existing
    )


async def project_assertion(
    assertion: RelationshipAssertion,
    *,
    gateway: Optional[GraphMutationGateway] = None,
    graph_client: Optional[Any] = None,
) -> str:
    """Write one promoted assertion to the graph through the gateway, idempotently.

    Returns a status string: ``projected`` when the edge was newly written,
    ``skipped_existing`` when a live edge already carries the deterministic
    idempotency key (convergent re-promotion), or ``disabled`` when the
    rollout flag is off (nothing is written). ``graph_client`` / ``gateway`` are
    injectable for tests.
    """
    if not relationship_promotion_enabled():
        return "disabled"
    graph_client = graph_client or get_graph_client()
    gw = gateway or GraphMutationGateway(graph_client=graph_client)
    edge = edge_from_assertion(assertion)
    key = str(edge.properties.get("idempotency_key") or "")
    if await _already_projected(
        graph_client,
        assertion.tenant_id,
        assertion.source_entity_id,
        assertion.target_entity_id,
        assertion.edge_type,
        key,
    ):
        return "skipped_existing"
    # WS-D item 1 (typed RelationshipFact + evidence_refs): when the WS-D
    # relationship-fact flag is ON, forward the assertion's per-signal
    # evidence_refs onto the gateway intent so the mutation LEDGER record (the
    # identity audit) carries them — today it drops them (evidence_refs=None).
    # OFF keeps the pre-WS-D call byte-for-byte identical.
    carry_ledger_evidence = relationship_fact_enabled()
    await gw.apply(
        edge_intent(
            edge,
            operation="edge_created",
            tenant_id=assertion.tenant_id,
            subject_kind="entity",
            subject_id=assertion.target_entity_id,
            causality_class="observed_sequence",
            evidence_refs=(
                assertion.evidence_refs if carry_ledger_evidence else None
            ),
            correlation_id=(
                str(edge.properties.get("correlation_id") or "")
                if carry_ledger_evidence
                else None
            ),
        )
    )
    # WS-D item 6 (correlation first-class): when enabled, the promoted edge's
    # correlation family is registered in the durable CorrelationRegistry so
    # correlation is a first-class registry row, not only an edge-property
    # string. Best-effort: a registry failure never fails the projection.
    if correlation_first_class_enabled():
        try:
            from shared.backend_interpretation.observe import (
                register_correlation_from_observation,
            )

            family_id = str(edge.properties.get("correlation_id") or "")
            if family_id:
                await register_correlation_from_observation(
                    assertion.tenant_id,
                    {
                        "correlation": {"correlation_id": family_id},
                        "event": {"id": family_id},
                        "source": {"type": "relationship_promotion"},
                    },
                )
        except Exception:  # noqa: BLE001 - registry write is best-effort
            pass
    return "projected"


async def revoke_assertion(
    assertion: RelationshipAssertion,
    *,
    reason: str = "relationship_evidence_contradicted",
    gateway: Optional[GraphMutationGateway] = None,
    graph_client: Optional[Any] = None,
) -> str:
    """Soft-revoke a previously promoted assertion through the gateway.

    Returns ``revoked`` when the revocation intent was applied, ``disabled``
    when the rollout flag is off (nothing is written), or ``noop`` when the
    promotion flag would gate the revoke but the caller already knows the write
    happened earlier under a different mode. ``graph_client`` / ``gateway`` are
    injectable for tests.
    """
    if not relationship_promotion_enabled():
        return "disabled"
    graph_client = graph_client or get_graph_client()
    gw = gateway or GraphMutationGateway(graph_client=graph_client)
    await gw.apply(
        revocation_intent(
            from_vertex_id=assertion.source_entity_id,
            to_vertex_id=assertion.target_entity_id,
            edge_type=assertion.edge_type,
            reason=reason,
            tenant_id=assertion.tenant_id,
            actor_kind="system",
            actor_id="relationship_promotion",
        )
    )
    return "revoked"


__all__ = [
    "PROMOTION_POLICY_REF",
    "PromotionVerdict",
    "PromotionReason",
    "RelationshipAssertion",
    "EvaluationResult",
    "assertion_natural_key",
    "evaluate_promotion",
    "edge_from_assertion",
    "project_assertion",
    "revoke_assertion",
]
