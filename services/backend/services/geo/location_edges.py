"""Location-fact graph surface (geographic360 G4.2).

A governed :class:`~shared.geo.models.LocationFact` reaches the graph as typed,
evidence-carrying edges — never as a bare table write. This module is the ONE
canonical assembly surface for that mapping (surfaced through ``services/geo``,
the registry row's legacy binding):

* ``LOCATED_AT``           subject -> REGION     (a resolved located-at region at
   declared precision — residence / workplace / declared area)
* ``OBSERVED_IN``          subject -> PLACE      (a single observation at a named
   venue / landmark)
* ``UNDER_JURISDICTION``   subject -> JURISDICTION (the governing policy scope,
   kept distinct from the observation that locates a subject)

Every edge carries the geographic provenance keys registered on
``shared.graph.edge_properties.OPTIONAL_EDGE_PROPERTIES`` (``location_role`` /
``precision_class`` / ``precision_state`` / ``region_type`` / ``coarse_cell``)
and the fact's ``EvidenceRef`` ids on both the edge properties and the gateway
intent. Precision is typed and never exceeds evidence: ``validate_location_fact``
fails closed on an unknown vocabulary id and on a ``precise`` / ``coarse_cell``
claim the fact's evidence cannot support — a downgrade is always a typed
``precision_reduced`` / ``suppressed`` ``precision_state`` upstream, never a
silent coarsening here.

The module is **pure** (no DB / graph I/O): it validates and assembles
:class:`~shared.graph.mutation_gateway.MutationIntent` objects ready for the
canonical :class:`~shared.graph.mutation_gateway.GraphMutationGateway`. The
governed write
path (consent evaluation, vertex materialisation, soft-revoke leaves) lives with
the location-fact ingestion / DSR plane (G4.5); the projection (G4.4) reads the
resulting edges back as a location timeline.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from shared.geo.generated_taxonomy import (
    COORDINATE_SYSTEMS,
    LOCATION_PRECISION_CLASSES,
    LOCATION_ROLES,
    REGION_TYPES,
)
from shared.geo.models import Jurisdiction, LocationFact, Place, Region
from shared.graph.graph import Edge, EdgeType
from shared.graph.mutation_gateway import MutationIntent
from shared.graph.mutation_intents import edge_intent

# Typed precision states — never a silent coarsening. ``precision_reduced`` /
# ``suppressed`` are explicit output states applied by an upstream downgrade;
# this surface only ever carries them through, and validates they are known.
PRECISION_STATES: tuple[str, ...] = ("full", "precision_reduced", "suppressed")

# Sentinel for LocationFact resolution targets that are unknown vocabulary.
_UNKNOWN = "<unknown>"


class LocationFactValidationError(Exception):
    """A LocationFact cannot be surfaced as graph edges (fails closed).

    Aggregates every violation so a caller sees the full reason at once.
    """

    def __init__(self, violations: list[str]) -> None:
        super().__init__("; ".join(violations))
        self.violations = violations


def _kind_name(value: Optional[str]) -> str:
    return value if value else _UNKNOWN


def validate_location_fact(fact: LocationFact) -> None:
    """Fail closed on a LocationFact that cannot be a canonical graph surface.

    Enforced invariants (each independently reported):

    * every vocabulary id is canonical — ``role`` ∈ LOCATION_ROLES,
      ``precision_class`` ∈ LOCATION_PRECISION_CLASSES, ``region_type`` ∈
      REGION_TYPES, ``precision_state`` ∈ PRECISION_STATES, and the coordinate
      system ∈ COORDINATE_SYSTEMS;
    * precision never exceeds evidence — a ``precise`` fact must carry a
      coordinate, and a ``coarse_cell`` fact must carry a coarse cell (or a
      coordinate that can derive one).

    Coordinates stay on location facts only (never context capsules); this
    module never invents a coordinate from a named region.
    """
    violations: list[str] = []

    if fact.role not in LOCATION_ROLES:
        violations.append(
            f"role {_kind_name(fact.role)!r} not in LOCATION_ROLES"
        )
    if fact.precision_class not in LOCATION_PRECISION_CLASSES:
        violations.append(
            f"precision_class {_kind_name(fact.precision_class)!r} "
            "not in LOCATION_PRECISION_CLASSES"
        )
    if fact.precision_state not in PRECISION_STATES:
        violations.append(
            f"precision_state {_kind_name(fact.precision_state)!r} "
            "not in PRECISION_STATES"
        )
    if fact.region_type is not None and fact.region_type not in REGION_TYPES:
        violations.append(
            f"region_type {fact.region_type!r} not in REGION_TYPES"
        )
    if fact.coordinate is not None and (
        fact.coordinate.coordinate_system not in COORDINATE_SYSTEMS
    ):
        violations.append(
            f"coordinate_system {fact.coordinate.coordinate_system!r} "
            "not in COORDINATE_SYSTEMS"
        )

    # Precision never exceeds evidence (coarse_cell-aligned ladder).
    if fact.precision_class == "precise" and fact.coordinate is None:
        violations.append(
            "precision_class 'precise' requires a coordinate "
            "(precision never exceeds evidence)"
        )
    if fact.precision_class == "coarse_cell" and not (
        fact.coarse_cell or fact.coordinate
    ):
        violations.append(
            "precision_class 'coarse_cell' requires a coarse_cell string "
            "or coordinate evidence"
        )

    if violations:
        raise LocationFactValidationError(violations)


def _base_properties(
    *,
    tenant_id: str,
    fact: LocationFact,
    evidence_refs: list[str],
) -> dict:
    """Canonical geographic provenance property set for every location edge."""
    props: dict = {
        "tenant_id": tenant_id,
        "location_role": fact.role,
        "precision_class": fact.precision_class,
        "precision_state": fact.precision_state,
        "evidence_refs": list(evidence_refs),
    }
    if fact.region_type is not None:
        props["region_type"] = fact.region_type
    if fact.coarse_cell:
        props["coarse_cell"] = fact.coarse_cell
    return props


def _build_edge(
    *,
    fact: LocationFact,
    tenant_id: str,
    subject_id: str,
    edge_type: str,
    to_vertex_id: str,
    properties: dict,
    evidence_refs: list[str],
    subject_kind: str,
    source_event_id: Optional[str],
    causality_class: str,
    valid_from: Optional[datetime],
    valid_to: Optional[datetime],
    confidence: float,
) -> MutationIntent:
    return edge_intent(
        Edge(
            edge_type=edge_type,
            from_vertex_id=subject_id,
            to_vertex_id=to_vertex_id,
            properties=properties,
        ),
        operation="edge_created",
        tenant_id=tenant_id,
        actor_kind="system",
        actor_id="geo_surface",
        subject_kind=subject_kind,
        subject_id=subject_id,
        source_event_id=source_event_id or fact.source_observation_id,
        causality_class=causality_class,
        confidence=confidence,
        evidence_refs=evidence_refs,
        valid_from=valid_from.isoformat() if valid_from else None,
        valid_to=valid_to.isoformat() if valid_to else None,
    )


def build_location_edge_intents(
    fact: LocationFact,
    *,
    tenant_id: str,
    subject_id: Optional[str] = None,
    subject_kind: str = "entity",
    source_event_id: Optional[str] = None,
    causality_class: str = "observed_sequence",
    evidence_refs: Optional[list[str]] = None,
    confidence: float = 1.0,
    valid_from: Optional[datetime] = None,
    valid_to: Optional[datetime] = None,
) -> List[MutationIntent]:
    """Assemble the typed, evidence-carrying edges for one LocationFact.

    One edge is emitted per resolution target actually carried by the fact, in
    stable order (region -> ``LOCATED_AT``, place -> ``OBSERVED_IN``,
    jurisdiction -> ``UNDER_JURISDICTION``). A fact that resolves no target
    (e.g. a bare coordinate) assembles nothing — the named-resolution decision
    is an upstream concern, never invented here. Fails closed via
    :func:`validate_location_fact` before assembling anything.
    """
    validate_location_fact(fact)

    subject_id = subject_id or fact.subject_id
    if not subject_id:
        raise LocationFactValidationError(
            ["LocationFact has no subject_id and none was provided"]
        )
    evidence = evidence_refs if evidence_refs is not None else list(fact.evidence_refs)

    base: dict = _base_properties(
        tenant_id=tenant_id, fact=fact, evidence_refs=evidence
    )
    intents: List[MutationIntent] = []

    region: Optional[Region] = fact.region
    if region is not None:
        props = dict(base)
        # The located-at edge carries the resolved region's own granularity.
        props["region_type"] = region.region_type
        intents.append(
            _build_edge(
                fact=fact,
                tenant_id=tenant_id,
                subject_id=subject_id,
                edge_type=EdgeType.LOCATED_AT,
                to_vertex_id=region.region_id,
                properties=props,
                evidence_refs=evidence,
                subject_kind=subject_kind,
                source_event_id=source_event_id,
                causality_class=causality_class,
                valid_from=valid_from,
                valid_to=valid_to,
                confidence=confidence,
            )
        )

    place: Optional[Place] = fact.place
    if place is not None:
        props = dict(base)
        if place.region_type is not None:
            props["region_type"] = place.region_type
        intents.append(
            _build_edge(
                fact=fact,
                tenant_id=tenant_id,
                subject_id=subject_id,
                edge_type=EdgeType.OBSERVED_IN,
                to_vertex_id=place.place_id,
                properties=props,
                evidence_refs=evidence,
                subject_kind=subject_kind,
                source_event_id=source_event_id,
                causality_class=causality_class,
                valid_from=valid_from,
                valid_to=valid_to,
                confidence=confidence,
            )
        )

    jurisdiction: Optional[Jurisdiction] = fact.jurisdiction
    if jurisdiction is not None:
        props = dict(base)
        intents.append(
            _build_edge(
                fact=fact,
                tenant_id=tenant_id,
                subject_id=subject_id,
                edge_type=EdgeType.UNDER_JURISDICTION,
                to_vertex_id=jurisdiction.jurisdiction_id,
                properties=props,
                evidence_refs=evidence,
                subject_kind=subject_kind,
                source_event_id=source_event_id,
                causality_class=causality_class,
                valid_from=valid_from,
                valid_to=valid_to,
                confidence=confidence,
            )
        )

    return intents


__all__ = [
    "PRECISION_STATES",
    "LocationFactValidationError",
    "build_location_edge_intents",
    "validate_location_fact",
]
