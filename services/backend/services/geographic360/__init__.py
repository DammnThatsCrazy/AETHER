"""Geographic360 intelligence-projection provider.

Sibling of ``services/population360`` / ``services/temporal360``: the
``geographic360`` context_360 projection (contextual WHERE) and its precision /
privacy posture. The provider is a pure read over canonical location facts
surfaced through the injected :class:`Geographic360Reader` seam. Since G4.5 the
default :class:`GeographicLocationReader` is store-backed over the canonical
``location_facts`` store (``services.geo.location_facts``), so a subject with
recorded facts projects them and one with none reads an honest ``missing``.

G4.5 also formalizes the registry row's pending ``context_capsule_semantics``
spine authority as :mod:`services.geographic360.capsule_semantics`: the pure
rule set that turns a privacy-shaped capsule :class:`LocationObservation` into a
canonical geographic reading (role resolution, precision derived from carried
labels and capped at ``coarse_cell`` — never ``precise``, no coordinate, no
invented jurisdiction). It is consumed through the provider's reader seam, and
its names are re-exported here as the formalized surface.
"""

from services.geographic360.capsule_semantics import (
    CAPSULE_LOCATION_PROVIDER,
    DEFAULT_ROLE,
    MAX_CAPSULE_PRECISION,
    SEMANTIC_ROLE,
    SOURCE_ROLE,
    capsule_location_fact,
    capsule_precision_class,
    capsule_role,
    normalise_capsule_fact_row,
)
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
    "CAPSULE_LOCATION_PROVIDER",
    "DEFAULT_ROLE",
    "Geographic360Provider",
    "Geographic360Reader",
    "GeographicLocationReader",
    "GeographicPosture",
    "GeographicView",
    "LocationRow",
    "MAX_CAPSULE_PRECISION",
    "OUTPUT_SECTIONS",
    "RENDER_CAP_CITY",
    "RENDER_CAP_METRO",
    "RENDER_CAP_NONE",
    "SEMANTIC_ROLE",
    "SOURCE_ROLE",
    "SUPPORTED_TEMPORAL_MODES",
    "capsule_location_fact",
    "capsule_precision_class",
    "capsule_role",
    "normalise_capsule_fact_row",
    "register_provider",
]
