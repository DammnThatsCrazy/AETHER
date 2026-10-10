"""Shared geo model surface (geographic360 Phase 4).

The authoritative vocabulary lives in
``packages/shared/contracts/location-registry.json``; its generated twins are
``shared/geo/generated_taxonomy.py`` (Python) and ``packages/shared/location-registry.ts``
(TypeScript). The hand-authored model surface — :class:`LocationFact` with
role/precision/coordinates/provenance and the ``Place``/``Region``/``Jurisdiction``
resolution hierarchy — is exposed here.
"""

from shared.geo.models import Coordinate, Jurisdiction, LocationFact, Place, Region

__all__ = [
    "Coordinate",
    "Jurisdiction",
    "LocationFact",
    "Place",
    "Region",
]
