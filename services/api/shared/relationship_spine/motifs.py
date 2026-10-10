"""Deterministic relationship-motif matcher (Social360 + Relationship Fidelity M6).

Milestone M6 (blueprint §45). A relationship MOTIF is a higher-order structural
pattern over already-observed relationship edges. This module is a DETERMINISTIC
(no-LLM) matcher over the generated motif catalog
``generated_relationship_motif_registry`` (derived from
``packages/shared/contracts/relationship-motif-registry.json``): given the live
relationship edges currently projected in the graph, it enumerates every motif
instance whose ``requiredEdges`` all bind to distinct observed edges under a
consistent role assignment.

Design rules:

* The matcher never invents edges: every required edge of a motif must bind to a
  genuinely observed edge (self-loops are rejected). ``requiredEdges`` reference
  *predicates*; the matcher resolves each to a live ``EdgeType`` via
  :func:`shared.relationship_spine.relationship_registry.motif_observation_edge_type`
  (registered relationship predicates resolve through the registry -- ``FOLLOWS``
  to ``FOLLOWS_SOCIAL`` -- and bare graph edges such as ``DELEGATES_TO`` /
  ``ACTED_FOR`` resolve verbatim). A motif with an unresolvable required edge is
  unmatchable and reported with a reason, never silently approximated.
* Role assignment is globally consistent and enumerated deterministically
  (sorted match keys). Distinct motif roles may only bind to the same vertex
  when the observed structure permits it -- the matcher imposes no hidden
  inequality; the anti-degenerate constraint (a required edge is never a
  self-loop) is the only one it can honestly enforce without a vertex-kind
  catalog.
* Outputs are honest and bounded. A motif's ``outputKind`` is either
  ``RELATIONSHIP_PREDICATE`` (the motif is the *derived evidence* for promoting
  a registered relationship predicate -- feeds ``promotion.py``) or
  ``DERIVED_RELATIONSHIP_STATE`` (the motif emits a bounded derived-state
  indicator -- feeds ``motif_indicators.py`` under the reserved ``graph_motifs``
  authority). A relationship-predicate match is promoted ONLY if it clears its
  output predicate's registry evidence floor (:func:`promotion.evaluate_promotion`);
  otherwise the motif is honestly reported as detected-but-not-promotable.
* The motif registry does not carry the output predicate's endpoint roles, so
  M6 promotion policy fixes them in :data:`PREDICATE_OUTPUT_ENDPOINTS`. A
  predicate-output motif WITHOUT a policy entry is reported ``unevaluable`` --
  the matcher never fabricates endpoints.
* Runtime is ROLLOUT-GATED OFF (``flags.relationship_motifs_enabled``);
  emission helpers no-op when the flag is off.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from shared.common.common import utc_now

from .evidence import Observation
from .flags import relationship_motifs_enabled
from .promotion import (
    EvaluationResult,
    PromotionVerdict,
    RelationshipAssertion,
    evaluate_promotion,
)
from .relationship_registry import motif_observation_edge_type
from .generated_relationship_motif_registry import RELATIONSHIP_MOTIFS

OUTPUT_KIND_PREDICATE = "RELATIONSHIP_PREDICATE"
OUTPUT_KIND_DERIVED_STATE = "DERIVED_RELATIONSHIP_STATE"

# M6 promotion-policy endpoint roles for relationship-predicate-output motifs.
# The motif registry declares requiredEdges + outputPredicate but NOT which roles
# are the output predicate's two endpoints; promotion therefore needs a fixed,
# documented policy. Every RELATIONSHIP_PREDICATE-output motif MUST appear here
# (the module's self-test enforces it).
PREDICATE_OUTPUT_ENDPOINTS: dict[str, tuple[str, str]] = {
    "MUTUAL_SOCIAL_CONNECTION": ("source_entity", "target_entity"),
    "RECIPROCAL_COMMUNICATION": ("entity_a", "entity_b"),
    "RECURRING_CO_PRESENCE": ("entity_a", "entity_b"),
    "COMMUNITY_ASSOCIATION": ("entity_a", "entity_b"),
    "AGENT_MEDIATED_PRINCIPAL_INTERACTION": ("principal_a", "principal_b"),
    "PERSISTENT_MULTI_CONTEXT_ASSOCIATION": ("entity_a", "entity_b"),
}

# A ``PROMOTE``-bounded confidence for a motif-verified derived claim.
_MOTIF_CLAIM_CONFIDENCE_FLOOR = 0.6


def _digest(*parts: str) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class ObservedEdge:
    """One live relationship edge the matcher may bind a motif to."""

    edge_id: str
    edge_type: str
    source_vertex_id: str
    target_vertex_id: str
    valid_from: Optional[str] = None
    source_key: str = ""


@dataclass
class MotifMatch:
    """One bound instance of a relationship motif over observed edges."""

    motif_id: str
    motif_version: int
    output_kind: str
    output_predicate: Optional[str]
    output_state: Optional[str]
    output_claim_ceiling: str
    incentive_policy: str
    evidence_independence_policy: str
    roles: dict[str, str] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)  # bound required edges

    @property
    def match_key(self) -> str:
        """Deterministic identity: motif id + sorted bound vertex set."""
        return _digest(self.motif_id, *sorted(self.roles.values()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "motif_id": self.motif_id,
            "version": self.motif_version,
            "match_key": self.match_key,
            "output_kind": self.output_kind,
            "output_predicate": self.output_predicate,
            "output_state": self.output_state,
            "output_claim_ceiling": self.output_claim_ceiling,
            "incentive_policy": self.incentive_policy,
            "evidence_independence_policy": self.evidence_independence_policy,
            "roles": dict(sorted(self.roles.items())),
            "edges": [dict(e) for e in self.edges],
        }


def _index_observed(observed: Iterable[ObservedEdge]) -> dict[str, list[ObservedEdge]]:
    index: dict[str, list[ObservedEdge]] = {}
    for edge in observed:
        index.setdefault(edge.edge_type, []).append(edge)
    # Deterministic candidate order.
    for key in index:
        index[key].sort(key=lambda e: (e.source_vertex_id, e.target_vertex_id, e.edge_id))
    return index


def _resolvable_requirements(motif: dict[str, Any]) -> tuple[Optional[list[dict]], list[str]]:
    """Resolve a motif's requiredEdges to live edge types.

    Returns (resolved_requirements, reasons). When any required edge's predicate
    resolves to nothing the motif is unmatchable in the current graph.
    """
    resolved: list[dict] = []
    for req in motif.get("requiredEdges", []):
        edge_type = motif_observation_edge_type(str(req["predicate"]))
        if edge_type is None:
            return None, [f"unresolvable_required_predicate={req['predicate']}"]
        resolved.append(
            {
                "source_role": req["sourceRole"],
                "target_role": req["targetRole"],
                "predicate": req["predicate"],
                "edge_type": edge_type,
            }
        )
    return resolved, []


def _bind_motif(
    motif: dict[str, Any],
    requirements: list[dict],
    index: dict[str, list[ObservedEdge]],
    cap: int = 50,
) -> list[MotifMatch]:
    """Enumerate role-consistent bindings of a motif over observed edges.

    Standard backtracking: process required edges in order, binding their two
    roles to an observed edge's endpoints. Each required edge binds to a DISTINCT
    observed edge and is never a self-loop. Results are capped at ``cap`` so a
    pathological dense graph cannot explode the caller.
    """
    matches: list[MotifMatch] = []
    role_to_vertex: dict[str, str] = {}
    used_edges: set[str] = set()
    bound_edges: list[dict[str, Any]] = []
    by_role_occurrences: dict[str, int] = {}
    # Pre-count how often each role appears so we can free bindings safely.
    occurrence_count: dict[str, int] = {}
    for req in requirements:
        occurrence_count[req["source_role"]] = occurrence_count.get(req["source_role"], 0) + 1
        occurrence_count[req["target_role"]] = occurrence_count.get(req["target_role"], 0) + 1
    role_assignments_used: dict[str, int] = {r: 0 for r in occurrence_count}
    # vertex currently bound per role (recomputed lazily is not enough; keep a
    # stack so we can backtrack cleanly when a role is shared by many edges).

    # We track each binding as: when we place edge i we assign role -> vertex.
    # A role appearing multiple times must keep the SAME vertex; rather than
    # complicate undo, we record assignments per (role, occurrence_index).
    # Simpler: maintain role_to_vertex plus a per-role count of how many placed
    # edges reference it; only clear the vertex when the count drops to 0.
    per_role_refs: dict[str, int] = {}

    def _current_vertex(role: str) -> Optional[str]:
        return role_to_vertex.get(role)

    def _place(edge_index: int) -> None:
        if len(matches) >= cap:
            return
        if edge_index >= len(requirements):
            matches.append(
                MotifMatch(
                    motif_id=str(motif["motifId"]),
                    motif_version=int(motif.get("version") or 1),
                    output_kind=str(motif.get("outputKind") or OUTPUT_KIND_PREDICATE),
                    output_predicate=motif.get("outputPredicate"),
                    output_state=motif.get("outputState"),
                    output_claim_ceiling=str(motif.get("outputClaimCeiling") or "derived"),
                    incentive_policy=str(motif.get("incentivePolicy") or "NONE_REQUIRED"),
                    evidence_independence_policy=str(
                        motif.get("evidenceIndependencePolicy") or "INDEPENDENT_OBSERVATIONS_REQUIRED"
                    ),
                    roles=dict(role_to_vertex),
                    edges=[dict(e) for e in bound_edges],
                )
            )
            return

        req = requirements[edge_index]
        src_role = req["source_role"]
        tgt_role = req["target_role"]
        edge_type = req["edge_type"]
        candidates = index.get(edge_type, [])
        src_bound = _current_vertex(src_role)
        tgt_bound = _current_vertex(tgt_role)
        for edge in candidates:
            if edge.edge_id in used_edges:
                continue
            if edge.source_vertex_id == edge.target_vertex_id:
                continue
            if src_bound is not None and edge.source_vertex_id != src_bound:
                continue
            if tgt_bound is not None and edge.target_vertex_id != tgt_bound:
                continue
            # New role binding must agree if the other endpoint is already bound
            # to the same vertex (that would be a self-loop style collision is
            # already excluded above when both bound; here just place).
            if src_bound is not None and tgt_bound is not None and src_bound == tgt_bound:
                continue
            # place
            placed_src = src_role not in role_to_vertex
            placed_tgt = tgt_role not in role_to_vertex
            if placed_src:
                role_to_vertex[src_role] = edge.source_vertex_id
            if placed_tgt:
                role_to_vertex[tgt_role] = edge.target_vertex_id
            used_edges.add(edge.edge_id)
            bound_edges.append(
                {
                    "predicate": req["predicate"],
                    "edge_type": edge_type,
                    "source_role": src_role,
                    "target_role": tgt_role,
                    "source_vertex_id": edge.source_vertex_id,
                    "target_vertex_id": edge.target_vertex_id,
                    "edge_id": edge.edge_id,
                    "source_key": edge.source_key or edge.edge_id,
                    "valid_from": edge.valid_from,
                }
            )
            _place(edge_index + 1)
            bound_edges.pop()
            used_edges.remove(edge.edge_id)
            if placed_tgt:
                del role_to_vertex[tgt_role]
            if placed_src:
                del role_to_vertex[src_role]
            if len(matches) >= cap:
                return

    _place(0)
    # Deterministic ordering.
    matches.sort(key=lambda m: m.match_key)
    return matches


def detect_motif_instances(
    motif: dict[str, Any],
    observed: Iterable[ObservedEdge],
    cap: int = 50,
) -> tuple[list[MotifMatch], list[str]]:
    """Enumerate all instances of ONE motif over the observed edges.

    Returns (matches, reasons); a motif with an unresolvable required edge is an
    empty match list with an honest reason.
    """
    requirements, reasons = _resolvable_requirements(motif)
    if requirements is None:
        return [], reasons
    index = _index_observed(observed)
    matches = _bind_motif(motif, requirements, index, cap=cap)
    # Orientation mirrors bind the SAME observed edges to swapped role labels
    # (e.g. MUTUAL_SOCIAL_CONNECTION detected as source=a OR source=b). Those are
    # ONE structural instance, not two: dedupe by bound edge set, keeping a
    # deterministic representative.
    best_by_edges: dict[frozenset[str], MotifMatch] = {}
    for m in matches:
        key = frozenset(e["edge_id"] for e in m.edges)
        prev = best_by_edges.get(key)
        if prev is None or m.match_key < prev.match_key:
            best_by_edges[key] = m
    deduped = sorted(best_by_edges.values(), key=lambda m: m.match_key)
    return deduped, []


def detect_motifs(
    observed: Iterable[ObservedEdge],
    *,
    motif_filter: Optional[Iterable[str]] = None,
    cap_per_motif: int = 50,
) -> dict[str, list[MotifMatch]]:
    """Deterministically match every catalog motif (or a filtered subset).

    Returns {motifId: [matches]}. Unmatchable motifs (unresolvable required
    edge) yield an empty list -- the caller can ask :func:`motif_matchability`
    for the honest per-motif reason.
    """
    wanted = set(motif_filter) if motif_filter is not None else None
    result: dict[str, list[MotifMatch]] = {}
    for motif in RELATIONSHIP_MOTIFS:
        motif_id = str(motif["motifId"])
        if wanted is not None and motif_id not in wanted:
            continue
        matches, _ = detect_motif_instances(motif, observed, cap=cap_per_motif)
        result[motif_id] = matches
    return result


def motif_matchability(observed: Iterable[ObservedEdge]) -> dict[str, list[str]]:
    """Per-motif reason when the motif cannot match over the observed edges.

    A motif that simply has no matching instance in the current edge set is
    reported with an empty reason list (absence is ``unknown``, never a
    definitive negative); a motif whose required predicate resolves to no live
    EdgeType reports ``unresolvable_required_predicate=...`` so the caller can
    distinguish "not present" from "cannot exist here yet".
    """
    index = _index_observed(observed)
    reasons_map: dict[str, list[str]] = {}
    for motif in RELATIONSHIP_MOTIFS:
        requirements, reasons = _resolvable_requirements(motif)
        if requirements is None:
            reasons_map[str(motif["motifId"])] = reasons
            continue
        has_edge = any(index.get(r["edge_type"]) for r in requirements)
        if not has_edge:
            reasons_map[str(motif["motifId"])] = ["no_required_edge_type_present"]
    return reasons_map


# ── Relationship-predicate output -> promotion feed ─────────────────────────

def _endpoint_pair(match: MotifMatch) -> Optional[tuple[str, str]]:
    """The output predicate's (source, target) endpoints for a predicate match.

    Returns None (honest "unevaluable") when the motif is a predicate output
    with no M6 promotion-policy endpoint entry -- never a fabricated pair.
    """
    if match.output_kind != OUTPUT_KIND_PREDICATE or not match.output_predicate:
        return None
    pair = PREDICATE_OUTPUT_ENDPOINTS.get(match.motif_id)
    if pair is None:
        return None
    src_role, tgt_role = pair
    if src_role not in match.roles or tgt_role not in match.roles:
        return None
    return (match.roles[src_role], match.roles[tgt_role])


def _synthetic_group(match: MotifMatch) -> Optional[Any]:
    """Build the derived-candidate EvidenceGroup for a predicate-output match.

    Each bound component edge becomes one supporting observation whose
    ``source_key`` is the component edge's own source lineage (so correlated
    edges damp) and whose ``observed_at`` is the component edge's ``valid_from``
    (so temporal dispersion remains honest -- two same-day component edges do
    not fabricate dispersion). ``proof_level`` is ``aggregated_independent``
    because each component edge is itself an independently promoted fact.
    """
    if match.output_kind != OUTPUT_KIND_PREDICATE or not match.output_predicate:
        return None
    pair = _endpoint_pair(match)
    if pair is None:
        return None
    source, target = pair
    obs: list[Observation] = []
    for i, edge in enumerate(match.edges):
        valid_from = edge.get("valid_from") or utc_now().isoformat()
        obs.append(
            Observation(
                observation_id=str(edge["edge_id"]),
                predicate=str(match.output_predicate),
                source_entity_id=str(edge["source_vertex_id"]),
                target_entity_id=str(edge["target_vertex_id"]),
                source_key=str(edge.get("source_key") or edge["edge_id"]),
                observed_at=str(valid_from),
                supports_predicate=True,
                correlation_family=None,
                proof_level="aggregated_independent",
                evidence_basis="motif_component_edge",
            )
        )
    from .evidence import EvidenceGroup

    group = EvidenceGroup(
        predicate=str(match.output_predicate),
        source_entity_id=source,
        target_entity_id=target,
        supporting=obs,
        contradicting=[],
    )
    return group


def _canonical_pair(pair: tuple[str, str]) -> tuple[str, str]:
    """Deterministic (source, target) orientation for a derived pair edge.

    The derived predicates promoted from motifs are RECIPROCAL_PAIR /
    UNDIRECTED relationship facts (mutual connection, reciprocal communication,
    community association, ...). Their graph edge carries no natural direction,
    so M6 promotion policy stores them in the sorted (min, max) orientation to
    guarantee one canonical edge per unordered pair (no duplicate a->b / b->a).
    """
    return (min(pair[0], pair[1]), max(pair[0], pair[1]))


def promotion_candidates_for_matches(
    matches: Iterable[MotifMatch],
    *,
    tenant_id: str = "default",
) -> list[EvaluationResult]:
    """Evaluate relationship-predicate motif matches for promotion (Step 3 feed).

    Every predicate-output match with a resolvable endpoint pair contributes its
    bound component edges to that UNORDERED pair. Matches whose canonical pair
    collides (orientation mirrors, or a second structural route to the same
    derived relationship) are merged so ONE promotion candidate is evaluated per
    derived relationship, with the union of the component edges as its evidence
    (deduplicated by edge id). The candidate runs through
    :func:`promotion.evaluate_promotion` with the requirements the motif
    structure itself guarantees (bidirectional/opposite structure, corroborating
    distinct component edges, distinct relationship contexts) supplied as met.

    A candidate that does not clear the floor yields an honest BELOW_FLOOR
    result (detected-but-not-promotable), never a fabricated edge.
    """
    from collections import defaultdict

    edges_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        if match.output_kind != OUTPUT_KIND_PREDICATE or not match.output_predicate:
            continue
        pair = _endpoint_pair(match)
        if pair is None:
            continue
        cpair = _canonical_pair(pair)
        seen: set[str] = {e["edge_id"] for e in edges_by_pair[cpair]}
        for edge in match.edges:
            if edge["edge_id"] in seen:
                continue
            seen.add(edge["edge_id"])
            tagged = dict(edge)
            tagged["output_predicate"] = str(match.output_predicate)
            tagged["motif_id"] = match.motif_id
            edges_by_pair[cpair].append(tagged)

    results: list[EvaluationResult] = []
    for pair, edges in edges_by_pair.items():
        result = _evaluate_pair(edges, pair, tenant_id=tenant_id)
        results.append(result)
    results.sort(key=lambda r: (r.predicate, r.source_entity_id, r.target_entity_id))
    return results



def _structural_attestations(
    motif_ids: set[str],
    edges: list[dict[str, Any]],
) -> dict[str, object]:
    """Attest the evidence requirements a bound motif structure guarantees.

    A motif match is the DERIVED evidence for its output predicate. Which
    structural guarantees it can honestly attest depends on the motif:

    * a reciprocal motif (MUTUAL_SOCIAL_CONNECTION, RECIPROCAL_COMMUNICATION)
      bound BOTH directions -- opposite/bidirectional requirements are met by
      construction;
    * COMMUNITY_ASSOCIATION binds two memberships in a SHARED community --
      shared-membership is met by construction;
    * AGENT_MEDIATED_PRINCIPAL_INTERACTION binds a delegation/agency/payment
      agent chain -- agent-chain is met by construction;
    * RECURRING_CO_PRESENCE attests EPISODE independence only when the bound
      co-presence edges span at least two distinct days (two same-day edges are
      one episode, never "recurring");
    * corroboration is always attested (distinct bound component edges), and the
      number of distinct component PREDICATES bound is the honest count of
      distinct relationship contexts (PERSISTENT_MULTI_CONTEXT_ASSOCIATION).
    """
    attest: dict[str, object] = {}
    if motif_ids & {"MUTUAL_SOCIAL_CONNECTION", "RECIPROCAL_COMMUNICATION"}:
        attest["requiresOppositeDirectedEvidence"] = True
        attest["requiresBidirectionalEvidence"] = True
    if "COMMUNITY_ASSOCIATION" in motif_ids:
        attest["sharedMembershipRequired"] = True
    if "AGENT_MEDIATED_PRINCIPAL_INTERACTION" in motif_ids:
        attest["agentChainRequired"] = True
    if "RECURRING_CO_PRESENCE" in motif_ids:
        days = {str(e.get("valid_from") or "")[:10] for e in edges}
        days.discard("")
        attest["episodeIndependenceRequired"] = len(days) >= 2
    attest["corroborationRequired"] = True
    attest["minimumIndependentContexts"] = len({e["predicate"] for e in edges})
    return attest



def _evaluate_pair(
    edges: list[dict[str, Any]],
    pair: tuple[str, str],
    *,
    tenant_id: str = "default",
) -> EvaluationResult:
    """Evaluate ONE derived candidate (all motif instances bound to a pair)."""
    source, target = pair
    from .evidence import EvidenceGroup

    out_predicates = {str(e["output_predicate"]) for e in edges if e.get("output_predicate")}
    if not out_predicates:
        # Honest unevaluable: no output predicate tagged (defensive; merge tags
        # it). We refuse to guess an edge type from component predicates.
        return EvaluationResult(
            verdict=PromotionVerdict.BELOW_FLOOR,
            predicate=str(edges[0]["predicate"]),
            source_entity_id=source,
            target_entity_id=target,
            reason="unevaluable_output_predicate",
        )
    predicate = sorted(out_predicates)[0]
    obs: list[Observation] = []
    for edge in edges:
        obs.append(
            Observation(
                observation_id=str(edge["edge_id"]),
                predicate=predicate,
                source_entity_id=str(edge["source_vertex_id"]),
                target_entity_id=str(edge["target_vertex_id"]),
                source_key=str(edge.get("source_key") or edge["edge_id"]),
                observed_at=str(edge.get("valid_from") or utc_now().isoformat()),
                supports_predicate=True,
                correlation_family=None,
                proof_level="aggregated_independent",
                evidence_basis="motif_component_edge",
            )
        )
    group = EvidenceGroup(
        predicate=predicate,
        source_entity_id=source,
        target_entity_id=target,
        supporting=obs,
        contradicting=[],
    )
    motif_ids = {str(e["motif_id"]) for e in edges if e.get("motif_id")}
    supplied = _structural_attestations(motif_ids, edges)
    return evaluate_promotion(group, tenant_id=tenant_id, supplied_requirements=supplied)


def relationship_assertions_for_matches(
    matches: Iterable[MotifMatch],
    *,
    tenant_id: str = "default",
) -> list[RelationshipAssertion]:
    """Promotable assertions across predicate-output motif matches (Step 3 feed).

    Delegates to :func:`promotion_candidates_for_matches` (one candidate per
    unordered derived pair) and returns only the PROMOTE assertions. Detected
    but below-floor candidates are never written and are surfaced in the
    :class:`promotion.EvaluationResult` list instead.
    """
    assertions: list[RelationshipAssertion] = []
    for result in promotion_candidates_for_matches(matches, tenant_id=tenant_id):
        if result.promoted and result.assertion is not None:
            assertions.append(result.assertion)
    return assertions


def promotion_result_for_match(
    match: MotifMatch,
    *,
    tenant_id: str = "default",
) -> Optional[EvaluationResult]:
    """Convenience: promotion evaluation for a single match's canonical pair.

    Kept for callers/tests that operate on one match at a time; returns the
    evaluation for that match's (merged) canonical pair, or None when the match
    is not a predicate output / has unevaluable endpoints.
    """
    if match.output_kind != OUTPUT_KIND_PREDICATE or not match.output_predicate:
        return None
    results = promotion_candidates_for_matches([match], tenant_id=tenant_id)
    return results[0] if results else None



def motif_matches_enabled() -> bool:
    return relationship_motifs_enabled()


__all__ = [
    "OUTPUT_KIND_PREDICATE",
    "OUTPUT_KIND_DERIVED_STATE",
    "PREDICATE_OUTPUT_ENDPOINTS",
    "ObservedEdge",
    "MotifMatch",
    "detect_motif_instances",
    "detect_motifs",
    "promotion_candidates_for_matches",
    "motif_matchability",
    "promotion_result_for_match",
    "relationship_assertions_for_matches",
    "motif_matches_enabled",
]
