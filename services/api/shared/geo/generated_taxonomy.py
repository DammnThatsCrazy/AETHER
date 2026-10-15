# DO NOT EDIT — generated from packages/shared/contracts/location-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated location taxonomy (roles, region types, precision, cells)."""

from __future__ import annotations

LOCATION_REGISTRY_CONTRACT_VERSION = "1.0.0"

# Role a location fact plays for its subject.
LOCATION_ROLES: tuple[str, ...] = (
    "network_egress",
    "observed_presence",
    "likely_residence",
    "primary_residence",
    "declared_address",
    "shipping_address",
    "billing_address",
    "workplace",
    "commercial_destination",
    "organization_registered",
    "agent_execution_region",
    "venue_association",
    "trip_destination",
)

# Region-type hierarchy (not US-only), continent down to locality.
REGION_TYPES: tuple[str, ...] = (
    "continent",
    "country",
    "admin_region",
    "admin_subregion",
    "metro_area",
    "city",
    "district",
    "locality",
)

# Coarsest-to-finest precision ladder (aligned to context-capsule).
LOCATION_PRECISION_CLASSES: tuple[str, ...] = (
    "country",
    "region",
    "city",
    "coarse_cell",
    "precise",
)

# Coordinate reference systems a LocationFact may carry.
COORDINATE_SYSTEMS: tuple[str, ...] = ("wgs84",)

# Spatial cell schemes (client-computed strings; never a spatial index).
CELL_SCHEMES: tuple[str, ...] = ("h3",)

__all__ = [
    "LOCATION_REGISTRY_CONTRACT_VERSION",
    "LOCATION_ROLES",
    "REGION_TYPES",
    "LOCATION_PRECISION_CLASSES",
    "COORDINATE_SYSTEMS",
    "CELL_SCHEMES",
]
