"""Pure-python WGS84 geodesy via geographiclib (geographic360 G4.3).

Distances between coordinates (and between H3 cell centroids) are computed with
``geographiclib`` — a pure-python, no-C-extension WGS84 ellipsoid — so geodesic
answers never depend on PostGIS or a spatial database. Heavier ``pyproj`` /
``shapely`` are deliberately not introduced; they only become necessary if
jurisdiction-boundary point-in-polygon is later required (not this slice).

All helpers fail closed: out-of-domain coordinates raise
:class:`~services.geo.spatial_cells.CoordinateDomainError`, never a fabricated
or nonsensical distance.
"""

from __future__ import annotations

from geographiclib.geodesic import Geodesic

from services.geo.spatial_cells import (
    CoordinateDomainError,
    SpatialCellError,
    cell_to_center,
    is_valid_cell,
)

_WGS84 = Geodesic.WGS84


def geodesic_distance_m(
    latitude_a: object,
    longitude_a: object,
    latitude_b: object,
    longitude_b: object,
) -> float:
    """Shortest WGS84 geodesic distance in metres between two coordinates."""
    lat_a, lon_a = _require_coordinate(latitude_a, longitude_a)
    lat_b, lon_b = _require_coordinate(latitude_b, longitude_b)
    return float(_WGS84.Inverse(lat_a, lon_a, lat_b, lon_b)["s12"])


def cell_centroid_distance_m(cell_a: object, cell_b: object) -> float:
    """Geodesic distance in metres between two H3 cell centroids."""
    if not is_valid_cell(cell_a) or not is_valid_cell(cell_b):
        raise SpatialCellError(f"invalid cell in distance: {cell_a!r}, {cell_b!r}")
    lat_a, lon_a = cell_to_center(cell_a)
    lat_b, lon_b = cell_to_center(cell_b)
    return geodesic_distance_m(lat_a, lon_a, lat_b, lon_b)


def _require_coordinate(latitude: object, longitude: object) -> tuple[float, float]:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError) as exc:
        raise CoordinateDomainError(
            f"non-numeric coordinate: lat={latitude!r} lon={longitude!r}"
        ) from exc
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise CoordinateDomainError(f"coordinate outside WGS84 domain: lat={lat} lon={lon}")
    return lat, lon


__all__ = [
    "geodesic_distance_m",
    "cell_centroid_distance_m",
]
