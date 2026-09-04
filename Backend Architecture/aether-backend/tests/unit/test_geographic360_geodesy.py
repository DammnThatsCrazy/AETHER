"""Geographic360 geodesy tests (G4.3) — pure-python WGS84 distance.

Pins the geographiclib substrate:

* geodesic distances match independent great-circle (haversine) computation and
  real-world anchors — computed in pure python, never via PostGIS;
* H3 cell-centroid distances delegate to the same geodesic;
* out-of-domain / non-numeric inputs fail closed with a typed
  ``CoordinateDomainError``.
"""

from __future__ import annotations

import math

import pytest

from services.geo.geodesy import cell_centroid_distance_m, geodesic_distance_m
from services.geo.spatial_cells import (
    CoordinateDomainError,
    SpatialCellError,
    cell_to_center,
    coordinate_to_cell,
    k_ring,
)


def _haversine_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Independent great-circle distance (metres) on a 6371 km sphere.

    Used purely as a cross-check; geodesic distance on the ellipsoid differs
    from this by well under 0.5% for non-antipodal city-scale baselines.
    """
    radius = 6371000.0
    phi_a = math.radians(lat_a)
    phi_b = math.radians(lat_b)
    dphi = math.radians(lat_b - lat_a)
    dlambda = math.radians(lon_b - lon_a)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(
        dlambda / 2
    ) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


# Real-world anchors (city centres).
PORTLAND = (45.52, -122.68)
SEATTLE = (47.6062, -122.3321)
NYC = (40.7128, -74.0060)
LOS_ANGELES = (34.0522, -118.2437)


def test_zero_distance_for_identical_points():
    assert geodesic_distance_m(*PORTLAND, *PORTLAND) == pytest.approx(0.0, abs=1e-6)


def test_distance_matches_independent_haversine():
    got = geodesic_distance_m(*NYC, *LOS_ANGELES)
    expected = _haversine_m(*NYC, *LOS_ANGELES)
    # Ellipsoid vs sphere differs by < 0.5% at continental scale.
    assert abs(got - expected) / expected < 0.005


def test_real_world_anchor_portland_seattle():
    # ~230 km by road-less great circle; geodesic on the WGS84 ellipsoid.
    got = geodesic_distance_m(*PORTLAND, *SEATTLE)
    assert 225_000 <= got <= 235_000
    # Symmetric.
    assert geodesic_distance_m(*SEATTLE, *PORTLAND) == pytest.approx(got, rel=1e-9)


def test_distance_is_positive_and_monotonic():
    portland_vancouver = geodesic_distance_m(45.52, -122.68, 49.2827, -123.1207)
    portland_seattle = geodesic_distance_m(*PORTLAND, *SEATTLE)
    assert portland_seattle < portland_vancouver
    assert portland_vancouver > 100_000


def test_cell_centroid_distance_delegates_to_geodesic():
    cell_a = coordinate_to_cell(*PORTLAND)
    # A distinct res-6 neighbour two rings out.
    far = k_ring(cell_a, 2)[-1]
    lat_a, lon_a = cell_to_center(cell_a)
    lat_b, lon_b = cell_to_center(far)
    expected = geodesic_distance_m(lat_a, lon_a, lat_b, lon_b)
    assert cell_centroid_distance_m(cell_a, far) == pytest.approx(expected, rel=1e-9)
    assert cell_centroid_distance_m(cell_a, cell_a) == pytest.approx(0.0, abs=1e-6)


def test_invalid_cell_distance_raises_spatial_cell_error():
    with pytest.raises(SpatialCellError):
        cell_centroid_distance_m("garbage", coordinate_to_cell(*PORTLAND))


def test_out_of_domain_coordinates_fail_closed():
    with pytest.raises(CoordinateDomainError):
        geodesic_distance_m(91.0, 0.0, 0.0, 0.0)
    with pytest.raises(CoordinateDomainError):
        geodesic_distance_m(0.0, 0.0, 0.0, 181.0)
    with pytest.raises(CoordinateDomainError):
        geodesic_distance_m("nan-coordinate", 0.0, 0.0, 0.0)
