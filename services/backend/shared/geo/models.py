"""Hand-authored shared/geo models (geographic360 Phase 4 — the ONE new
canonical location authority).

The vocabulary tuples (location roles, region types, the precision ladder,
coordinate systems, cell schemes) live in ``shared.geo.generated_taxonomy`` —
regenerate, never edit (``scripts/generate_platform_contracts.py`` owns it).
The taxonomy's canonical source is
``packages/shared/contracts/location-registry.json``.

Privacy shape: coordinates live ONLY on :class:`LocationFact` records and their
resolution targets — never in the context capsule (``LocationObservation`` /
``ContextCapsule`` keep their no-raw-IP / no-lat-lon invariant, parity-tested).
H3 cells are stored as strings on facts/edges; the graph backend never builds a
spatial index. Jurisdiction (:class:`Jurisdiction`) stays a first-class
separation from the observation that locates a subject — never collapsed into
one "address" field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Coordinate(BaseModel):
    """A WGS84 coordinate carried by a :class:`LocationFact`.

    Coordinates never enter context capsules — they live only on location
    facts/edges (and their resolution targets).
    """

    model_config = ConfigDict(extra="forbid")

    latitude: float
    longitude: float
    accuracy_radius_meters: Optional[float] = None
    coordinate_system: str = "wgs84"  # COORDINATE_SYSTEMS


class Place(BaseModel):
    """A named, non-jurisdictional location (venue / landmark / named place).

    Resolution target for facts whose role is venue/site-like (e.g.
    ``venue_association``, ``commercial_destination``).
    """

    model_config = ConfigDict(extra="forbid")

    place_id: str
    name: str
    region_type: str  # REGION_TYPES — 'locality' | 'district' | ...
    parent_region_id: Optional[str] = None
    country_code: Optional[str] = None
    coordinate: Optional[Coordinate] = None
    coarse_cell: Optional[str] = None  # H3 string


class Region(BaseModel):
    """An administrative region (continent → locality), NOT US-only.

    ``region_type`` draws from the registry's region-type hierarchy
    (``country`` / ``admin_region`` / ``admin_subregion`` / ...).
    """

    model_config = ConfigDict(extra="forbid")

    region_id: str
    region_type: str  # REGION_TYPES
    name: str
    country_code: Optional[str] = None
    parent_region_id: Optional[str] = None
    geo_reference: Optional[str] = None  # ISO / statistical identifier


class Jurisdiction(BaseModel):
    """A governing authority whose policy scope a subject's location falls under.

    Kept distinct from the observation that locates a subject — jurisdiction vs
    location is a first-class separation, never collapsed into one address.
    """

    model_config = ConfigDict(extra="forbid")

    jurisdiction_id: str
    name: str
    kind: str  # 'country' | 'state' | 'municipality' | 'supranational' | ...
    iso_codes: tuple[str, ...] = ()
    policy_scope_ref: Optional[str] = None


class LocationFact(BaseModel):
    """A first-class, evidence-carrying WHERE fact for a subject.

    Carries role + precision + coordinates with provenance; resolution targets
    (``place``/``region``/``jurisdiction``) keep jurisdiction separate from
    observation. Precision never exceeds evidence: an ungrounded coordinate is
    a typed missing/degraded state upstream, never invented here.
    """

    model_config = ConfigDict(extra="forbid")

    location_id: str
    tenant_id: str
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    role: str  # LOCATION_ROLES
    precision_class: str  # LOCATION_PRECISION_CLASSES
    region_type: Optional[str] = None  # REGION_TYPES
    place: Optional[Place] = None
    region: Optional[Region] = None
    jurisdiction: Optional[Jurisdiction] = None
    coordinate: Optional[Coordinate] = None
    coarse_cell: Optional[str] = None  # H3 string
    observed_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    source_observation_id: Optional[str] = None  # context-capsule observation id
    provider: Optional[str] = None
    evidence_refs: list[str] = Field(default_factory=list)  # canonical EvidenceRef ids
    precision_state: str = "full"  # 'full' | 'precision_reduced' | 'suppressed'
    schema_version: Optional[str] = None
