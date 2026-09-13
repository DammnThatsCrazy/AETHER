"""context_capsule_semantics — capsule observation -> canonical geographic reading.

The ``geographic360`` registry row declares ``context_capsule_semantics`` as a
pending spine authority it resolves against ("context-capsule plane not yet
formalized"). G4.5-C2 formalizes that authority as this module: the pure rule
set that turns one privacy-shaped capsule :class:`LocationObservation` into a
canonical geographic reading, consumed through the geographic360 provider's
reader seam.

Two boundaries, one rule set:

* **Internal write** — :func:`capsule_location_fact` maps one
  :class:`~shared.context_capsule.models.LocationObservation` onto a canonical
  :class:`~shared.geo.models.LocationFact` that a future context-capsule
  ingestion path writes through :class:`~services.geo.location_facts`
  ``record`` (the G4.5 internal write plane — no public route/consent surface
  ships here).
* **Read guard** — :func:`normalise_capsule_fact_row` is applied by the default
  :class:`~services.geographic360.provider.GeographicLocationReader` to every
  stored row whose ``provider`` is the capsule authority, so capsule-derived
  evidence can **never** render finer than it really is.

Honesty invariants (all parity with the capsule contract, which deliberately
carries no raw IP and no lat/lon):

* **Never ``precise``.** A capsule observation has no coordinate, so its finest
  honest class is ``coarse_cell``. Precision is *derived from the labels the
  observation carries* — an observation declaring ``device_precise`` but only
  holding a coarse cell still reads ``coarse_cell``.
* **A coordinate is never emitted or echoed.** The write never sets one and the
  read guard strips any that would appear (defence in depth against a buggy
  writer), so ``coordinate_present`` stays ``False`` for capsule rows.
* **No invented jurisdiction.** A capsule observation locates a subject; it does
  not declare who governs it. ``jurisdiction`` is left unset — the
  jurisdiction-vs-location separation is never collapsed.

Roles resolve from the capsule semantics (what the observation *means*), then
from the source (where it *came from*), then to ``observed_presence``. The
mapping never fabricates a stronger claim than the evidence supports.
"""

from __future__ import annotations

from copy import copy
from typing import Optional

from shared.context_capsule.models import LocationObservation
from shared.geo.generated_taxonomy import LOCATION_PRECISION_CLASSES
from shared.geo.models import LocationFact, Region

# Provenance marker stored on every capsule-derived location fact. The store and
# the reader use it to recognize capsule rows so the read guard applies.
CAPSULE_LOCATION_PROVIDER = "context_capsule"

# Finest precision class a capsule observation can ground. Coarse cells live on
# the H3 scheme; finer-than-cell claims need a coordinate, which capsules never
# carry — so this authority never emits a ``precise`` fact.
MAX_CAPSULE_PRECISION = "coarse_cell"

_CLASS_RANK = {
    name: index for index, name in enumerate(LOCATION_PRECISION_CLASSES)
}

# Default role when neither semantics nor source resolves a claim.
DEFAULT_ROLE = "observed_presence"

# Capsule semantics (what a location observation means) -> canonical geo role.
# Deliberately conservative: an observed/reported presence is ``observed_presence``,
# never ``likely_residence``/``primary_residence`` — residence is a conclusion,
# not one observation. ``unknown`` is absent on purpose: ``capsule_role`` treats
# an unresolved semantics as a source-based guess. Each value is a member of the
# geo LOCATION_ROLES tuple.
SEMANTIC_ROLE: dict[str, str] = {
    "network_egress": "network_egress",
    "likely_physical_presence": "observed_presence",
    "verified_physical_presence": "observed_presence",
    "declared_address": "declared_address",
    "commercial_destination": "commercial_destination",
    "billing_jurisdiction": "billing_address",
    "organization_location": "organization_registered",
    "execution_region": "agent_execution_region",
    "venue_association": "venue_association",
}

# Capsule source (where the observation came from) -> canonical geo role. Only
# consulted when the semantics do not resolve (unknown), so a declared intent
# always beats a source guess.
SOURCE_ROLE: dict[str, str] = {
    "server_network_ip": "network_egress",
    "device_coarse": "observed_presence",
    "device_precise": "observed_presence",
    "verified_venue": "venue_association",
    "tenant_supplied_venue": "venue_association",
    "qr_or_checkin": "venue_association",
    "shipping_address": "shipping_address",
    "billing_address": "billing_address",
    "payment_instrument_country": "billing_address",
    "provider_reported": "observed_presence",
    "organization_registered": "organization_registered",
    "agent_execution_region": "agent_execution_region",
    "server_execution_region": "agent_execution_region",
    "imported_historical": "observed_presence",
}


def capsule_role(semantics: str, source: str) -> str:
    """Resolve the canonical geo role for a capsule observation.

    Semantics (what the observation means) win; an unresolved/unknown semantics
    defers to the source; neither resolving falls back to ``observed_presence``.
    Never fabricates a stronger claim than the semantics carry.
    """
    role = SEMANTIC_ROLE.get(semantics)
    if role is None:
        role = SOURCE_ROLE.get(source)
    return role or DEFAULT_ROLE


def capsule_precision_class(observation: LocationObservation) -> Optional[str]:
    """Finest honest precision the observation's carried labels support.

    Derived from the labels actually present (coarse cell > city > region >
    country), capped at ``coarse_cell`` — a capsule has no coordinate, so
    ``precise`` is unreachable no matter what ``precision_class`` the source
    declared. Returns ``None`` when the observation carries no usable coarse
    location at all.
    """
    if observation.coarse_cell:
        return MAX_CAPSULE_PRECISION
    if observation.city:
        return "city"
    if observation.region_code:
        return "region"
    if observation.country_code:
        return "country"
    return None


