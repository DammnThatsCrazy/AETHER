"""Client-side H3 spatial cells (geographic360 G4.3).

H3 cell strings are the coarse/precise location vocabulary carried on facts and
edges — ``LocationFact.coarse_cell``, ``Place.coarse_cell`` and the graph-edge
``coarse_cell`` provenance key. Cells are computed **in the application** from
WGS84 coordinates and stored as **plain strings**: the graph backend is
in-memory/Neptune and Postgres is JSONB, so there is NO PostGIS and no
materialized spatial index — cells are rebuildable at any time.

``coarse_cell`` sits between ``city`` and ``precise`` on the shared precision
ladder (``shared.geo.generated_taxonomy``). This module's default resolution
(H3 resolution 6, neighbourhood-scale hexagons, ~1 km edges, ~36 km²) is that
``coarse_cell`` granularity.

Every helper fails closed: invalid cells, out-of-domain coordinates and
impossible resolution moves raise a :class:`SpatialCellError` subclass — never a
raw h3 exception and never a fabricated cell. The only public surface is
``h3``-scheme string cells.
"""

from __future__ import annotations

import h3

CELL_SCHEME = "h3"  # matches CELL_SCHEMES in shared.geo.generated_taxonomy

H3_MIN_RESOLUTION = 0
H3_MAX_RESOLUTION = 15

# Default ``coarse_cell`` granularity: H3 resolution 6. Coarser than a precise
# coordinate, finer than a city — exactly where ``coarse_cell`` sits on the
# shared precision ladder.
COARSE_CELL_RESOLUTION = 6


class SpatialCellError(ValueError):
    """Base for spatial-cell failures (fail-closed)."""


class CellValidationError(SpatialCellError):
    """Not a well-formed h3 cell string of the ``h3`` scheme."""


class CoordinateDomainError(SpatialCellError):
    """Latitude/longitude outside the WGS84 domain (or non-numeric)."""


class ResolutionError(SpatialCellError):
    """Resolution outside [0, 15] or an impossible parent/child move."""


def is_valid_cell(cell: object) -> bool:
    """True only for a well-formed h3 cell string of the ``h3`` scheme."""
    if not isinstance(cell, str) or not cell:
        return False
    try:
        return bool(h3.is_valid_cell(cell))
    except Exception:  # noqa: BLE001 - h3 raises typed errors; never leak them
        return False


def _require_valid(cell: object) -> None:
    if not is_valid_cell(cell):
        raise CellValidationError(f"invalid h3 cell string: {cell!r}")


def _require_resolution(resolution: object) -> int:
    try:
        value = int(resolution)
    except (TypeError, ValueError) as exc:
        raise ResolutionError(f"non-integer resolution: {resolution!r}") from exc
    if not (H3_MIN_RESOLUTION <= value <= H3_MAX_RESOLUTION):
        raise ResolutionError(
            f"resolution {value} outside h3 domain [{H3_MIN_RESOLUTION}, {H3_MAX_RESOLUTION}]"
        )
    return value


def _require_coordinate(latitude: object, longitude: object) -> tuple[float, float]:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError) as exc:
        raise CoordinateDomainError(
            f"non-numeric coordinate: lat={latitude!r} lon={longitude!r}"
        ) from exc
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise CoordinateDomainError(
            f"coordinate outside WGS84 domain: lat={lat} lon={lon}"
        )
    return lat, lon


def coordinate_to_cell(
    latitude: object,
    longitude: object,
    resolution: object = COARSE_CELL_RESOLUTION,
) -> str:
    """Client-side h3 cell string for a WGS84 coordinate at ``resolution``."""
    lat, lon = _require_coordinate(latitude, longitude)
    res = _require_resolution(resolution)
    try:
        return str(h3.latlng_to_cell(lat, lon, res))
    except Exception as exc:  # noqa: BLE001 - translate to a stable error type
        raise SpatialCellError(
            f"coordinate->cell failed for lat={lat} lon={lon} res={res}"
        ) from exc


def cell_to_center(cell: object) -> tuple[float, float]:
    """Centroid ``(latitude, longitude)`` in degrees of ``cell``."""
    _require_valid(cell)
    lat, lon = h3.cell_to_latlng(cell)
    return float(lat), float(lon)


def cell_resolution(cell: object) -> int:
    """h3 resolution of ``cell``."""
    _require_valid(cell)
    return int(h3.get_resolution(cell))


