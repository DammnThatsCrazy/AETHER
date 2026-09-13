"""Geographic360 spatial-cell tests (G4.3) — client-side H3 string cells.

Pins the client-side H3 substrate:

* cells are plain, deterministic ``h3``-scheme **strings** computed from WGS84
  coordinates (never a spatial index, never PostGIS — the graph backend is
  in-memory/Neptune and Postgres is JSONB);
* the default ``coarse_cell`` resolution is 6 (neighbourhood-scale) and the
  centre of any cell re-indexes to that same cell (stability);
* hierarchical containment (parent / children) and ``k``-ring neighbourhoods
  behave on the v4 API;
* every failure is fail-closed and typed (``SpatialCellError`` subclasses) —
  never a raw h3 exception, never a fabricated cell.
"""

from __future__ import annotations

import pytest

from services.geo import spatial_cells as sc

# A stable canonical pin: Portland, OR at the default coarse resolution.
PORTLAND_LAT = 45.52
PORTLAND_LON = -122.68
PORTLAND_CELL_RES6 = "8628f0007ffffff"
PORTLAND_PARENT_RES5 = "8528f003fffffff"


# --- client-side strings ------------------------------------------------------


def test_cell_is_a_plain_rebuildable_string():
    cell = sc.coordinate_to_cell(PORTLAND_LAT, PORTLAND_LON)
    assert isinstance(cell, str)
    assert sc.is_valid_cell(cell)
    # Deterministic: the same coordinate always yields the same cell string.
    assert sc.coordinate_to_cell(PORTLAND_LAT, PORTLAND_LON) == cell
    # Default resolution is the canonical coarse_cell granularity.
    assert sc.cell_resolution(cell) == sc.COARSE_CELL_RESOLUTION == 6
    # Scheme aligns to the shared location taxonomy.
    assert sc.CELL_SCHEME == "h3"


def test_known_cell_pin():
    # Pinned against h3 4.5's exact output for a fixed WGS84 input at res 6.
    assert sc.coordinate_to_cell(PORTLAND_LAT, PORTLAND_LON, 6) == PORTLAND_CELL_RES6
    assert sc.parent_cell(PORTLAND_CELL_RES6, 5) == PORTLAND_PARENT_RES5


def test_center_stability_across_resolutions():
    # The reported cell centre must re-index to the same cell at every res —
    # centres are authoritative index points, so this is the idempotence
    # invariant that makes stored cells rebuildable.
    for resolution in range(0, 10):
        cell = sc.coordinate_to_cell(PORTLAND_LAT, PORTLAND_LON, resolution)
        lat, lon = sc.cell_to_center(cell)
        assert sc.coordinate_to_cell(lat, lon, resolution) == cell


def test_cell_to_center_shape_and_range():
    lat, lon = sc.cell_to_center(PORTLAND_CELL_RES6)
    assert -90.0 <= lat <= 90.0
    assert -180.0 <= lon <= 180.0


def test_is_valid_cell_fails_closed_on_non_cells():
    assert sc.is_valid_cell(PORTLAND_CELL_RES6) is True
    assert sc.is_valid_cell("8628f0007fffffe") is False  # flipped last hex digit
    assert sc.is_valid_cell("not-a-cell") is False
    assert sc.is_valid_cell("") is False
    assert sc.is_valid_cell(None) is False
    # The string surface is strict: an int cell id is not a valid *string* cell.
    assert sc.is_valid_cell(0x8628F0007FFFFFF) is False


# --- domain fail-closed --------------------------------------------------------


def test_coordinate_out_of_domain_is_typed_error():
    with pytest.raises(sc.CoordinateDomainError):
        sc.coordinate_to_cell(91.0, 0.0)
    with pytest.raises(sc.CoordinateDomainError):
        sc.coordinate_to_cell(0.0, -181.0)
    with pytest.raises(sc.CoordinateDomainError):
        sc.coordinate_to_cell("not-a-number", 0.0)


