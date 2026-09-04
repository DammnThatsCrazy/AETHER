"""Geographic360 intelligence-projection provider.

Sibling of ``services/population360`` / ``services/temporal360``: the
``geographic360`` context_360 projection (contextual WHERE) and its precision /
privacy posture. The provider is a pure read over canonical location facts
surfaced through the injected :class:`Geographic360Reader` seam. Since G4.5 the
default :class:`GeographicLocationReader` is store-backed over the canonical
``location_facts`` store (``services.geo.location_facts``), so a subject with
recorded facts projects them and one with none reads an honest ``missing``.
"""

from services.geographic360.provider import (
    Geographic360Provider,
    Geographic360Reader,
    GeographicLocationReader,
    GeographicPosture,
    GeographicView,
    LocationRow,
    OUTPUT_SECTIONS,
    RENDER_CAP_CITY,
    RENDER_CAP_METRO,
    RENDER_CAP_NONE,
    SUPPORTED_TEMPORAL_MODES,
    register_provider,
)

__all__ = [
    "Geographic360Provider",
    "Geographic360Reader",
    "GeographicLocationReader",
    "GeographicPosture",
    "GeographicView",
    "LocationRow",
    "OUTPUT_SECTIONS",
    "RENDER_CAP_CITY",
    "RENDER_CAP_METRO",
    "RENDER_CAP_NONE",
    "SUPPORTED_TEMPORAL_MODES",
    "register_provider",
]