def _capsule_region(observation: LocationObservation) -> Optional[Region]:
    """Administrative region lifted from the observation's flat labels.

    A city resolves to a ``city`` region (the admin code travels as
    ``geo_reference``); a bare region code to an ``admin_region``; a country-only
    observation to a ``country`` region. No region when none of the labels exist
    (a coarse-cell-only observation locates without an administrative label).
    """
    region_id = f"capsule-region:{observation.observation_id}"
    if observation.city:
        return Region(
            region_id=region_id,
            region_type="city",
            name=observation.city,
            country_code=observation.country_code,
            geo_reference=observation.region_code,
        )
    if observation.region_code:
        return Region(
            region_id=region_id,
            region_type="admin_region",
            name=observation.region_code,
            country_code=observation.country_code,
            geo_reference=observation.region_code,
        )
    if observation.country_code:
        return Region(
            region_id=region_id,
            region_type="country",
            name=observation.country_code,
            country_code=observation.country_code,
        )
    return None


def capsule_location_fact(
    observation: LocationObservation,
    *,
    subject_type: str,
    subject_id: str,
) -> LocationFact:
    """Map one capsule observation onto a canonical location fact (write side).

    The *internal* authority write builder: it produces the
    :class:`~shared.geo.models.LocationFact` a future context-capsule ingestion
    path records through the ``location_facts`` store. No public route or
    consent surface ships with it — consent gating stays in that ingestion
    path, not in this pure mapping.

    Invariants: role from :func:`capsule_role`, precision from
    :func:`capsule_precision_class` (never ``precise``), no coordinate, no
    jurisdiction, provenance stamped ``provider=context_capsule`` and
    ``source_observation_id=observation_id``. Raises :class:`ValueError` when
    the observation carries no usable coarse location or the subject is unnamed.
    """
    if not subject_type or not subject_id:
        raise ValueError(
            "a capsule-derived location fact needs a named subject "
            "(subject_type and subject_id are required)"
        )
    precision = capsule_precision_class(observation)
    if precision is None:
        raise ValueError(
            "capsule observation carries no usable coarse location "
            "(none of country_code / region_code / city / coarse_cell set)"
        )
    region = _capsule_region(observation)
    return LocationFact(
        location_id=f"capsule:{observation.observation_id}",
        tenant_id=observation.tenant_id,
        subject_type=subject_type,
        subject_id=subject_id,
        role=capsule_role(observation.semantics, observation.source),
        precision_class=precision,
        region_type=region.region_type if region is not None else None,
        region=region,
        coarse_cell=observation.coarse_cell,
        observed_at=observation.observed_at,
        source_observation_id=observation.observation_id,
        provider=CAPSULE_LOCATION_PROVIDER,
        precision_state="full",
    )


def _labels_carry_class_index(stored: dict) -> Optional[int]:
    """Finest class the labels of a stored row actually support (pure).

    Mirrors the provider's label semantics (a city region lifts to a city, a
    country/continent region to a country, a name carries its region type) but
    never treats a coordinate as present — this is the capsule read guard, and
    a coordinate is stripped before this runs.
    """
    region = stored.get("region") or {}
    place = stored.get("place") or {}
    if stored.get("coarse_cell") or place.get("coarse_cell"):
        return _CLASS_RANK["coarse_cell"]
    region_type = region.get("region_type")
    if region.get("name"):
        if region_type == "city":
            return _CLASS_RANK["city"]
        if region_type in ("country", "continent"):
            return _CLASS_RANK["country"]
        return _CLASS_RANK["region"]
    if place.get("name"):
        return _CLASS_RANK["city"]
    if region.get("geo_reference"):
        return _CLASS_RANK["region"]
    if (
        stored.get("country_code")
        or region.get("country_code")
        or place.get("country_code")
    ):
        return _CLASS_RANK["country"]
    return None


def normalise_capsule_fact_row(stored: dict) -> dict:
    """Read-boundary guard for one stored capsule-provenance fact row.

    Applied by the default geographic reader to every row whose ``provider`` is
    the capsule authority. Returns a **copy** — the store is never mutated by a
    read. Enforces the two capsule invariants at the render boundary:

    * a coordinate (top-level or on ``place``) is stripped, so a capsule row can
      never echo one (``coordinate_present`` stays ``False``);
    * a ``precision_class`` finer than the labels support (notably ``precise``,
      which no capsule can ground) is clamped down to the class the labels
      actually carry — capped at ``coarse_cell`` by construction.
    """
    result = copy(stored)
    if result.get("coordinate") is not None:
        result["coordinate"] = None
    place = result.get("place")
    if isinstance(place, dict) and place.get("coordinate") is not None:
        result["place"] = {**place, "coordinate": None}
    precision = result.get("precision_class")
    stored_rank = _CLASS_RANK.get(precision)
    if stored_rank is not None:
        carried = _labels_carry_class_index(result)
        if carried is not None and stored_rank > carried:
            result["precision_class"] = LOCATION_PRECISION_CLASSES[carried]
    return result


__all__ = [
    "CAPSULE_LOCATION_PROVIDER",
    "DEFAULT_ROLE",
    "MAX_CAPSULE_PRECISION",
    "SEMANTIC_ROLE",
    "SOURCE_ROLE",
    "capsule_location_fact",
    "capsule_precision_class",
    "capsule_role",
    "normalise_capsule_fact_row",
]