def test_resolution_out_of_domain_is_typed_error():
    with pytest.raises(sc.ResolutionError):
        sc.coordinate_to_cell(PORTLAND_LAT, PORTLAND_LON, -1)
    with pytest.raises(sc.ResolutionError):
        sc.coordinate_to_cell(PORTLAND_LAT, PORTLAND_LON, 16)


def test_invalid_cell_operations_raise_cell_validation_error():
    with pytest.raises(sc.CellValidationError):
        sc.cell_resolution("garbage")
    with pytest.raises(sc.CellValidationError):
        sc.k_ring("garbage", 1)
    with pytest.raises(sc.CellValidationError):
        sc.cell_to_center("garbage")


def test_impossible_parent_child_moves_raise_resolution_error():
    # Parent of a res-0 cell is impossible; children require a finer target.
    with pytest.raises(sc.ResolutionError):
        sc.parent_cell(sc.coordinate_to_cell(0.0, 0.0, 0), 0)
    with pytest.raises(sc.ResolutionError):
        sc.parent_cell(PORTLAND_CELL_RES6, 6)
    with pytest.raises(sc.ResolutionError):
        sc.child_cells(PORTLAND_CELL_RES6, 6)
    with pytest.raises(sc.ResolutionError):
        sc.child_cells(PORTLAND_CELL_RES6, 4)


def test_negative_ring_radius_is_typed_error():
    with pytest.raises(sc.ResolutionError):
        sc.k_ring(PORTLAND_CELL_RES6, -1)


# --- hierarchy (containment, parent, children) ---------------------------------


def test_child_cells_are_finer_and_contained():
    children = sc.child_cells(PORTLAND_CELL_RES6, 7)
    assert children  # non-empty
    assert all(sc.cell_resolution(child) == 7 for child in children)
    assert all(sc.contains_cell(PORTLAND_CELL_RES6, child) for child in children)
    # A non-pentagon res-6 hexagon subdivides into exactly 7 res-7 hexagons.
    assert len(children) == 7


def test_contains_cell_hierarchy():
    assert sc.contains_cell(PORTLAND_CELL_RES6, PORTLAND_CELL_RES6)  # self
    parent = sc.parent_cell(PORTLAND_CELL_RES6, 5)
    assert sc.contains_cell(parent, PORTLAND_CELL_RES6)
    assert sc.contains_cell(sc.parent_cell(parent, 4), PORTLAND_CELL_RES6)
    # A sibling (same parent, different cell) is not contained.
    parent_children = sc.child_cells(parent, 6)
    sibling = next(c for c in parent_children if c != PORTLAND_CELL_RES6)
    assert not sc.contains_cell(PORTLAND_CELL_RES6, sibling)
    assert not sc.contains_cell(sibling, PORTLAND_CELL_RES6)
    # Invalid cells are never contained.
    assert sc.contains_cell(PORTLAND_CELL_RES6, "garbage") is False
    assert sc.contains_cell("garbage", PORTLAND_CELL_RES6) is False


# --- k-ring neighbourhoods ------------------------------------------------------


def test_k_ring_zero_and_neighbourhood():
    assert sc.k_ring(PORTLAND_CELL_RES6, 0) == [PORTLAND_CELL_RES6]
    disk = sc.k_ring(PORTLAND_CELL_RES6, 2)
    # Non-pentagon disk cardinality: 1 + 3k(k+1) = 19 for k=2.
    assert len(disk) == 19
    assert disk == sorted(disk)  # deterministic ordering
    assert PORTLAND_CELL_RES6 in disk
    assert all(sc.is_valid_cell(c) for c in disk)
    assert sc.k_ring(PORTLAND_CELL_RES6, 2) == disk  # deterministic across calls


def test_exact_ring_cardinality():
    assert sc.ring(PORTLAND_CELL_RES6, 0) == [PORTLAND_CELL_RES6]
    assert len(sc.ring(PORTLAND_CELL_RES6, 1)) == 6
    assert len(sc.ring(PORTLAND_CELL_RES6, 2)) == 12
    # k-ring(k) == union of rings 0..k.
    assert sc.k_ring(PORTLAND_CELL_RES6, 2) == sorted(
        set().union(*(set(sc.ring(PORTLAND_CELL_RES6, r)) for r in range(3)))
    )
