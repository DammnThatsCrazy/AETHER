"""Aether Shared — @aether/relationship_spine/influence_propagation
Wave 4a read-side influence-path decomposition (9-way attention decomposition).

Blueprint ``social360.md`` (the Social360 + Relationship Fidelity extension to
the Relational Intelligence Spine) defines influence NOT as follower count but
as **propagation**:

    Influence = observed capacity for information, behavior, or outcomes to
    propagate through evidence-backed relationships in a defined context.
                                                          (blueprint §70)

Sections §71–§80 then refuse a single collapsed "influence number" and instead
name nine separate attention categories that an EngagementFi-style surface must
keep apart:

    RAW ATTENTION                 (§72)
    INCENTIVE-EXPOSED ATTENTION   (§73)
    INDEPENDENCE-SUPPORTED ATTENTION   (§74)
    EARNED DOWNSTREAM AMPLIFICATION    (§75)
    PERSISTENT ATTENTION          (§76)
    NOVEL ATTENTION               (§77)
    RELATIONSHIP-WEIGHTED ATTENTION    (§78)
    OUTCOME-LINKED ATTENTION      (§79)
    COORDINATION-ADJUSTED ATTENTION    (§80)

This module is the **read-side decomposition** of the influence one entity
exerts over another *along one relationship path* into exactly those nine
components. It is pure, dependency-light and deterministic: it performs no
graph writes, imports no app settings / DB (no ``config.settings``, no flag
module), and only consumes what a caller passes in (path edges, an ``as_of``
reference, per-hop measured values, and the governed predicate registry through
``shared.relationship_spine.path_fidelity``'s public helpers).

Honesty contract (repo doctrine, mirrored from ``path_fidelity.py`` / M7):

* UNKNOWN is never 0 and never fabricated: a component that cannot be measured
  from the supplied evidence is ``None`` with a machine-readable ``state`` of
  ``insufficient_data`` (or ``not_applicable``) and a reason — never a 0.
* No universal ``InfluenceScore`` / ``SocialScore`` scalar is produced. The
  nine components are exposed as separate fields; the top level only summarises
  which components are available.
* Absence of evidence never yields a low influence claim. Unidirectional or
  unmeasured hops never certify a low reciprocal/relationship-weighted value.
* A multi-hop path cannot certify propagation through a relationship the
  governed registry does not authorise to propagate (fail-closed), and a path
  never exceeds the weakest material hop's epistemic authority (§66/§68).
* The blueprint's §72–§80 categories describe per-entity engagement corpora.
  Where this repo's per-hop data genuinely measures a category we fold it along
  the path; where the needed evidence is not produced anywhere in this repo yet
  the component is exposed as an explicitly-degraded ``None``/``insufficient_data``
  and the future surface that would supply it is documented on that component
  (see :class:`ComponentEstimate` and the builders below).

Measurement inputs
------------------
Per-hop measured values travel in ``fidelity_by_hop`` (same lookup shape as
``path_fidelity.score_path_with_fidelity``: hop index, an ``id``/``edge_id``/
``relationship_id`` property, or the synthetic ``from:to:edge_type`` signature).
Each value is a dict keyed by the M7 relationship-fidelity-vector dimension
names the caller has actually measured for that hop (``interaction_frequency``,
``interaction_depth``, ``persistence``, ``reciprocity``,
``incentive_exposure``, ``incentive_independence_support``,
``coordination_indicator_strength``, ``outcome_support``). A value outside
[0, 1] or ``None`` is treated as not measured for that hop — never coerced.

Propagation fold
----------------
Every component folds measured per-hop values along the path deterministically.
A single documented fold is chosen per component from the semantics of the
category (bottleneck / share / contamination); the fold and its rationale are
carried on each :class:`ComponentEstimate`. A component is only ``available``
when every material hop (every hop for most components; every *downstream* hop
for §75) actually carries its measured input — an unmeasured leg could be
arbitrarily weaker/contaminated, so declaring the whole path available from
partial legs would overstate.

Output
------
``decompose_influence_propagation(...)`` returns a frozen
:class:`InfluencePropagationDecomposition` dataclass (sibling style to
``PathFidelityResult``) whose nine named fields mirror the blueprint's nine
categories exactly so a Noesis ``influence_path`` intent or a REST read can
render them independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Mapping, Optional

from shared.relationship_spine.generated_relationship_predicate_registry import (
    RELATIONSHIP_PREDICATES,
)
from shared.relationship_spine.path_fidelity import (
    CEILING_ATTRIBUTION_ELIGIBLE,
    CEILING_DELEGATION_COMPOSABLE,
    CEILING_INFERENTIAL_ONLY,
    CEILING_NON_TRANSITIVE_MISUSE,
    CEILING_PATH_COMPOSABLE,
    CEILING_PROPAGATION_ONLY,
    CEILING_UNCERTIFIED,
    StalenessPolicy,
    assess_hop_epistemic,
    assess_hop_staleness,
)
from shared.temporal.instant import coerce_utc_lenient

# Canonical identifiers for this decomposition algorithm.
INFLUENCE_PROPAGATION_ALGORITHM = "aether.relationship_spine.influence_propagation"
INFLUENCE_PROPAGATION_VERSION = "1"

# Version of the relationship-weight basis formula (blueprint §78 requires the
# relationship-weighting definition to be versioned and contextual).
RELATIONSHIP_WEIGHT_FORMULA_VERSION = "1"

# Reference for the persistence window the measured `persistence` dimension
# implies when it was derived by the M7 scorer (shared.relationship_fidelity).
# §76 requires an explicit duration/window policy; M7 owns the derivation, this
# module only records the reference window it is consistent with.
PERSISTENCE_HORIZON_DAYS = 90.0

# ────────────────────────────────────────────────────────────────────────────
# The nine canonical components, in blueprint §71 order. A surface rendering the
# blueprint's 9-way attention decomposition MUST expose exactly these ids.
# ────────────────────────────────────────────────────────────────────────────

ComponentId = Literal[
    "raw_attention",
    "incentive_exposed_attention",
    "independence_supported_attention",
    "earned_downstream_amplification",
    "persistent_attention",
    "novel_attention",
    "relationship_weighted_attention",
    "outcome_linked_attention",
    "coordination_adjusted_attention",
]

ATTENTION_COMPONENTS: tuple[ComponentId, ...] = (
    "raw_attention",
    "incentive_exposed_attention",
    "independence_supported_attention",
    "earned_downstream_amplification",
    "persistent_attention",
    "novel_attention",
    "relationship_weighted_attention",
    "outcome_linked_attention",
    "coordination_adjusted_attention",
)

ComponentState = Literal["available", "insufficient_data", "not_applicable"]

# Propagation decisions for a whole path. Mirrors path_fidelity's vocabulary but
# scoped to *influence propagation* rather than relationship-transitivity claims.
InfluenceDecision = Literal[
    "empty",         # no material hops
    "pass",          # propagation decomposable on governed, certifiable hops
    "downweight",    # NON_PROPAGATING hop chained but tolerated at a low ceiling
    "reject",        # NON_PROPAGATING hop chained and strict -> not decomposable
    "uncertified",   # a hop's predicate is outside the governed registry
    "invalid",       # a hop's valid-time window is not active at as_of
]

# Per-hop fold labels (documented, deterministic).
FoldKind = Literal["bottleneck_min", "assessed_mean", "contamination_max"]

# Machine-readable reason codes shared across components.
R_EMPTY_PATH = "empty_path_no_material_hops"
R_NO_MEASURED_INPUTS = "no_hop_measurements_supplied"
R_PARTIAL_HOP_MEASUREMENT = "insufficient_hop_measurement_coverage"
R_NOT_IN_GOVERNED_REGISTRY = "predicate_not_in_governed_registry_uncertified"
R_NON_PROPAGATING = "non_propagating_relationship_chained"
R_WINDOW_INACTIVE = "hop_window_not_active_at_as_of"
R_NOVELTY_UNSUPPLIED = "novelty_neighborhood_history_not_produced"
R_DOWNSTREAM_UNSUPPLIED = "downstream_incentive_absence_not_produced"
R_NO_DOWNSTREAM_HOP = "no_downstream_material_hop"

# ────────────────────────────────────────────────────────────────────────────
# Public result types
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HopPropagationAuthority:
    """Epistemic authority of ONE material hop for *propagation* semantics.

    ``usage`` distinguishes a single-hop (direct) relationship — self-certifying
    as an observed fact via its claim floor — from a multi-hop *propagation* leg,
    whose authority comes from the governed predicate's ``transitivityClasses``
    selected for influence flow (see module docstring: the registry authorises
    PROPAGATION_ELIGIBLE hops to carry flow even when they are NON_TRANSITIVE as
    *relationship identities*).
    """

    index: int
    edge_type: str
    predicate: Optional[str]
    transitivity_classes: tuple[str, ...]
    usage: Literal["direct", "propagation"]
    kind: str
    ceiling: Optional[float]
    reason: str = ""


@dataclass(frozen=True)
class ComponentEstimate:
    """One of the nine attention components decomposed along the path.

    ``state == "available"`` means the value is a measured [0, 1] fold over the
    material hops. ``state == "insufficient_data"`` means the value is ``None``:
    the required evidence is absent, partial or not produced by any current
    surface — never a fabricated 0. ``not_applicable`` is used where the
    category cannot apply structurally (e.g. no downstream hop for §75).
    """

    component_id: ComponentId
    display_name: str
    blueprint_section: str
    state: ComponentState
    value: Optional[float] = None
    reason_code: str = ""
    reason: str = ""
    formula: FoldKind | str = ""
    material_hops: int = 0
    measured_hops: int = 0
    per_hop_values: tuple[tuple[int, float], ...] = ()  # (hop_index, value), index order
    limitations: str = ""


@dataclass(frozen=True)
class InfluencePropagationDecomposition:
    """Decomposition of influence propagating from ``source_ref`` to ``target_ref``.

    Exactly the nine §71 fields are exposed by name. No universal influence
    scalar exists; :attr:`available_component_ids` and :attr:`available_components`
    summarise what the supplied evidence actually supports.
    """

    source_ref: str
    target_ref: str
    algorithm: str = INFLUENCE_PROPAGATION_ALGORITHM
    version: str = INFLUENCE_PROPAGATION_VERSION
    as_of: Optional[str] = None
    decision: InfluenceDecision = "empty"
    propagation_certified: bool = False
    reason_codes: tuple[str, ...] = ()
    staleness_status: Literal[
        "fresh", "stale", "expired", "not_yet_active", "unknown", "empty"
    ] = "unknown"
    hop_count: int = 0
    min_epistemic_ceiling: Optional[float] = None

    # The nine §71 attention components.
    raw_attention: ComponentEstimate = field(default_factory=lambda: _degraded("raw_attention"))
    incentive_exposed_attention: ComponentEstimate = field(
        default_factory=lambda: _degraded("incentive_exposed_attention")
    )
    independence_supported_attention: ComponentEstimate = field(
        default_factory=lambda: _degraded("independence_supported_attention")
    )
    earned_downstream_amplification: ComponentEstimate = field(
        default_factory=lambda: _degraded("earned_downstream_amplification")
    )
    persistent_attention: ComponentEstimate = field(
        default_factory=lambda: _degraded("persistent_attention")
    )
    novel_attention: ComponentEstimate = field(
        default_factory=lambda: _degraded("novel_attention")
    )
    relationship_weighted_attention: ComponentEstimate = field(
        default_factory=lambda: _degraded("relationship_weighted_attention")
    )
    outcome_linked_attention: ComponentEstimate = field(
        default_factory=lambda: _degraded("outcome_linked_attention")
    )
    coordination_adjusted_attention: ComponentEstimate = field(
        default_factory=lambda: _degraded("coordination_adjusted_attention")
    )

    hop_authority: tuple[HopPropagationAuthority, ...] = ()
    hop_staleness: tuple[Any, ...] = ()  # path_fidelity.HopStalenessAssessment tuples

    @property
    def all_components(self) -> tuple[ComponentEstimate, ...]:
        """The nine components in §71 order (deterministic)."""
        return (
            self.raw_attention,
            self.incentive_exposed_attention,
            self.independence_supported_attention,
            self.earned_downstream_amplification,
            self.persistent_attention,
            self.novel_attention,
            self.relationship_weighted_attention,
            self.outcome_linked_attention,
            self.coordination_adjusted_attention,
        )

    @property
    def available_component_ids(self) -> tuple[str, ...]:
        return tuple(c.component_id for c in self.all_components if c.state == "available")

    @property
    def available_components(self) -> int:
        return sum(1 for c in self.all_components if c.state == "available")

    def as_dict(self) -> dict[str, ComponentEstimate]:
        """Ordered mapping field id -> estimate for renderers."""
        return {c.component_id: c for c in self.all_components}


# Degraded default estimate (used for dataclass field defaults / empty paths).
def _degraded(component_id: ComponentId) -> ComponentEstimate:
    display, section = _DISPLAY[component_id]
    return ComponentEstimate(
        component_id=component_id,
        display_name=display,
        blueprint_section=section,
        state="insufficient_data",
        reason_code=R_EMPTY_PATH,
        reason="no material hops on the path to decompose",
    )


# Display metadata keyed by component id.
_DISPLAY: dict[ComponentId, tuple[str, str]] = {
    "raw_attention": ("Raw Attention", "72"),
    "incentive_exposed_attention": ("Incentive-Exposed Attention", "73"),
    "independence_supported_attention": ("Independence-Supported Attention", "74"),
    "earned_downstream_amplification": ("Earned Downstream Amplification", "75"),
    "persistent_attention": ("Persistent Attention", "76"),
    "novel_attention": ("Novel Attention", "77"),
    "relationship_weighted_attention": ("Relationship-Weighted Attention", "78"),
    "outcome_linked_attention": ("Outcome-Linked Attention", "79"),
    "coordination_adjusted_attention": ("Coordination-Adjusted Attention", "80"),
}

# Per-hop measured dimension keys each component consumes (M7 fidelity-vector
# dimension names). NOVEL has no existing supplier; EARNED DOWNSTREAM AMPLIFICATION
# consumes a key no current surface produces (documented future EngagementFi input).
_RAW_INPUTS = ("interaction_frequency", "interaction_depth")
_INCENTIVE_EXPOSED_INPUTS = ("incentive_exposure",)
_INDEPENDENCE_INPUTS = ("incentive_independence_support",)
_PERSISTENT_INPUTS = ("persistence",)
_RELATIONSHIP_WEIGHT_INPUTS = ("reciprocity", "persistence")
_OUTCOME_INPUTS = ("outcome_support",)
_COORDINATION_INPUTS = ("coordination_indicator_strength",)
_DOWNSTREAM_INPUTS = ("downstream_incentive_absence",)

# ────────────────────────────────────────────────────────────────────────────
# Hop accessors (accept shared.graph.Edge-like objects or plain dict hops;
# identical contract to path_fidelity's private helpers, re-implemented here so
# this module stays self-contained).
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


def _coerce_utc(value: object) -> Optional[datetime]:
    coerced = coerce_utc_lenient(value)
    if coerced is None:
        return None
    return coerced.astimezone(timezone.utc)


# ────────────────────────────────────────────────────────────────────────────
# Predicate resolution (public helper from path_fidelity, registry-indexed)
# ────────────────────────────────────────────────────────────────────────────

_registry_index: Optional[dict[str, dict[str, Any]]] = None


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


def _resolver_for(
    predicate_resolver: Optional[Callable[[str], Optional[dict[str, Any]]]],
) -> Callable[[str], Optional[dict[str, Any]]]:
    if predicate_resolver is not None:
        return predicate_resolver
    global _registry_index
    if _registry_index is None:
        _registry_index = _build_registry_index()

    def _resolve(edge_type: str) -> Optional[dict[str, Any]]:
        entry = _registry_index.get(str(edge_type))
        return entry if isinstance(entry, dict) else None

    return _resolve


# ────────────────────────────────────────────────────────────────────────────
# Per-hop propagation authority
# ────────────────────────────────────────────────────────────────────────────

# Strong composable classes: presence authorises relationship-composable
# propagation at the strongest declared grade.
_COMPOSABLE_AUTHORIZING: dict[str, float] = {
    "PATH_COMPOSABLE": CEILING_PATH_COMPOSABLE,
    "DELEGATION_COMPOSABLE": CEILING_DELEGATION_COMPOSABLE,
    "ATTRIBUTION_ELIGIBLE": CEILING_ATTRIBUTION_ELIGIBLE,
}


def assess_hop_propagation_authority(
    index: int,
    hop: Any,
    *,
    path_length: int,
    predicate_resolver: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
) -> HopPropagationAuthority:
    """Epistemic authority of one hop for *influence-propagation* semantics.

    Single hop (``path_length == 1``): the hop IS the source->target channel, a
    direct observed relationship; authority is delegated to path_fidelity's
    direct-hop assessment (self-certifying via claim floor / causality).

    Multi-hop: each leg is used to *propagate* information/behaviour/outcomes.
    The governed registry's ``transitivityClasses`` select the leg's authority
    for flow:

    * INFERENTIAL_ONLY   -> weak inferred-affinity flow (ceiling INFERENTIAL)
    * composable classes -> strongest of PATH/DELEGATION/ATTRIBUTION composable
    * PROPAGATION_ELIGIBLE -> flow may propagate even though the relationship is
      NON_TRANSITIVE as an identity (ceiling PROPAGATION_ONLY)
    * NON_TRANSITIVE only (no propagation authorisation) -> the spine does not
      assert influence flows through this relationship: not certifiable
    * predicate absent from the governed registry -> never certified.
    """
    resolver = _resolver_for(predicate_resolver)
    edge_type = _hop_type(hop)
    if path_length <= 1:
        # Direct observed relationship — reuse path_fidelity's direct-hop model.
        ep = assess_hop_epistemic(index, hop, path_length=1, predicate_resolver=resolver)
        entry = resolver(edge_type)
        predicate = str(entry.get("predicate", "")) if entry else None
        classes = tuple(str(c) for c in (entry.get("transitivityClasses") or ())) if entry else ()
        return HopPropagationAuthority(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=classes,
            usage="direct",
            kind=ep.kind,
            ceiling=ep.ceiling,
            reason=ep.reason,
        )

    entry = resolver(edge_type)
    predicate: Optional[str] = None
    classes: tuple[str, ...] = ()
    if entry is not None:
        predicate = str(entry.get("predicate", "")) or None
        raw_classes = entry.get("transitivityClasses") or ()
        classes = tuple(str(c) for c in raw_classes)

    if not classes:
        return HopPropagationAuthority(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=(),
            usage="propagation",
            kind="uncertified",
            ceiling=CEILING_UNCERTIFIED,
            reason=R_NOT_IN_GOVERNED_REGISTRY,
        )

    if "INFERENTIAL_ONLY" in classes:
        return HopPropagationAuthority(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=classes,
            usage="propagation",
            kind="inferred",
            ceiling=CEILING_INFERENTIAL_ONLY,
            reason="inferential_only_propagation_hop",
        )

    authorizing = {
        c: ceiling for c, ceiling in _COMPOSABLE_AUTHORIZING.items() if c in classes
    }
    if authorizing:
        ceiling = max(authorizing.values())
        return HopPropagationAuthority(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=classes,
            usage="propagation",
            kind="composable",
            ceiling=ceiling,
            reason="relationship_composable_propagation_hop",
        )

    if "PROPAGATION_ELIGIBLE" in classes:
        return HopPropagationAuthority(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=classes,
            usage="propagation",
            kind="propagation",
            ceiling=CEILING_PROPAGATION_ONLY,
            reason="propagation_eligible_hop",
        )

    if "NON_TRANSITIVE" in classes:
        return HopPropagationAuthority(
            index=index,
            edge_type=edge_type,
            predicate=predicate,
            transitivity_classes=classes,
            usage="propagation",
            kind="non_propagating",
            ceiling=CEILING_NON_TRANSITIVE_MISUSE,
            reason=R_NON_PROPAGATING,
        )

    return HopPropagationAuthority(
        index=index,
        edge_type=edge_type,
        predicate=predicate,
        transitivity_classes=classes,
        usage="propagation",
        kind="uncertified",
        ceiling=CEILING_UNCERTIFIED,
        reason="unclassifiable_transitivity",
    )


# ────────────────────────────────────────────────────────────────────────────
# Per-hop measured-value resolution (M7 fidelity-vector dimensions)
# ────────────────────────────────────────────────────────────────────────────


def _coerce_measured(value: object) -> Optional[float]:
    """A measured per-hop value in [0, 1], or None when not a measurement.

    Mirrors ``shared.relationship_fidelity.scoring.passthrough_value``: bools,
    out-of-range and non-numeric inputs are dropped (an out-of-range measurement
    is not coerced into a plausible one).
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= v <= 1.0):
        return None
    return v


