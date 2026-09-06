"""Aether Shared — @aether/relationship_spine/path_fidelity
M8 fidelity-aware path scoring layer (epistemic-ceiling hop contract).

This module extends *scoring* on top of the existing traversal engine
(``shared/graph/traversal.py``) and its numeric scorer
(``shared/graph/path_scoring.py``). It does NOT replace or modify either one:
the traversal engine, ``path_scoring.score_path`` output contract and the
``services.operational_intelligence`` ``RelationshipPath`` DTO shape are all
left untouched. This layer is meant to be *composed with* a
``RelationshipPath``/``PathScoreBreakdown`` by a caller that opts in.

Governing invariant (release-blocking, blueprint ``social360.md``):
    Multi-hop paths do not manufacture truth — a path cannot exceed the
    epistemic ceiling of its weakest material hop.

What this module adds:

1. EPISTEMIC-CEILING HOP CONTRACT
   Each material hop carries an epistemic authority derived from the governed
   relationship-predicate registry's ``transitivityClasses``. A hop is
   *material* whenever it is load-bearing for the path's claim:
     - in a single-hop path the one hop carries a direct fact;
     - in a multi-hop path EVERY hop (including the two endpoints) is being
       used transitively to infer that source and target are connected.
   A ``PATH_COMPOSABLE`` observed hop and an ``INFERENTIAL_ONLY`` hop carry
   different ceilings, and a multi-hop path that would rely on a
   ``NON_TRANSITIVE`` predicate for transitive inference is rejected (strict,
   default) or down-weighted to its honest ceiling. A hop whose predicate is
   absent from the governed registry cannot certify composition, so the path is
   not certified (never fabricated upward).

2. SNAPSHOT STALENESS
   Hops carry temporal windows (bitemporal discipline from ``shared/temporal``).
   An explicit observation instant ages against the ``as_of`` reference: a
   confirmed-stale observation lowers the path's effective authority instead of
   being treated as fresh. An observation whose instant is UNKNOWN is never
   reported as fresh and never assigned a fabricated age.

3. FIDELITY-AWARE COMPOSITION
   A new scoring layer that consumes the existing ``path_scoring``
   geometric-mean result and the M7 relationship-fidelity/evidence interface
   when present. If the M7 fidelity interface is absent (it is not built yet at
   M8), the layer degrades honestly: fidelity inputs are treated as UNKNOWN and
   the epistemic ceiling is still enforced from ``transitivityClasses`` alone.

4. NEVER MANUFACTURE TRUTH
   No universal person/social score. Unknown is never converted to 0 *as a
   measurement*, but a definite finding that a path is invalid (a NON_TRANSITIVE
   transitive misuse, a disputed fidelity vector, an expired window, or a
   predicate outside the governed registry) zeroes the *certified* composite:
   refusing to certify is not the same as reporting an unknown.

Flag gate (default OFF): ``AETHER_PATH_FIDELITY_ENABLED``. When it is not set
to a truthy value the layer is inert and returns the caller's existing
``path_scoring`` result unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Mapping, Optional

from shared.relationship_spine.generated_relationship_predicate_registry import (
    RELATIONSHIP_PREDICATES,
)
from shared.temporal.instant import coerce_utc_lenient

# Canonical identifier for the fidelity-aware scoring algorithm.
PATH_FIDELITY_ALGORITHM = "aether.relationship_spine.path_fidelity"
PATH_FIDELITY_VERSION = "1"

# Env flag controlling the layer. Undefined => False (new behaviour defaults OFF).
PATH_FIDELITY_ENV = "AETHER_PATH_FIDELITY_ENABLED"

# ────────────────────────────────────────────────────────────────────────────
# Governed epistemic-authority ceilings
#
# These constants encode M8 policy: the ordering is strict (a higher authority
# may never be manufactured by composing lower-authority hops). They are policy
# constants in the same spirit as ``_CAUSALITY_PENALTIES`` in path_scoring.py —
# deterministic, documented, and versioned — never learned or derived from the
# hop's own confidence.
# ────────────────────────────────────────────────────────────────────────────

# Authority of a material hop used for TRANSITIVE inference (multi-hop path),
# selected from the hop predicate's declared ``transitivityClasses``.
CEILING_PATH_COMPOSABLE = 1.0          # fully composable observed hop
CEILING_DELEGATION_COMPOSABLE = 0.8    # delegation-composable hop
CEILING_ATTRIBUTION_ELIGIBLE = 0.7     # attribution-eligible hop
CEILING_PROPAGATION_ONLY = 0.55        # flow/influence may propagate; a relationship may not
CEILING_INFERENTIAL_ONLY = 0.4         # weakest certified authority: inference over the graph
CEILING_NON_TRANSITIVE_MISUSE = 0.15   # down-weight mode only; a NON_TRANSITIVE hop chained
CEILING_UNCERTIFIED = 0.0              # predicate outside governed registry -> not certified

# Authority of a SINGLE-hop (direct fact) path from the predicate's declared
# claim-type floor. Unknown claim floors fall back to the edge's causality.
_DIRECT_CEILING_BY_CLAIM_FLOOR: dict[str, float] = {
    "observed": 1.0,
    "verified": 1.0,
    "resolved": 1.0,
    "derived": 0.85,
    "temporally_supported": 0.7,
    "inferred": CEILING_INFERENTIAL_ONLY,
    "predicted": 0.3,
    "correlated": 0.25,
    "disputed": 0.0,
}

# Direct-hop fallback authority from the edge's graph-level causality class.
_DIRECT_CEILING_BY_CAUSALITY: dict[str, float] = {
    "observed": 1.0,
    "observed_sequence": 1.0,
    "causal_supported": 1.0,
    "experiment_incremental": 1.0,
    "direct_cause": 1.0,
    "attributed": 0.6,
    "attributed_influence": 0.6,
    "inferred": CEILING_INFERENTIAL_ONLY,
    "inferred_influence": CEILING_INFERENTIAL_ONLY,
    "correlation": 0.25,
    "correlated": 0.25,
}

# ────────────────────────────────────────────────────────────────────────────
# Snapshot-staleness policy (governed defaults, overridable per call)
# ────────────────────────────────────────────────────────────────────────────

DEFAULT_FRESH_HORIZON_DAYS = 7.0   # age <= this (in days) counts as fresh
DEFAULT_STALE_HORIZON_DAYS = 90.0  # beyond this the observation is maximally stale
DEFAULT_STALE_FLOOR = 0.5          # effective-authority multiplier once maximally stale

# Observation-instant property keys, in preference order. Absence of all of them
# makes a hop's staleness UNKNOWN (never fabricated fresh).
_OBSERVATION_TIME_KEYS = ("observed_at", "observed_on", "reported_at")

# M7 fidelity-vector ``status`` values (from relationship-fidelity-vector schema).
FIDELITY_VECTOR_STATUSES = frozenset(
    {"current", "stale", "superseded", "disputed", "unknown"}
)

# Decision vocab exposed by the layer.
PathFidelityDecision = Literal[
    "disabled",      # flag OFF -> passthrough of the base path_scoring result
    "pass",          # certified composite (subject to ceiling / staleness)
    "downweight",    # NON_TRANSITIVE misuse tolerated -> honest low ceiling
    "reject",        # definite misuse/dispute -> composite zeroed (not certified)
    "uncertified",   # predicate not in governed registry -> not certified
    "invalid",       # hop window not active at as_of -> not a current fact
]


@dataclass
class StalenessPolicy:
    """Recency thresholds for snapshot-staleness evaluation."""

    fresh_horizon_days: float = DEFAULT_FRESH_HORIZON_DAYS
    stale_horizon_days: float = DEFAULT_STALE_HORIZON_DAYS
    stale_floor: float = DEFAULT_STALE_FLOOR

    def __post_init__(self) -> None:
        if not (0 <= self.fresh_horizon_days < self.stale_horizon_days):
            raise ValueError(
                "staleness policy requires 0 <= fresh_horizon_days < stale_horizon_days"
            )
        if not (0.0 <= self.stale_floor <= 1.0):
            raise ValueError("staleness policy requires 0 <= stale_floor <= 1.0")


@dataclass
class HopEpistemicAssessment:
    index: int
    edge_type: str
    predicate: Optional[str]
    transitivity_classes: tuple[str, ...]
    usage: Literal["direct", "transitive"]
    kind: str
    ceiling: Optional[float]
    reason: str = ""


@dataclass
class HopStalenessAssessment:
    index: int
    edge_type: str
    status: Literal["fresh", "stale", "expired", "not_yet_active", "unknown"]
    validity_ok: bool
    age_days: Optional[float] = None
    recency_factor: Optional[float] = None  # None when staleness is UNKNOWN (neutral, never fresh)
    reason: str = ""


@dataclass
class PathFidelityResult:
    """Fidelity-aware score for one path.

    ``breakdown`` is always shape-compatible with the existing
    ``PathScoreBreakdown`` DTO (and with ``path_scoring.score_path`` output): it
    carries exactly the same top-level fields, with ``overall`` holding the
    fidelity-adjusted composite. Richer per-hop detail lives on the dataclass,
    not inside the DTO dict, so callers that only want the DTO can pass
    ``breakdown`` straight through ``PathScoreBreakdown(**breakdown)``.
    """

    breakdown: dict[str, Any]
    raw_overall: float
    decision: PathFidelityDecision
    certified: bool
    reason_codes: tuple[str, ...] = ()
    epistemic_ceiling: Optional[float] = None
    recency_factor: Optional[float] = None
    staleness_status: Literal[
        "fresh", "stale", "expired", "not_yet_active", "unknown", "disabled"
    ] = "unknown"
    fidelity_input_status: Literal["present", "unknown", "degraded"] = "unknown"
    hop_epistemic: list[HopEpistemicAssessment] = field(default_factory=list)
    hop_staleness: list[HopStalenessAssessment] = field(default_factory=list)
    fidelity_version: str = PATH_FIDELITY_VERSION
    algorithm: str = PATH_FIDELITY_ALGORITHM

    @property
    def overall(self) -> float:
        return float(self.breakdown["overall"])

# ────────────────────────────────────────────────────────────────────────────
# Predicate resolution (governed registry -> entry for an edge type)
# ────────────────────────────────────────────────────────────────────────────

# (predicate|graphEdgeType) -> registry entry; built lazily from the generated
# tuple so the module stays correct if the generated twin is regenerated.
_registry_by_key: Optional[dict[str, dict[str, Any]]] = None


def _build_registry_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entry in RELATIONSHIP_PREDICATES:
        if not isinstance(entry, dict):
            continue
        predicate = str(entry.get("predicate", ""))
        graph_edge = entry.get("graphEdgeType")
        if predicate:
            index[predicate] = entry
        if graph_edge:
            index[str(graph_edge)] = entry
    return index


def predicate_entry_for_edge_type(
    edge_type: str, registry_index: Optional[Mapping[str, Any]] = None
) -> Optional[dict[str, Any]]:
    """Resolve a graph ``edge_type`` to its governed predicate entry.

    Matches either the predicate's canonical name or its declared
    ``graphEdgeType``. Returns ``None`` when the edge type is not governed by the
    relationship-predicate registry (the path is then NOT certified for
    relationship-fidelity composition — never silently assumed composable).
    """
    if registry_index is None:
        global _registry_by_key
        if _registry_by_key is None:
            _registry_by_key = _build_registry_index()
        registry_index = _registry_by_key
    if not edge_type:
        return None
    entry = registry_index.get(str(edge_type))
    return entry if isinstance(entry, dict) else None


# ────────────────────────────────────────────────────────────────────────────
# Hop accessors — accept shared.graph.Edge-like objects or plain dict hops
# ────────────────────────────────────────────────────────────────────────────

def _hop_props(hop: Any) -> dict[str, Any]:
    if isinstance(hop, dict):
        props = hop.get("properties") or {}
        return props if isinstance(props, dict) else dict(props)
    props = getattr(hop, "properties", None) or {}
    return props if isinstance(props, dict) else dict(props)


def _hop_type(hop: Any) -> str:
    if isinstance(hop, dict):
        return str(hop.get("type") or hop.get("edge_type") or "")
    return str(getattr(hop, "edge_type", "") or "")


def _hop_from_id(hop: Any) -> str:
    if isinstance(hop, dict):
        return str(hop.get("from") or hop.get("from_vertex_id") or "")
    return str(getattr(hop, "from_vertex_id", "") or "")


def _hop_to_id(hop: Any) -> str:
    if isinstance(hop, dict):
        return str(hop.get("to") or hop.get("to_vertex_id") or "")
    return str(getattr(hop, "to_vertex_id", "") or "")


def _hop_signature(hop: Any) -> str:
    return f"{_hop_from_id(hop)}:{_hop_to_id(hop)}:{_hop_type(hop)}"


def _edge_causality_class(props: Mapping[str, Any]) -> Optional[str]:
    raw = props.get("causality_class")
    if raw is None:
        return None
    value = str(raw).strip().lower()
    return value or None


# ────────────────────────────────────────────────────────────────────────────
# Temporal parsing (bitemporal discipline, defensive)
# ────────────────────────────────────────────────────────────────────────────

def _coerce_utc(value: object) -> Optional[datetime]:
    """Best-effort parse of an ISO-8601 instant to an aware UTC datetime.

    Delegates the naive-UTC assumption to the temporal kernel
    (``shared.temporal.instant.coerce_utc_lenient``), the only module permitted
    to attach a timezone. Unparseable input returns ``None`` (callers treat it
    as UNKNOWN, never as a fabricated instant).
    """
    coerced = coerce_utc_lenient(value)
    if coerced is None:
        return None
    return coerced.astimezone(timezone.utc)


# ────────────────────────────────────────────────────────────────────────────
# Staleness assessment
# ────────────────────────────────────────────────────────────────────────────

def _observation_instant(hop: Any, props: Mapping[str, Any]) -> Optional[datetime]:
    """The instant the hop's underlying observation was made.

    Resolved from explicit observation-time properties only. ``valid_from`` is
    NOT used as an observation instant: a relationship's validity start does not
    imply recent observation, so recency must be certified by an explicit
    observation/statement instant or left UNKNOWN.
    """
    for key in _OBSERVATION_TIME_KEYS:
        value = props.get(key)
        if value is not None:
            parsed = _coerce_utc(value)
            if parsed is not None:
                return parsed
    return None


def _validity_at(
    props: Mapping[str, Any], reference: datetime
) -> tuple[bool, Literal["active", "expired", "not_yet_active", "unknown"]]:
    """Whether the hop's valid-time window is active at ``reference``.

    Absent window => no temporal constraint => active. This mirrors the
    traversal engine's temporal filter (``valid_from <= as_of`` and
    ``valid_to is absent OR valid_to > as_of``).
    """
    valid_from = _coerce_utc(props.get("valid_from"))
    valid_to = _coerce_utc(props.get("valid_to"))
    if valid_from is None and valid_to is None:
        return True, "unknown"
    if valid_from is not None and valid_from > reference:
        return False, "not_yet_active"
    if valid_to is not None and valid_to <= reference:
        return False, "expired"
    return True, "active"


def assess_hop_staleness(
    hop: Any,
    *,
    reference: datetime,
    policy: StalenessPolicy,
) -> HopStalenessAssessment:
    """Assess one hop's snapshot staleness against ``reference``.

    - a hop with no active valid-time window at ``reference`` is not a current
      fact (``expired`` / ``not_yet_active`` -> recency factor 0);
    - a hop with an explicit observation instant is ``fresh``/``stale`` and gets
      a deterministic recency multiplier in ``[stale_floor, 1.0]``;
    - a hop with NO observation instant reports UNKNOWN staleness — it is never
      reported fresh and never assigned a fabricated age.
    """
    edge_type = _hop_type(hop)
    props = _hop_props(hop)

    validity_ok, window_status = _validity_at(props, reference)
    if not validity_ok:
        return HopStalenessAssessment(
            index=-1,
            edge_type=edge_type,
            status=window_status,  # type: ignore[arg-type]
            validity_ok=False,
            recency_factor=0.0,
            reason="hop_window_not_active_at_reference",
        )

    observed = _observation_instant(hop, props)
    if observed is None:
        return HopStalenessAssessment(
            index=-1,
            edge_type=edge_type,
            status="unknown",
            validity_ok=True,
            recency_factor=None,
            reason="observation_instant_unknown",
        )

    age = reference - observed
    age_days = age.total_seconds() / 86400.0
    if age_days <= policy.fresh_horizon_days:
        return HopStalenessAssessment(
            index=-1,
            edge_type=edge_type,
            status="fresh",
            validity_ok=True,
            age_days=round(age_days, 6),
            recency_factor=1.0,
            reason="within_fresh_horizon",
        )
    if age_days >= policy.stale_horizon_days:
        return HopStalenessAssessment(
            index=-1,
            edge_type=edge_type,
            status="stale",
            validity_ok=True,
            age_days=round(age_days, 6),
            recency_factor=policy.stale_floor,
            reason="beyond_stale_horizon",
        )
    span = policy.stale_horizon_days - policy.fresh_horizon_days
    progress = (age_days - policy.fresh_horizon_days) / span if span else 1.0
    factor = 1.0 - progress * (1.0 - policy.stale_floor)
    return HopStalenessAssessment(
        index=-1,
        edge_type=edge_type,
        status="stale",
        validity_ok=True,
        age_days=round(age_days, 6),
        recency_factor=round(max(0.0, min(factor, 1.0)), 6),
        reason="past_fresh_horizon",
    )

# ────────────────────────────────────────────────────────────────────────────
# Epistemic assessment
# ────────────────────────────────────────────────────────────────────────────

# Strong composable classes: presence authorizes TRUE transitive composition.
_COMPOSABLE_AUTHORIZING = {
    "PATH_COMPOSABLE": CEILING_PATH_COMPOSABLE,
    "DELEGATION_COMPOSABLE": CEILING_DELEGATION_COMPOSABLE,
    "ATTRIBUTION_ELIGIBLE": CEILING_ATTRIBUTION_ELIGIBLE,
}


def _transitive_hop_epistemic(
    index: int, edge_type: str, entry: Optional[dict[str, Any]]
) -> HopEpistemicAssessment:
    """Epistemic assessment of a material hop USED TRANSITIVELY.

    Worst case wins: an ``INFERENTIAL_ONLY`` hop caps the whole path at the
    inferential ceiling even when it also declares a composable class; a
    NON_TRANSITIVE hop is not composable and its transitive use is a misuse.
    """
    classes: tuple[str, ...] = ()
    predicate: Optional[str] = None
    if entry is not None:
        predicate = str(entry.get("predicate", "")) or None
        raw_classes = entry.get("transitivityClasses") or ()
        classes = tuple(str(c) for c in raw_classes)

    if not classes:
        return HopEpistemicAssessment(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=(),
            usage="transitive",
            kind="uncertified",
            ceiling=CEILING_UNCERTIFIED,
            reason="predicate_not_in_governed_registry",
        )

    if "INFERENTIAL_ONLY" in classes:
        return HopEpistemicAssessment(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=classes,
            usage="transitive",
            kind="inferred",
            ceiling=CEILING_INFERENTIAL_ONLY,
            reason="inferential_only_hop",
        )

    authorizing = {
        c: ceiling for c, ceiling in _COMPOSABLE_AUTHORIZING.items() if c in classes
    }
    if authorizing:
        # The strongest authorizing capability present is the hop's composable
        # grade; weaker co-tags (e.g. PROPAGATION_ELIGIBLE on PAYS) do not pull
        # a genuinely composable hop down.
        ceiling = max(authorizing.values())
        return HopEpistemicAssessment(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=classes,
            usage="transitive",
            kind="composable",
            ceiling=ceiling,
            reason="composable_material_hop",
        )

    if "NON_TRANSITIVE" in classes:
        return HopEpistemicAssessment(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=classes,
            usage="transitive",
            kind="non_transitive_misuse",
            ceiling=CEILING_NON_TRANSITIVE_MISUSE,
            reason="non_transitive_transitive_inference",
        )

    if "PROPAGATION_ELIGIBLE" in classes:
        return HopEpistemicAssessment(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=classes,
            usage="transitive",
            kind="propagation",
            ceiling=CEILING_PROPAGATION_ONLY,
            reason="propagation_eligible_only",
        )

    return HopEpistemicAssessment(
        index=index,
        edge_type=edge_type,
        predicate=predicate,
        transitivity_classes=classes,
        usage="transitive",
        kind="uncertified",
        ceiling=CEILING_UNCERTIFIED,
        reason="unclassifiable_transitivity",
    )


def _direct_hop_epistemic(
    index: int, edge_type: str, hop: Any, entry: Optional[dict[str, Any]]
) -> HopEpistemicAssessment:
    """Epistemic assessment of a SINGLE-HOP (direct fact) path.

    A direct hop asserts the existence of the edge itself, so its authority
    comes from how the fact was obtained:
      - an ``INFERENTIAL_ONLY`` predicate is inference-grade material;
      - otherwise the registry claim-type floor (observed/verified > derived >
        inferred > ...) bounds the hop;
      - when the predicate is not governed we fall back to the edge's graph-level
        causality class (an edge is self-certifying as an observation, but an
        inferred/correlated edge stays weak).
    """
    props = _hop_props(hop)
    classes: tuple[str, ...] = ()
    predicate: Optional[str] = None
    claim_floor: Optional[str] = None
    if entry is not None:
        predicate = str(entry.get("predicate", "")) or None
        raw_classes = entry.get("transitivityClasses") or ()
        classes = tuple(str(c) for c in raw_classes)
        claim_value = entry.get("claimTypeFloor")
        claim_floor = str(claim_value) if claim_value else None

    if "INFERENTIAL_ONLY" in classes:
        return HopEpistemicAssessment(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=classes,
            usage="direct",
            kind="inferred",
            ceiling=CEILING_INFERENTIAL_ONLY,
            reason="inferential_only_predicate",
        )

    ceiling: Optional[float] = None
    reason = "direct_observed_edge"
    kind = "observed"
    if claim_floor in _DIRECT_CEILING_BY_CLAIM_FLOOR:
        ceiling = _DIRECT_CEILING_BY_CLAIM_FLOOR[claim_floor]
        kind = claim_floor
        reason = f"claim_type_floor={claim_floor}"

    causality = _edge_causality_class(props)
    if causality is not None:
        causality_ceiling = _DIRECT_CEILING_BY_CAUSALITY.get(causality)
        if causality_ceiling is not None:
            ceiling = causality_ceiling if ceiling is None else min(ceiling, causality_ceiling)
            reason = f"{reason}; causality_class={causality}"
            if causality in ("inferred_influence", "inferred"):
                kind = "inferred"
            elif causality in ("correlation", "correlated"):
                kind = "correlated"

    if ceiling is None:
        ceiling = 1.0
        kind = "observed"
        reason = "direct_observed_edge"

    return HopEpistemicAssessment(
        index=index,
        edge_type=edge_type,
        predicate=predicate,
        transitivity_classes=classes,
        usage="direct",
        kind=kind,
        ceiling=round(ceiling, 6),
        reason=reason,
    )


def assess_hop_epistemic(
    index: int,
    hop: Any,
    *,
    path_length: int,
    predicate_resolver: Callable[[str], Optional[dict[str, Any]]],
) -> HopEpistemicAssessment:
    """Public per-hop epistemic assessment (used by the path scorer and tests)."""
    edge_type = _hop_type(hop)
    entry = predicate_resolver(edge_type)
    if path_length > 1:
        return _transitive_hop_epistemic(index, edge_type, entry)
    return _direct_hop_epistemic(index, edge_type, hop, entry)


# ────────────────────────────────────────────────────────────────────────────
# M7 fidelity-vector consumption (defensive; absent interface => UNKNOWN)
# ────────────────────────────────────────────────────────────────────────────

def _fidelity_vector_for_hop(
    hop: Any,
    index: int,
    mapping: Optional[Mapping[Any, Any]],
) -> Optional[dict[str, Any]]:
    """Locate an M7 relationship-fidelity vector for one hop.

    Accepts keys as hop index (int), the synthetic edge signature, or a hop id
    property. Returns ``None`` when absent or when the value is not a dict.
    """
    if not mapping:
        return None
    candidates: list[Any] = [index]
    props = _hop_props(hop)
    for key in ("id", "edge_id", "relationship_id"):
        if props.get(key):
            candidates.append(props[key])
    candidates.append(_hop_signature(hop))
    for candidate in candidates:
        value = mapping.get(candidate)
        if isinstance(value, dict):
            return value
    return None


# ────────────────────────────────────────────────────────────────────────────
# Public scoring entry points
# ────────────────────────────────────────────────────────────────────────────

def path_fidelity_enabled(enabled: Optional[bool] = None) -> bool:
    """Effective flag state. Undefined env => False (new behaviour defaults OFF)."""
    if enabled is not None:
        return bool(enabled)
    raw = os.environ.get(PATH_FIDELITY_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _default_reference(as_of: Optional[str]) -> datetime:
    if as_of is not None:
        parsed = _coerce_utc(as_of)
        if parsed is not None:
            return parsed
    return datetime.now(timezone.utc)


def score_path_with_fidelity(
    edges: list[Any],
    *,
    max_depth: int,
    as_of: Optional[str] = None,
    base_breakdown: Optional[dict[str, Any]] = None,
    predicate_resolver: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    fidelity_by_hop: Optional[Mapping[Any, Any]] = None,
    reject_non_transitive: bool = True,
    strict_uncertified: bool = True,
    staleness_policy: Optional[StalenessPolicy] = None,
    enabled: Optional[bool] = None,
) -> PathFidelityResult:
    """Compute a fidelity-aware score for ``edges``.

    Composition contract
    --------------------
    - ``base_breakdown`` is the existing ``path_scoring.score_path`` result dict.
      When omitted it is computed lazily by importing ``path_scoring`` (kept out
      of module import time so the layer can sit inert when disabled).
    - ``overall`` in the returned ``breakdown`` is the fidelity-adjusted
      composite; every other field keeps the base semantics. All additional
      numeric fidelity markers live inside ``breakdown["components"]`` so the
      dict stays shape-compatible with ``PathScoreBreakdown``.

    Flag gate
    ---------
    When the fidelity layer is not enabled the base breakdown is returned
    untouched (``decision == "disabled"``) — existing path_scoring/traversal
    behaviour is unchanged, which is the flag-OFF regression contract.
    """
    policy = staleness_policy or StalenessPolicy()
    if not path_fidelity_enabled(enabled):
        if base_breakdown is None:
            base_breakdown = _compute_base_breakdown(edges, max_depth=max_depth)
        return PathFidelityResult(
            breakdown=base_breakdown,
            raw_overall=float(base_breakdown["overall"]),
            decision="disabled",
            certified=False,
            reason_codes=("path_fidelity_disabled",),
            fidelity_input_status="unknown",
            staleness_status="disabled",
        )

    if base_breakdown is None:
        base_breakdown = _compute_base_breakdown(edges, max_depth=max_depth)
    resolver = predicate_resolver or predicate_entry_for_edge_type
    raw_overall = float(base_breakdown["overall"])
    reference = _default_reference(as_of)

    if not edges:
        return PathFidelityResult(
            breakdown=_with_components(base_breakdown, raw_overall, None, None, None),
            raw_overall=raw_overall,
            decision="pass",
            certified=True,
            reason_codes=("empty_path_no_material_hops",),
            staleness_status="unknown",
            fidelity_input_status="unknown",
        )

    path_length = len(edges)
    reason_codes: list[str] = []

    # Per-hop epistemic + staleness assessments.
    epistemic: list[HopEpistemicAssessment] = []
    staleness: list[HopStalenessAssessment] = []
    for idx, hop in enumerate(edges):
        ep = assess_hop_epistemic(idx, hop, path_length=path_length,
                                  predicate_resolver=resolver)
        st = assess_hop_staleness(hop, reference=reference, policy=policy)
        st.index = idx
        epistemic.append(ep)
        staleness.append(st)

    # Fidelity-vector consumption (M7 interface; absent => honest UNKNOWN).
    fidelity_input_status: str = "unknown"
    if fidelity_by_hop:
        fidelity_input_status = "present"
        for idx, hop in enumerate(edges):
            vector = _fidelity_vector_for_hop(hop, idx, fidelity_by_hop)
            if not vector:
                continue
            vector_status = vector.get("status")
            if vector_status not in FIDELITY_VECTOR_STATUSES:
                continue
            if vector_status == "disputed":
                reason_codes.append(f"hop_{idx}_fidelity_disputed")
                return PathFidelityResult(
                    breakdown=_with_components(base_breakdown, 0.0, None, None, None),
                    raw_overall=raw_overall,
                    decision="reject",
                    certified=False,
                    reason_codes=tuple(reason_codes),
                    epistemic_ceiling=None,
                    recency_factor=None,
                    staleness_status="unknown",
                    fidelity_input_status=fidelity_input_status,
                    hop_epistemic=epistemic,
                    hop_staleness=staleness,
                )
            if vector_status in ("stale", "superseded"):
                # Definite negative recency evidence from the fidelity vector:
                # fold it in as if the supporting observation had aged out.
                st = staleness[idx]
                if st.recency_factor is None or st.recency_factor > policy.stale_floor:
                    st.recency_factor = policy.stale_floor
                    st.status = "stale"  # type: ignore[assignment]
                    st.reason = f"{st.reason}; fidelity_vector_{vector_status}"
    else:
        reason_codes.append("fidelity_inputs_absent_degraded_to_unknown")

    # Aggregate staleness: worst-case (weakest material hop) recency wins.
    limiting_staleness = staleness[0]
    for st in staleness[1:]:
        if not st.validity_ok:
            limiting_staleness = st
            break
        if st.recency_factor is not None and (
            limiting_staleness.recency_factor is None
            or st.recency_factor < limiting_staleness.recency_factor
        ):
            limiting_staleness = st

    if not limiting_staleness.validity_ok:
        reason_codes.append("hop_window_not_active_at_as_of")
        return PathFidelityResult(
            breakdown=_with_components(base_breakdown, 0.0, None, None, None),
            raw_overall=raw_overall,
            decision="invalid",
            certified=False,
            reason_codes=tuple(reason_codes),
            epistemic_ceiling=None,
            recency_factor=0.0,
            staleness_status=limiting_staleness.status,  # type: ignore[arg-type]
            fidelity_input_status=fidelity_input_status,
            hop_epistemic=epistemic,
            hop_staleness=staleness,
        )

    staleness_status: str = limiting_staleness.status
    recency_factor = limiting_staleness.recency_factor
    if any(st.recency_factor is None for st in staleness):
        # At least one hop has UNKNOWN staleness. Never fabricate freshness: the
        # composite reports 'unknown' even though the numeric fold stays neutral.
        if recency_factor is None or all(st.recency_factor is None for st in staleness):
            recency_factor = 1.0
            staleness_status = "unknown"
        else:
            staleness_status = "unknown"

    # Aggregate epistemic ceiling (weakest material hop wins).
    ceilings = [e.ceiling for e in epistemic if e.ceiling is not None]
    path_ceiling = min(ceilings) if ceilings else None

    misuse = any(e.kind == "non_transitive_misuse" for e in epistemic)
    uncertified = any(e.kind == "uncertified" for e in epistemic)

    if misuse and reject_non_transitive:
        reason_codes.append("non_transitive_transitive_inference_rejected")
        return PathFidelityResult(
            breakdown=_with_components(base_breakdown, 0.0, path_ceiling,
                                       recency_factor, raw_overall),
            raw_overall=raw_overall,
            decision="reject",
            certified=False,
            reason_codes=tuple(reason_codes),
            epistemic_ceiling=path_ceiling,
            recency_factor=recency_factor,
            staleness_status=staleness_status,  # type: ignore[arg-type]
            fidelity_input_status=fidelity_input_status,
            hop_epistemic=epistemic,
            hop_staleness=staleness,
        )

    if uncertified and strict_uncertified:
        reason_codes.append("predicate_not_in_governed_registry_uncertified")
        return PathFidelityResult(
            breakdown=_with_components(base_breakdown, 0.0, path_ceiling,
                                       recency_factor, raw_overall),
            raw_overall=raw_overall,
            decision="uncertified",
            certified=False,
            reason_codes=tuple(reason_codes),
            epistemic_ceiling=path_ceiling,
            recency_factor=recency_factor,
            staleness_status=staleness_status,  # type: ignore[arg-type]
            fidelity_input_status=fidelity_input_status,
            hop_epistemic=epistemic,
            hop_staleness=staleness,
        )

    if misuse and not reject_non_transitive:
        reason_codes.append("non_transitive_transitive_inference_downweighted")
        decision: PathFidelityDecision = "downweight"
    elif uncertified and not strict_uncertified:
        reason_codes.append("predicate_not_in_governed_registry_uncertified")
        decision = "uncertified"
    else:
        decision = "pass"

    cap = path_ceiling if path_ceiling is not None else 1.0
    effective = min(raw_overall, cap) * (recency_factor if recency_factor is not None else 1.0)
    effective = round(max(0.0, min(effective, 1.0)), 6)

    reason_codes.append("epistemic_ceiling_enforced")

    return PathFidelityResult(
        breakdown=_with_components(
            base_breakdown, effective, path_ceiling, recency_factor, raw_overall
        ),
        raw_overall=raw_overall,
        decision=decision,
        certified=decision == "pass",
        reason_codes=tuple(reason_codes),
        epistemic_ceiling=path_ceiling,
        recency_factor=recency_factor,
        staleness_status=staleness_status,  # type: ignore[arg-type]
        fidelity_input_status=fidelity_input_status,  # type: ignore[arg-type]
        hop_epistemic=epistemic,
        hop_staleness=staleness,
    )


def _compute_base_breakdown(edges: list[Any], *, max_depth: int) -> dict[str, Any]:
    """Lazy import of the existing numeric scorer (kept out of module import)."""
    from shared.graph.path_scoring import score_path  # noqa: PLC0415

    return score_path(edges, max_depth=max_depth)


def _with_components(
    base: dict[str, Any],
    overall: float,
    epistemic_ceiling: Optional[float],
    recency_factor: Optional[float],
    raw_overall: Optional[float],
) -> dict[str, Any]:
    """Return a PathScoreBreakdown-shaped copy of ``base`` with fidelity markers.

    Only numeric fidelity markers are added inside ``components`` so the dict
    remains shape-compatible with ``PathScoreBreakdown`` (whose ``components``
    is ``dict[str, float]``); all rich per-hop detail is carried on the result
    dataclass instead.
    """
    components = dict(base.get("components") or {})
    components["fidelity_overall"] = float(overall)
    if epistemic_ceiling is not None:
        components["epistemic_ceiling"] = float(epistemic_ceiling)
    if recency_factor is not None:
        components["recency_factor"] = float(recency_factor)
    if raw_overall is not None:
        components["raw_geometric_composite"] = float(raw_overall)
    components["fidelity_version"] = float(PATH_FIDELITY_VERSION)
    return {
        "geometric_mean_confidence": base.get("geometric_mean_confidence", 1.0),
        "min_edge_confidence": base.get("min_edge_confidence", 1.0),
        "hop_penalty": base.get("hop_penalty", 1.0),
        "causality_penalty": base.get("causality_penalty", 0.0),
        "overall": round(float(overall), 6),
        "scoring_version": base.get("scoring_version", "1"),
        "components": components,
    }
