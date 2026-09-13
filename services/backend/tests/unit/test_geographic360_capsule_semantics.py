"""context_capsule_semantics authority (geographic360 G4.5-C2).

G4.5-C2 formalizes the registry row's pending ``context_capsule_semantics``
spine authority as the pure rule set that turns a privacy-shaped capsule
:class:`~shared.context_capsule.models.LocationObservation` into a canonical
geographic reading. This suite pins:

* role resolution: capsule *semantics* (what the observation means) win, an
  unresolved/unknown semantics defers to the *source*, and neither resolving
  falls back to ``observed_presence`` — never a stronger claim;
* precision: derived from the labels the observation actually carries, capped at
  ``coarse_cell`` and never ``precise`` (a capsule has no coordinate, whatever
  ``device_precise`` the source declared);
* the write-side builder :func:`capsule_location_fact`: provenance stamped
  ``provider=context_capsule`` + ``source_observation_id``, **no coordinate and
  no invented jurisdiction**, region granularity lifted from the flat labels;
* the read guard :func:`normalise_capsule_fact_row`: applied by the default
  geographic reader to capsule-provenance rows, it strips any coordinate and
  clamps a ``precise`` over-claim down to what the labels support (a copy —
  the store is never mutated by a read).

End-to-end, a capsule-sourced fact (even one a buggy writer recorded with a
coordinate and ``precise`` precision) reads back through
:class:`~services.geographic360.provider.GeographicLocationReader` with no
coordinate echoed and precision never finer than its labels.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402

from services.geo.location_facts import location_fact_repo  # noqa: E402
from services.geographic360 import (  # noqa: E402
    CAPSULE_LOCATION_PROVIDER,
    SEMANTIC_ROLE,
    SOURCE_ROLE,
    capsule_location_fact,
    capsule_precision_class,
    capsule_role,
    normalise_capsule_fact_row,
)
from services.geographic360.provider import (  # noqa: E402
    GeographicLocationReader,
)

from shared.context_capsule.generated_taxonomy import (  # noqa: E402
    LOCATION_SEMANTICS,
    LOCATION_SOURCES,
)
from shared.context_capsule.models import LocationObservation  # noqa: E402
from shared.geo.generated_taxonomy import (  # noqa: E402
    LOCATION_ROLES,
    LOCATION_PRECISION_CLASSES,
)
from shared.geo.models import (  # noqa: E402
    Coordinate,
    LocationFact,
    Region,
)

TENANT_A = "tenant_geo_capsule_a"

_NOW = datetime.now(timezone.utc)


def _obs(
    *,
    observation_id: str = "obs-1",
    source: str = "device_coarse",
    semantics: str = "likely_physical_presence",
    country_code: str | None = "US",
    region_code: str | None = "OR",
    city: str | None = "Portland",
    coarse_cell: str | None = None,
    observed_at: datetime = _NOW,
    **extra: object,
) -> LocationObservation:
    return LocationObservation(
        observation_id=observation_id,
        tenant_id=TENANT_A,
        source=source,
        semantics=semantics,
        precision_class="precise",  # a capsule source may *say* precise; labels govern
        country_code=country_code,
        region_code=region_code,
        city=city,
        coarse_cell=coarse_cell,
        observed_at=observed_at,
        **extra,  # type: ignore[arg-type]
    )


# ── role resolution: semantics win, then source, then observed_presence ───────


def test_role_resolution_follows_semantics_then_source():
    # Semantics (what the observation means) win over the source.
    assert capsule_role("network_egress", "tenant_supplied_venue") == "network_egress"
    assert capsule_role("billing_jurisdiction", "device_coarse") == "billing_address"
    assert capsule_role("execution_region", "shipping_address") == "agent_execution_region"
    assert capsule_role("declared_address", "server_network_ip") == "declared_address"

    # An unknown semantics defers to the source (where the observation came from).
    assert capsule_role("unknown", "server_network_ip") == "network_egress"
    assert capsule_role("unknown", "shipping_address") == "shipping_address"
    assert capsule_role("unknown", "organization_registered") == "organization_registered"

    # Neither resolving falls back to observed_presence — never a stronger claim.
    assert capsule_role("unknown", "provider_reported") == "observed_presence"
    assert capsule_role("not-a-semantics", "not-a-source") == "observed_presence"


def test_presence_semantics_never_claim_residence():
    # One observation of presence is presence — never a residence conclusion.
    for semantics in ("likely_physical_presence", "verified_physical_presence"):
        assert capsule_role(semantics, "device_precise") == "observed_presence"


def test_semantic_and_source_maps_stay_in_their_taxonomy():
    # Governance guard: the maps only ever reference known taxonomy members, so
    # a taxonomy rename cannot silently break the reading authority.
    assert set(SEMANTIC_ROLE.keys()) <= set(LOCATION_SEMANTICS)
    assert set(SEMANTIC_ROLE.values()) <= set(LOCATION_ROLES)
    assert set(SOURCE_ROLE.keys()) <= set(LOCATION_SOURCES)
    assert set(SOURCE_ROLE.values()) <= set(LOCATION_ROLES)


def test_source_fallback_covers_every_capsule_source():
    # Every taxonomy source must resolve to a geo role (via semantics or source).
    for source in LOCATION_SOURCES:
        role = capsule_role("unknown", source)
        assert role in LOCATION_ROLES, f"no role resolved for source {source!r}"


# ── precision: derived from carried labels, capped at coarse_cell ─────────────


def test_precision_is_derived_from_carried_labels():
    assert capsule_precision_class(_obs(city=None, region_code=None, country_code=None)) is None
    assert capsule_precision_class(_obs(city=None, region_code=None)) == "country"
    assert capsule_precision_class(_obs(city=None, region_code="OR")) == "region"
    assert capsule_precision_class(_obs()) == "city"
    assert capsule_precision_class(_obs(coarse_cell="h3:abc")) == "coarse_cell"


def test_precision_is_never_precise_even_when_the_source_says_precise():
    # device_precise with only a coarse cell reads coarse_cell, not precise:
    # a capsule never carries a coordinate, so precise is unreachable.
    obs = _obs(source="device_precise", coarse_cell="h3:abc")
    assert obs.precision_class == "precise"
    assert capsule_precision_class(obs) == "coarse_cell"


# ── write-side builder: capsule_location_fact ─────────────────────────────────


def test_capsule_location_fact_maps_labels_onto_a_canonical_fact():
    obs = _obs(
        observation_id="obs-full",
        semantics="verified_physical_presence",
        source="device_coarse",
        country_code="US",
        region_code="OR",
        city="Portland",
        coarse_cell="h3:abc",
    )
    fact = capsule_location_fact(obs, subject_type="entity", subject_id="ent-portland")

    assert fact.location_id == "capsule:obs-full"
    assert fact.tenant_id == TENANT_A
    assert fact.subject_type == "entity"
    assert fact.subject_id == "ent-portland"
    assert fact.role == "observed_presence"
    assert fact.precision_class == "coarse_cell"  # labels cap, never precise
    assert fact.provider == CAPSULE_LOCATION_PROVIDER
    assert fact.source_observation_id == "obs-full"
    assert fact.observed_at == obs.observed_at

    # Region granularity lifted from flat labels (city + admin code).
    assert fact.region is not None
    assert fact.region.region_type == "city"
    assert fact.region.name == "Portland"
    assert fact.region.country_code == "US"
    assert fact.region.geo_reference == "OR"
    assert fact.region_type == "city"

    # Privacy invariants: no coordinate, no invented jurisdiction, cell carried.
    assert fact.coordinate is None
    assert fact.jurisdiction is None
    assert fact.coarse_cell == "h3:abc"


def test_capsule_location_fact_country_only_reading():
    fact = capsule_location_fact(
        _obs(
            observation_id="obs-country",
            semantics="billing_jurisdiction",
            source="payment_instrument_country",
            country_code="DE",
            region_code=None,
            city=None,
        ),
        subject_type="entity",
        subject_id="ent-berlin",
    )
    assert fact.role == "billing_address"
    assert fact.precision_class == "country"
    assert fact.region is not None
    assert fact.region.region_type == "country"
    assert fact.region.name == "DE"  # country-only label names the code
    assert fact.coarse_cell is None


def test_capsule_location_fact_coarse_cell_only_carries_no_region():
    fact = capsule_location_fact(
        _obs(
            observation_id="obs-cell",
            semantics="unknown",
            source="server_network_ip",
            country_code=None,
            region_code=None,
            city=None,
            coarse_cell="h3:abc",
        ),
        subject_type="entity",
        subject_id="ent-cell",
    )
    assert fact.role == "network_egress"
    assert fact.precision_class == "coarse_cell"
    assert fact.region is None
    assert fact.coarse_cell == "h3:abc"


def test_capsule_location_fact_requires_a_named_subject_and_a_location():
    obs = _obs()
    with pytest.raises(ValueError, match="named subject"):
        capsule_location_fact(obs, subject_type="", subject_id="ent-x")
    with pytest.raises(ValueError, match="named subject"):
        capsule_location_fact(obs, subject_type="entity", subject_id="")

    blank = _obs(country_code=None, region_code=None, city=None)
    with pytest.raises(ValueError, match="no usable coarse location"):
        capsule_location_fact(blank, subject_type="entity", subject_id="ent-x")


# ── read guard: normalise_capsule_fact_row ────────────────────────────────────


def test_normalise_returns_a_copy_and_leaves_honest_rows_alone():
    honest = {
        "provider": CAPSULE_LOCATION_PROVIDER,
        "precision_class": "coarse_cell",
        "region": {"region_type": "city", "name": "Portland"},
        "coarse_cell": "h3:abc",
        "country_code": "US",
    }
    result = normalise_capsule_fact_row(honest)
    assert result == honest
    assert result is not honest


def test_normalise_strips_a_coordinate_from_capsule_rows():
    row = {
        "provider": CAPSULE_LOCATION_PROVIDER,
        "precision_class": "city",
        "coordinate": {"latitude": 45.5, "longitude": -122.6},
        "place": {"name": "Powell's", "coordinate": {"latitude": 45.5, "longitude": -122.6}},
        "region": {"region_type": "city", "name": "Portland"},
    }
    result = normalise_capsule_fact_row(row)
    assert result["coordinate"] is None
    assert result["place"]["coordinate"] is None
    # The input row is never mutated by a read.
    assert row["coordinate"] is not None
    assert row["place"]["coordinate"] is not None


def test_normalise_clamps_precise_down_to_carried_labels():
    # A capsule row claiming precise with only a coarse cell -> coarse_cell.
    cell_row = {
        "provider": CAPSULE_LOCATION_PROVIDER,
        "precision_class": "precise",
        "coarse_cell": "h3:abc",
        "country_code": "US",
    }
    assert normalise_capsule_fact_row(cell_row)["precision_class"] == "coarse_cell"

    # ... with only a city label -> city (never finer than the labels).
    city_row = {
        "provider": CAPSULE_LOCATION_PROVIDER,
        "precision_class": "precise",
        "region": {"region_type": "city", "name": "Portland", "country_code": "US"},
    }
    assert normalise_capsule_fact_row(city_row)["precision_class"] == "city"


# ── reader seam: capsule rows enforce invariants end-to-end ───────────────────


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_reader_applies_capsule_read_guard_to_tampered_row():
    # Simulate a buggy writer: a capsule-provenance fact recorded WITH a
    # coordinate and a precise over-claim. The read boundary must never render
    # either — no coordinate echoed, precision clamped to what the labels carry.
    tampered = LocationFact(
        location_id="capsule:obs-tampered",
        tenant_id=TENANT_A,
        subject_type="entity",
        subject_id="ent-portland",
        role="observed_presence",
        precision_class="precise",
        region=Region(
            region_id="region:obs-tampered",
            region_type="city",
            name="Portland",
            country_code="US",
            geo_reference="OR",
        ),
        coordinate=Coordinate(latitude=45.5, longitude=-122.6),
        observed_at=_NOW,
        provider=CAPSULE_LOCATION_PROVIDER,
        source_observation_id="obs-tampered",
    )
    await location_fact_repo.record(tampered)

    view = await GeographicLocationReader().view(
        tenant_id=TENANT_A, subject_kind="entity", subject_id="ent-portland"
    )
    assert view.missing_reason is None
    row = view.posture.facts[0]
    assert row.provider == CAPSULE_LOCATION_PROVIDER
    assert row.coordinate_present is False  # never echoed
    assert row.precision_class == "city"  # clamped, never precise
    assert row.city == "Portland"
    assert row.country_code == "US"


@pytest.mark.asyncio
async def test_reader_projects_a_capsule_location_fact_store_backed():
    # The full happy path: capsule observation -> canonical fact -> store ->
    # store-backed default reader, with provenance and caps intact.
    obs = _obs(
        observation_id="obs-legit",
        semantics="verified_physical_presence",
        source="device_coarse",
        country_code="US",
        region_code="OR",
        city="Portland",
        coarse_cell="h3:abc",
    )
    fact = capsule_location_fact(obs, subject_type="entity", subject_id="ent-portland")
    await location_fact_repo.record(fact)

    view = await GeographicLocationReader().view(
        tenant_id=TENANT_A, subject_kind="entity", subject_id="ent-portland"
    )
    assert view.missing_reason is None
    row = view.posture.facts[0]
    assert row.location_id == "capsule:obs-legit"
    assert row.role == "observed_presence"
    assert row.precision_class == "coarse_cell"
    assert row.provider == CAPSULE_LOCATION_PROVIDER
    assert row.city == "Portland"
    assert row.region_code == "OR"
    assert row.country_code == "US"
    assert row.coarse_cell == "h3:abc"
    assert row.coordinate_present is False
    assert row.jurisdiction_name is None  # no invented jurisdiction