def _measurement_vector_for_hop(
    hop: Any,
    index: int,
    mapping: Optional[Mapping[Any, Any]],
) -> Optional[dict[str, Any]]:
    """Locate the measured per-hop dimension dict for one hop.

    Lookup candidates mirror path_fidelity's fidelity-vector resolution: hop
    index (int), an id property, then the synthetic edge signature. Returns None
    when absent or not a dict.
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
            return dict(value)
    return None


def _hop_measured_values(
    hop: Any,
    index: int,
    mapping: Optional[Mapping[Any, Any]],
    input_keys: tuple[str, ...],
) -> dict[str, float]:
    """Present (measured, in-range) per-hop values for the given input keys."""
    vector = _measurement_vector_for_hop(hop, index, mapping)
    if not vector:
        return {}
    out: dict[str, float] = {}
    for key in input_keys:
        v = _coerce_measured(vector.get(key))
        if v is not None:
            out[key] = v
    return out


def _mean_of_present(values: dict[str, float]) -> Optional[float]:
    """Arithmetic mean of the present per-hop measured values (≥1 required)."""
    if not values:
        return None
    return sum(values.values()) / len(values)


def _single_value(values: dict[str, float]) -> Optional[float]:
    if not values:
        return None
    return next(iter(values.values()))


# ────────────────────────────────────────────────────────────────────────────
# Component building
# ────────────────────────────────────────────────────────────────────────────


def _fold(values: tuple[float, ...], fold: FoldKind) -> Optional[float]:
    if not values:
        return None
    if fold == "bottleneck_min":
        return min(values)
    if fold == "assessed_mean":
        return sum(values) / len(values)
    if fold == "contamination_max":
        return max(values)
    return None


def _build_component(
    *,
    component_id: ComponentId,
    material_hop_indexes: tuple[int, ...],
    hops_by_index: Mapping[int, Any],
    measurement_mapping: Optional[Mapping[Any, Any]],
    per_hop_fn: Callable[[dict[str, float]], Optional[float]],
    fold: FoldKind,
    formula_note: str,
    limitations: str,
    per_hop_input_keys: tuple[str, ...],
    no_inputs_reason: str,
    empty_reason: str = R_EMPTY_PATH,
) -> ComponentEstimate:
    display, section = _DISPLAY[component_id]
    if not material_hop_indexes:
        return ComponentEstimate(
            component_id=component_id,
            display_name=display,
            blueprint_section=section,
            state="insufficient_data",
            reason_code=empty_reason,
            reason="no material hops on the path to decompose",
            material_hops=0,
            measured_hops=0,
            limitations=limitations,
        )

    per_hop: list[tuple[int, float]] = []
    for idx in material_hop_indexes:
        hop = hops_by_index[idx]
        values = _hop_measured_values(hop, idx, measurement_mapping, per_hop_input_keys)
        value = per_hop_fn(values)
        if value is not None:
            per_hop.append((idx, round(value, 6)))

    if not per_hop:
        return ComponentEstimate(
            component_id=component_id,
            display_name=display,
            blueprint_section=section,
            state="insufficient_data",
            value=None,
            reason_code=R_NO_MEASURED_INPUTS,
            reason=no_inputs_reason,
            formula=formula_note,
            material_hops=len(material_hop_indexes),
            measured_hops=0,
            limitations=limitations,
        )

    if len(per_hop) < len(material_hop_indexes):
        missing = tuple(i for i in material_hop_indexes if i not in {p for p, _ in per_hop})
        return ComponentEstimate(
            component_id=component_id,
            display_name=display,
            blueprint_section=section,
            state="insufficient_data",
            value=None,
            reason_code=R_PARTIAL_HOP_MEASUREMENT,
            reason=(
                f"measured on {len(per_hop)} of {len(material_hop_indexes)} material "
                f"hops; unmeasured hop(s) {missing} could be arbitrarily weaker — "
                "path-level value not certified"
            ),
            formula=formula_note,
            material_hops=len(material_hop_indexes),
            measured_hops=len(per_hop),
            per_hop_values=tuple(per_hop),
            limitations=limitations,
        )

    folded = _fold(tuple(v for _, v in per_hop), fold)
    value = None if folded is None else round(max(0.0, min(folded, 1.0)), 6)
    return ComponentEstimate(
        component_id=component_id,
        display_name=display,
        blueprint_section=section,
        state="available",
        value=value,
        reason_code="measured",
        reason="measured on every material hop",
        formula=f"{fold}({formula_note})",
        material_hops=len(material_hop_indexes),
        measured_hops=len(per_hop),
        per_hop_values=tuple(per_hop),
        limitations=limitations,
    )


def _build_novel_component(
    material_hop_indexes: tuple[int, ...],
) -> ComponentEstimate:
    """§77 NOVEL ATTENTION — permanently degraded: data not produced in this repo.

    Novel attention must distinguish *new-to-observation* entities/communities
    from *newly-created relationships* (blueprint §77). Neither the entity-entry
    window nor the relationship-neighbourhood membership history required for
    that distinction is produced by any surface in this repo, so the component
    is exposed as an explicitly-degraded ``None`` with ``insufficient_data``.
    Future supplier: an Episode360 / Narrative neighborhood-entry tracker that
    records first-observation instants per entity/community against the path's
    temporal context.
    """
    display, section = _DISPLAY["novel_attention"]
    return ComponentEstimate(
        component_id="novel_attention",
        display_name=display,
        blueprint_section=section,
        state="insufficient_data",
        value=None,
        reason_code=R_NOVELTY_UNSUPPLIED,
        reason=(
            "distinguishing new-to-observation from newly-created requires entity-entry "
            "windows and relationship-neighbourhood history this repo does not produce"
        ),
        formula="unsupported",
        material_hops=len(material_hop_indexes),
        measured_hops=0,
        limitations=(
            "No supplier today. A future Episode360 / Narrative neighbourhood-entry "
            "tracker that records per-entity first-observation instants would supply it."
        ),
    )


def _build_earned_downstream(
    *,
    material_hop_indexes: tuple[int, ...],
    hops_by_index: Mapping[int, Any],
    measurement_mapping: Optional[Mapping[Any, Any]],
) -> ComponentEstimate:
    """§75 EARNED DOWNSTREAM AMPLIFICATION.

    Defined as downstream amplification where *no direct incentive is observed for
    the downstream actor*. On a source->target path the *downstream* actors are the
    receivers on the hops after the originating hop (index >= 1). The per-hop
    input that would measure this is ``downstream_incentive_absence`` — a value no
    current surface produces (per-actor incentive attribution on propagation legs
    is not yet computed), so this component is degraded to ``insufficient_data``
    unless a future EngagementFi incentive-attribution surface supplies it.
    """
    display, section = _DISPLAY["earned_downstream_amplification"]
    downstream = tuple(i for i in material_hop_indexes if i >= 1)
    if not downstream:
        return ComponentEstimate(
            component_id="earned_downstream_amplification",
            display_name=display,
            blueprint_section=section,
            state="not_applicable",
            value=None,
            reason_code=R_NO_DOWNSTREAM_HOP,
            reason="single-hop path has no downstream material hop to amplify",
            formula="n/a",
            material_hops=len(material_hop_indexes),
            measured_hops=0,
            limitations=(
                "Absence of observed direct incentive never proves absence of "
                "incentive (blueprint §75 limitation retained)."
            ),
        )

    estimate = _build_component(
        component_id="earned_downstream_amplification",
        material_hop_indexes=downstream,
        hops_by_index=hops_by_index,
        measurement_mapping=measurement_mapping,
        per_hop_fn=_single_value,
        fold="bottleneck_min",
        no_inputs_reason=(
            f"no measured {display.lower()} evidence on any material hop; "
            "the required per-hop dimensions were not supplied"
        ),
        formula_note="min over downstream-hop downstream_incentive_absence",
        limitations=(
            "Absence of observed direct incentive never proves absence of incentive "
            "(blueprint §75). No current surface produces downstream_incentive_absence; "
            "a future EngagementFi incentive-attribution surface would."
        ),
        per_hop_input_keys=_DOWNSTREAM_INPUTS,
        empty_reason=R_DOWNSTREAM_UNSUPPLIED,
    )
    if estimate.state == "insufficient_data" and estimate.reason_code == R_NO_MEASURED_INPUTS:
        # The reason is not merely "inputs missing from this call": no current
        # surface produces per-hop downstream-incentive-absence at all.
        return ComponentEstimate(
            component_id=estimate.component_id,
            display_name=estimate.display_name,
            blueprint_section=estimate.blueprint_section,
            state=estimate.state,
            value=estimate.value,
            reason_code=R_DOWNSTREAM_UNSUPPLIED,
            reason=(
                "downstream_incentive_absence is not produced by any current surface; "
                "per-actor incentive attribution on propagation legs is not yet computed"
            ),
            formula=estimate.formula,
            material_hops=estimate.material_hops,
            measured_hops=estimate.measured_hops,
            per_hop_values=estimate.per_hop_values,
            limitations=estimate.limitations,
        )
    return estimate


# ────────────────────────────────────────────────────────────────────────────
# Path-level staleness + decision aggregation
# ────────────────────────────────────────────────────────────────────────────


def _default_reference(as_of: Optional[str]) -> datetime:
    if as_of is not None:
        parsed = _coerce_utc(as_of)
        if parsed is not None:
            return parsed
    return datetime.now(timezone.utc)


def _path_staleness(
    hops: list[Any],
    reference: datetime,
    policy: StalenessPolicy,
) -> tuple[list[Any], Literal["fresh", "stale", "unknown", "expired", "not_yet_active"]]:
    """Per-hop staleness assessments and a path-level staleness status.

    Follows path_fidelity's aggregate discipline: the weakest material recency
    wins; if ANY hop has UNKNOWN staleness the path is never reported fresh
    (``status == "unknown"``); an inactive valid window surfaces as the window
    status and is handled by the caller as ``invalid``.
    """
    assessments: list[Any] = []
    for idx, hop in enumerate(hops):
        st = assess_hop_staleness(hop, reference=reference, policy=policy)
        st.index = idx
        assessments.append(st)

    if not assessments:
        return assessments, "unknown"

    if any(not st.validity_ok for st in assessments):
        for st in assessments:
            if not st.validity_ok:
                return assessments, st.status  # type: ignore[return-value]

    if any(st.recency_factor is None for st in assessments):
        return assessments, "unknown"

    limiting = min(assessments, key=lambda st: st.recency_factor)  # type: ignore[arg-type]
    return assessments, limiting.status  # type: ignore[return-value]


# ────────────────────────────────────────────────────────────────────────────
# Public entry point
# ────────────────────────────────────────────────────────────────────────────


def _gated_component(
    component_id: ComponentId,
    *,
    material_hops: int,
    reason_code: str,
    reason: str,
) -> ComponentEstimate:
    display, section = _DISPLAY[component_id]
    return ComponentEstimate(
        component_id=component_id,
        display_name=display,
        blueprint_section=section,
        state="insufficient_data",
        value=None,
        reason_code=reason_code,
        reason=reason,
        formula="gated",
        material_hops=material_hops,
        measured_hops=0,
        limitations="Path-level gate: components are not certified while the path is not decomposable.",
    )


def _certify_failure_components(
    material_hops: int,
    reason_code: str,
    reason: str,
) -> tuple[ComponentEstimate, ...]:
    """All nine components gated to insufficient_data for a path-level failure.

    A path that cannot certify propagation (reject / uncertified / invalid /
    empty) yields nine ``insufficient_data`` estimates — never fabricated lows
    and never zeros.
    """
    return tuple(
        _gated_component(cid, material_hops=material_hops, reason_code=reason_code, reason=reason)
        for cid in ATTENTION_COMPONENTS
    )


def decompose_influence_propagation(
    path_edges: list[Any],
    *,
    source_ref: str,
    target_ref: str,
    as_of: Optional[str] = None,
    fidelity_by_hop: Optional[Mapping[Any, Any]] = None,
    predicate_resolver: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    staleness_policy: Optional[StalenessPolicy] = None,
    reject_non_propagating: bool = True,
) -> InfluencePropagationDecomposition:
    """Decompose the influence propagating source->target along ``path_edges``.

    This is a pure, read-side decomposition into the blueprint §71 nine attention
    categories. It performs no graph writes and never fabricates a component from
    absent evidence.

    Parameters
    ----------
    path_edges:
        Ordered hops from ``source_ref`` toward ``target_ref``. Each hop is a
        ``shared.graph.Edge``-like object or a dict with ``type``/``edge_type``,
        ``from``/``from_vertex_id``, ``to``/``to_vertex_id`` and ``properties``.
    source_ref, target_ref:
        Entity references framing the decomposition (also used as render keys).
    as_of:
        Reference instant for snapshot staleness / validity. ``None`` defaults to
        ``datetime.now(utc)`` (deterministic results require an explicit value).
    fidelity_by_hop:
        Per-hop measured M7 fidelity-vector dimension dicts (see module docstring
        "Measurement inputs"). Keyed by hop index, an id property, or the edge
        signature, mirroring path_fidelity's lookup.
    predicate_resolver:
        Registry resolver override (defaults to the governed relationship-predicate
        registry via path_fidelity's ``predicate_entry_for_edge_type``).
    staleness_policy:
        Snapshot-staleness thresholds; defaults to :class:`StalenessPolicy`.
    reject_non_propagating:
        Strict mode: a governed NON_TRANSITIVE hop that the registry does NOT mark
        PROPAGATION_ELIGIBLE cannot certify influence flow -> decision ``reject``.
        When False the path is down-weighted to the non-propagating ceiling.
    """
    reference = _default_reference(as_of)
    policy = staleness_policy or StalenessPolicy()
    resolver = _resolver_for(predicate_resolver)
    hops = list(path_edges)
    material = tuple(range(len(hops)))

    if not hops:
        estimates = _certify_failure_components(0, R_EMPTY_PATH, "no material hops")
        return InfluencePropagationDecomposition(
            source_ref=source_ref,
            target_ref=target_ref,
            as_of=_iso(reference),
            decision="empty",
            propagation_certified=False,
            reason_codes=(R_EMPTY_PATH,),
            staleness_status="empty",
            hop_count=0,
            min_epistemic_ceiling=None,
            raw_attention=estimates[0],
            incentive_exposed_attention=estimates[1],
            independence_supported_attention=estimates[2],
            earned_downstream_amplification=estimates[3],
            persistent_attention=estimates[4],
            novel_attention=estimates[5],
            relationship_weighted_attention=estimates[6],
            outcome_linked_attention=estimates[7],
            coordination_adjusted_attention=estimates[8],
        )

    hops_by_index = dict(enumerate(hops))
    authorities = [
        assess_hop_propagation_authority(
            idx, hop, path_length=len(hops), predicate_resolver=resolver
        )
        for idx, hop in enumerate(hops)
    ]
    staleness, staleness_status = _path_staleness(hops, reference, policy)

    ceilings = [a.ceiling for a in authorities if a.ceiling is not None]
    min_ceiling = min(ceilings) if ceilings else None

    # Path-level decision.
    reason_codes: list[str] = []

    if any(not st.validity_ok for st in staleness):
        reason_codes.append(R_WINDOW_INACTIVE)
        estimates = _certify_failure_components(len(material), R_WINDOW_INACTIVE,
                                                "a hop's valid-time window is not active at as_of")
        return _build_result(
            source_ref=source_ref, target_ref=target_ref, reference=reference,
            decision="invalid", reason_codes=tuple(reason_codes),
            staleness_status=staleness_status, hop_count=len(hops),
            min_ceiling=None, estimates=estimates,
            authorities=tuple(authorities), staleness=tuple(staleness),
        )

    if any(a.kind == "uncertified" for a in authorities):
        # The registry is authoritative: a hop whose predicate is absent from the
        # governed relationship-predicate registry cannot certify influence flow,
        # so the whole path is uncertified (never fabricated upward).
        reason_codes.append(R_NOT_IN_GOVERNED_REGISTRY)
        estimates = _certify_failure_components(len(material), R_NOT_IN_GOVERNED_REGISTRY,
                                                "a hop's predicate is not in the governed registry")
        return _build_result(
            source_ref=source_ref, target_ref=target_ref, reference=reference,
            decision="uncertified", reason_codes=tuple(reason_codes),
            staleness_status=staleness_status, hop_count=len(hops),
            min_ceiling=min_ceiling, estimates=estimates,
            authorities=tuple(authorities), staleness=tuple(staleness),
        )

    has_non_propagating = any(a.kind == "non_propagating" for a in authorities)
    if has_non_propagating and reject_non_propagating:
        reason_codes.append(R_NON_PROPAGATING)
        estimates = _certify_failure_components(
            len(material), R_NON_PROPAGATING,
            "a governed hop the registry does not authorise to propagate is chained")
        return _build_result(
            source_ref=source_ref, target_ref=target_ref, reference=reference,
            decision="reject", reason_codes=tuple(reason_codes),
            staleness_status=staleness_status, hop_count=len(hops),
            min_ceiling=min_ceiling, estimates=estimates,
            authorities=tuple(authorities), staleness=tuple(staleness),
        )

    decision: InfluenceDecision = "pass"
    if has_non_propagating and not reject_non_propagating:
        decision = "downweight"
        reason_codes.append("non_propagating_relationship_chained_downweighted")

    reason_codes.append("propagation_authority_enforced")
    if not fidelity_by_hop:
        reason_codes.append("influence_inputs_absent_components_degraded")

    # ── Build the nine components ──────────────────────────────────────────
    hops_for_components = hops_by_index
    raw = _build_component(
        component_id="raw_attention",
        material_hop_indexes=material,
        hops_by_index=hops_for_components,
        measurement_mapping=fidelity_by_hop,
        per_hop_fn=_mean_of_present,
        fold="bottleneck_min",
        no_inputs_reason=(
            "no raw-attention evidence on any material hop: interaction_frequency / "
            "interaction_depth were not supplied for any hop"
        ),
        formula_note="per-hop mean(interaction_frequency, interaction_depth) present; min over legs",
        limitations=(
            "Raw attention is volume evidence, NOT evidence of organic affinity "
            "(blueprint §72)."
        ),
        per_hop_input_keys=_RAW_INPUTS,
    )
    incentive = _build_component(
        component_id="incentive_exposed_attention",
        material_hop_indexes=material,
        hops_by_index=hops_for_components,
        measurement_mapping=fidelity_by_hop,
        per_hop_fn=_single_value,
        fold="assessed_mean",
        no_inputs_reason=(
            "no incentive-exposure evidence on any material hop: incentive_exposure "
            "was not assessed on any hop"
        ),
        formula_note="mean over legs of assessed incentive_exposure",
        limitations=(
            "Only hops whose incentive presence/absence was ASSESSED count; an "
            "assessed 0 is evidence-backed, unassessed attention is never organic "
            "(blueprint §73)."
        ),
        per_hop_input_keys=_INCENTIVE_EXPOSED_INPUTS,
    )
    independence = _build_component(
        component_id="independence_supported_attention",
        material_hop_indexes=material,
        hops_by_index=hops_for_components,
        measurement_mapping=fidelity_by_hop,
        per_hop_fn=_single_value,
        fold="bottleneck_min",
        no_inputs_reason=(
            "no independence-support evidence on any material hop: "
            "incentive_independence_support was not supplied on any hop"
        ),
        formula_note="min over legs of incentive_independence_support",
        limitations=(
            "Independence support does not prove psychological motivation "
            "(blueprint §74); unmeasured legs are never counted as independent."
        ),
        per_hop_input_keys=_INDEPENDENCE_INPUTS,
    )
    persistent = _build_component(
        component_id="persistent_attention",
        material_hop_indexes=material,
        hops_by_index=hops_for_components,
        measurement_mapping=fidelity_by_hop,
        per_hop_fn=_single_value,
        fold="bottleneck_min",
        no_inputs_reason=(
            "no persistent-attention evidence on any material hop: persistence was "
            "not supplied on any hop"
        ),
        formula_note="min over legs of persistence",
        limitations=(
            "Persistence requires an explicit duration/window policy (blueprint §76); "
            f"this module records the M7 reference window of {PERSISTENCE_HORIZON_DAYS:g} days "
            "and consumes the measured value as derived upstream."
        ),
        per_hop_input_keys=_PERSISTENT_INPUTS,
    )
    outcome = _build_component(
        component_id="outcome_linked_attention",
        material_hop_indexes=material,
        hops_by_index=hops_for_components,
        measurement_mapping=fidelity_by_hop,
        per_hop_fn=_single_value,
        fold="bottleneck_min",
        no_inputs_reason=(
            "no outcome-linkage evidence on any material hop: outcome_support was "
            "not supplied on any hop"
        ),
        formula_note="min over legs of outcome_support",
        limitations=(
            "Attention/outcome linkage does not automatically establish causality "
            "(blueprint §79); outcome_support is a measured pass-through from Outcome360."
        ),
        per_hop_input_keys=_OUTCOME_INPUTS,
    )
    coordination = _build_component(
        component_id="coordination_adjusted_attention",
        material_hop_indexes=material,
        hops_by_index=hops_for_components,
        measurement_mapping=fidelity_by_hop,
        per_hop_fn=_single_value,
        fold="contamination_max",
        no_inputs_reason=(
            "no coordination evidence on any material hop: "
            "coordination_indicator_strength was not supplied on any hop"
        ),
        formula_note="max over legs of coordination_indicator_strength",
        limitations=(
            "Raw totals are always presented alongside this adjustment — underlying "
            "observations are never deleted (blueprint §80). Coordination presence on "
            "any leg contaminates the path."
        ),
        per_hop_input_keys=_COORDINATION_INPUTS,
    )
    earned = _build_earned_downstream(
        material_hop_indexes=material,
        hops_by_index=hops_for_components,
        measurement_mapping=fidelity_by_hop,
    )
    novel = _build_novel_component(material)

    # Relationship-weighted attention is capped by the weakest material hop's
    # propagation authority (§66 epistemic ceiling) in addition to its fold.
    rel_weight = _build_component(
        component_id="relationship_weighted_attention",
        material_hop_indexes=material,
        hops_by_index=hops_for_components,
        measurement_mapping=fidelity_by_hop,
        per_hop_fn=_mean_of_present,
        fold="bottleneck_min",
        no_inputs_reason=(
            "no relationship-strength evidence on any material hop: reciprocity and "
            "persistence were not supplied on any hop"
        ),
        formula_note=(
            f"weight v{RELATIONSHIP_WEIGHT_FORMULA_VERSION}: per-hop mean(reciprocity, "
            "persistence) present; min over legs, capped by weakest propagation authority"
        ),
        limitations=(
            "Relationship weighting is versioned and contextual (blueprint §78); "
            "follower count is never multiplied by arbitrary engagement. A "
            "unidirectional / unmeasured hop keeps this component from certifying "
            "a low relationship weight."
        ),
        per_hop_input_keys=_RELATIONSHIP_WEIGHT_INPUTS,
    )
    if rel_weight.state == "available" and min_ceiling is not None:
        rel_weight = ComponentEstimate(
            component_id=rel_weight.component_id,
            display_name=rel_weight.display_name,
            blueprint_section=rel_weight.blueprint_section,
            state=rel_weight.state,
            value=round(min(rel_weight.value or 0.0, min_ceiling), 6),
            reason_code=rel_weight.reason_code,
            reason=f"{rel_weight.reason}; capped at epistemic ceiling {min_ceiling:g}",
            formula=rel_weight.formula,
            material_hops=rel_weight.material_hops,
            measured_hops=rel_weight.measured_hops,
            per_hop_values=rel_weight.per_hop_values,
            limitations=rel_weight.limitations,
        )

    return _build_result(
        source_ref=source_ref, target_ref=target_ref, reference=reference,
        decision=decision,
        reason_codes=tuple(reason_codes),
        staleness_status=staleness_status,
        hop_count=len(hops),
        min_ceiling=min_ceiling,
        estimates=(raw, incentive, independence, earned, persistent, novel,
                   rel_weight, outcome, coordination),
        authorities=tuple(authorities),
        staleness=tuple(staleness),
    )


def _iso(reference: datetime) -> str:
    return reference.astimezone(timezone.utc).isoformat()


def _build_result(
    *,
    source_ref: str,
    target_ref: str,
    reference: datetime,
    decision: InfluenceDecision,
    reason_codes: tuple[str, ...],
    staleness_status: Any,
    hop_count: int,
    min_ceiling: Optional[float],
    estimates: tuple[ComponentEstimate, ComponentEstimate, ComponentEstimate,
                     ComponentEstimate, ComponentEstimate, ComponentEstimate,
                     ComponentEstimate, ComponentEstimate, ComponentEstimate],
    authorities: tuple[HopPropagationAuthority, ...],
    staleness: tuple[Any, ...],
) -> InfluencePropagationDecomposition:
    return InfluencePropagationDecomposition(
        source_ref=source_ref,
        target_ref=target_ref,
        as_of=_iso(reference),
        decision=decision,
        propagation_certified=decision in ("pass", "downweight"),
        reason_codes=reason_codes,
        staleness_status=staleness_status,
        hop_count=hop_count,
        min_epistemic_ceiling=min_ceiling,
        raw_attention=estimates[0],
        incentive_exposed_attention=estimates[1],
        independence_supported_attention=estimates[2],
        earned_downstream_amplification=estimates[3],
        persistent_attention=estimates[4],
        novel_attention=estimates[5],
        relationship_weighted_attention=estimates[6],
        outcome_linked_attention=estimates[7],
        coordination_adjusted_attention=estimates[8],
        hop_authority=authorities,
        hop_staleness=staleness,
    )


__all__ = [
    "INFLUENCE_PROPAGATION_ALGORITHM",
    "INFLUENCE_PROPAGATION_VERSION",
    "RELATIONSHIP_WEIGHT_FORMULA_VERSION",
    "PERSISTENCE_HORIZON_DAYS",
    "ATTENTION_COMPONENTS",
    "ComponentId",
    "ComponentState",
    "InfluenceDecision",
    "ComponentEstimate",
    "HopPropagationAuthority",
    "InfluencePropagationDecomposition",
    "assess_hop_propagation_authority",
    "decompose_influence_propagation",
]
