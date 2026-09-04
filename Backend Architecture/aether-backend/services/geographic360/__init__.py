"""Geographic360 intelligence-projection provider.

Sibling of ``services/population360`` / ``services/temporal360``: the
``geographic360`` context_360 projection (contextual WHERE) and its precision /
privacy posture. The provider is a pure read over location facts surfaced
through the injected :class:`Geographic360Reader` seam; the location write path
that feeds those reads lands with the context-capsule authority in G4.5, so the
default reader answers an honest missing until then.
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
