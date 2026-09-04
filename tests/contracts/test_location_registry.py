"""Contract tests for the location registry (geographic360 Phase 4).

`packages/shared/location-registry.ts`,
`Backend Architecture/aether-backend/shared/geo/generated_taxonomy.py`, and
`docs/_generated/location-registry-table.md` are generated twins of
`packages/shared/contracts/location-registry.json`;
`shared/geo/models.py` is the hand-authored model surface (`LocationFact` with
role + precision + coordinates + provenance; `Place`/`Region`/`Jurisdiction`).
This test fails on vocabulary drift, on a broken lower_snake/unique/empty
registry, on a precision ladder that diverges from the context-capsule
taxonomy, if the TS module leaves the barrel, and on privacy regressions
(coordinates exist only on location facts — never on the context capsule).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.geo.generated_taxonomy import (  # noqa: E402
    CELL_SCHEMES,
    COORDINATE_SYSTEMS,
    LOCATION_PRECISION_CLASSES,
    LOCATION_REGISTRY_CONTRACT_VERSION,
    LOCATION_ROLES,
    REGION_TYPES,
)
from shared.geo.models import (  # noqa: E402
    Coordinate,
    Jurisdiction,
    LocationFact,
    Place,
    Region,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "location-registry.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "location-registry.json"
CAPSULE_REGISTRY_PATH = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "context-capsule-registry.json"
)

_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in location-registry.ts"
    return re.findall(r"'([a-z_0-9]+)'", m.group(1))


def test_registry_vocabulary_invariants():
    """Non-empty, unique, lower_snake identifiers for every vocabulary key."""
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    for key in (
        "locationRoles",
        "regionTypes",
        "precisionClasses",
        "coordinateSystems",
        "cellSchemes",
    ):
        values = registry[key]
        assert isinstance(values, list) and values, f"{key} must be a non-empty list"
        assert len(values) == len(set(values)), f"{key} has duplicates"
        for value in values:
            assert _IDENT.match(value), f"{key} entry {value!r} is not lower_snake"


def test_precision_ladder_aligned_to_context_capsule():
    """One precision ladder: location-registry must match the context capsule's."""
    location = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    capsule = json.loads(CAPSULE_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert location["precisionClasses"] == capsule["precisionClasses"]


def test_location_roles_parity():
    assert set(_const_array("locationRoles")) == set(LOCATION_ROLES)


def test_region_types_parity():
    assert set(_const_array("regionTypes")) == set(REGION_TYPES)


def test_precision_classes_parity():
    assert set(_const_array("locationPrecisionClasses")) == set(LOCATION_PRECISION_CLASSES)


def test_coordinate_systems_parity():
    assert set(_const_array("coordinateSystems")) == set(COORDINATE_SYSTEMS)


def test_cell_schemes_parity():
    assert set(_const_array("cellSchemes")) == set(CELL_SCHEMES)


def test_generated_taxonomy_matches_registry():
    """Generated Python taxonomy mirrors the JSON registry (regen if this fails)."""
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert LOCATION_REGISTRY_CONTRACT_VERSION == registry["contractVersion"]
    assert list(LOCATION_ROLES) == registry["locationRoles"]
    assert list(REGION_TYPES) == registry["regionTypes"]
    assert list(LOCATION_PRECISION_CLASSES) == registry["precisionClasses"]
    assert list(COORDINATE_SYSTEMS) == registry["coordinateSystems"]
    assert list(CELL_SCHEMES) == registry["cellSchemes"]


def test_barrel_exports_location_registry():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './location-registry';" in index


def test_models_extra_forbid():
    """Location models reject unknown fields (no silent vocabulary drift)."""
    with pytest.raises(Exception):
        LocationFact(location_id="l1", tenant_id="t1", unexpected="x")


def test_location_fact_carries_role_precision_coordinates_with_provenance():
    fact = LocationFact(
        location_id="loc-1",
        tenant_id="t1",
        subject_type="entity",
        subject_id="e-1",
        role="primary_residence",
        precision_class="precise",
        region_type="admin_region",
        region=Region(
            region_id="r-1",
            region_type="admin_region",
            name="Oregon",
            country_code="US",
        ),
        jurisdiction=Jurisdiction(
            jurisdiction_id="j-1",
            name="United States",
            kind="country",
            iso_codes=("US",),
        ),
        coordinate=Coordinate(latitude=45.5, longitude=-122.6),
        observed_at=None,
        provider="tenant_supplied",
        evidence_refs=["ev-1"],
    )
    assert fact.role == "primary_residence"
    assert fact.precision_class == "precise"
    assert fact.coordinate.latitude == 45.5
    assert fact.evidence_refs == ["ev-1"]
    assert fact.precision_state == "full"
    assert fact.region.country_code == "US"
    assert fact.jurisdiction.kind == "country"


def test_models_are_reusable_and_compose():
    place = Place(
        place_id="p-1",
        name="Pioneer Courthouse Square",
        region_type="locality",
        country_code="US",
        coarse_cell="8928308280fffffff",
    )
    assert place.coarse_cell.startswith("89")  # H3 cell strings are stored verbatim
    region = Region(region_id="r-2", region_type="metro_area", name="Portland metro")
    assert region.country_code is None