def parent_cell(cell: object, resolution: object) -> str:
    """Coarser ancestor of ``cell`` at ``resolution`` (must be strictly coarser)."""
    _require_valid(cell)
    res = _require_resolution(resolution)
    current = cell_resolution(cell)
    if res >= current:
        raise ResolutionError(
            f"parent resolution {res} is not coarser than cell resolution {current}"
        )
    try:
        return str(h3.cell_to_parent(cell, res))
    except Exception as exc:  # noqa: BLE001 - translate to a stable error type
        raise SpatialCellError(f"parent cell failed for {cell!r} at res {res}") from exc


def child_cells(cell: object, resolution: object) -> list[str]:
    """Finer descendants of ``cell`` at ``resolution`` (deterministic sorted).

    ``resolution`` must be strictly finer than the cell's own resolution;
    requesting a coarser or equal level is a :class:`ResolutionError`.
    """
    _require_valid(cell)
    res = _require_resolution(resolution)
    current = cell_resolution(cell)
    if res <= current:
        raise ResolutionError(
            f"child resolution {res} is not finer than cell resolution {current}"
        )
    try:
        cells = h3.cell_to_children(cell, res)
    except Exception as exc:  # noqa: BLE001 - translate to a stable error type
        raise SpatialCellError(f"child cells failed for {cell!r} at res {res}") from exc
    return sorted(str(child) for child in cells)


def k_ring(cell: object, k: object) -> list[str]:
    """``k``-ring neighbourhood (grid disk) of ``cell``, deterministic sorted.

    ``k == 0`` returns ``[cell]``; each step adds the hexagons one ring further
    out (for a non-pentagon origin, the disk holds ``1 + 3k(k + 1)`` cells).
    """
    _require_valid(cell)
    try:
        radius = int(k)
    except (TypeError, ValueError) as exc:
        raise ResolutionError(f"non-integer ring radius: {k!r}") from exc
    if radius < 0:
        raise ResolutionError(f"ring radius must be >= 0, got {radius}")
    try:
        cells = h3.grid_disk(cell, radius)
    except Exception as exc:  # noqa: BLE001 - translate to a stable error type
        raise SpatialCellError(f"k-ring failed for {cell!r} at radius {radius}") from exc
    return sorted(str(neighbor) for neighbor in cells)


def ring(cell: object, k: object) -> list[str]:
    """Exact ``k``-th ring of ``cell`` (cells at distance exactly ``k``)."""
    _require_valid(cell)
    try:
        radius = int(k)
    except (TypeError, ValueError) as exc:
        raise ResolutionError(f"non-integer ring radius: {k!r}") from exc
    if radius < 0:
        raise ResolutionError(f"ring radius must be >= 0, got {radius}")
    try:
        cells = h3.grid_ring(cell, radius)
    except Exception as exc:  # noqa: BLE001 - translate to a stable error type
        raise SpatialCellError(f"ring failed for {cell!r} at radius {radius}") from exc
    return sorted(str(neighbor) for neighbor in cells)


def contains_cell(outer: object, inner: object) -> bool:
    """True when ``inner`` is ``outer`` or a descendant of it in the h3 grid.

    Hierarchical containment check: two cells at the same resolution only match
    when identical; a finer cell is contained when climbing its ancestors reaches
    ``outer``. Invalid cells are never contained (fail closed).
    """
    if not is_valid_cell(outer) or not is_valid_cell(inner):
        return False
    if outer == inner:
        return True
    outer_res = cell_resolution(outer)
    inner_res = cell_resolution(inner)
    if inner_res <= outer_res:
        # Same-or-coarser resolution can never be strictly inside ``outer``.
        return False
    probe = str(inner)
    while cell_resolution(probe) > outer_res:
        probe = parent_cell(probe, cell_resolution(probe) - 1)
    return probe == outer


__all__ = [
    "CELL_SCHEME",
    "COARSE_CELL_RESOLUTION",
    "H3_MIN_RESOLUTION",
    "H3_MAX_RESOLUTION",
    "SpatialCellError",
    "CellValidationError",
    "CoordinateDomainError",
    "ResolutionError",
    "is_valid_cell",
    "coordinate_to_cell",
    "cell_to_center",
    "cell_resolution",
    "parent_cell",
    "child_cells",
    "k_ring",
    "ring",
    "contains_cell",
]
