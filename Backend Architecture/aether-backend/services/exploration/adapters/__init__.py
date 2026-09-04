"""Exploration surface-adapter registry.

Maps registered surface ids to their adapter. Surfaces without a backend on
this deployment (comparison_workbench, journeys, product_intelligence,
temporal_observatory — owned by other work packages) are intentionally absent;
``get_adapter`` returns ``None`` for them so the fabric answers an honest
not-available state instead of a fabricated one. temporal360 and population360
are present: the context-360 time leaf owns a dedicated ``temporal360`` surface
(Phase 2) rather than shadowing ``timeline`` / ``temporal_observatory``, and the
context-360 WHO/SET leaf owns a dedicated ``population360`` surface (Phase 3)
rather than shadowing ``comparison_workbench`` (deferred) or ``cluster360``
(already owned by ``ClusterSurfaceAdapter``).
"""

from __future__ import annotations

from typing import Optional

from services.exploration.adapters.base import (
    AdapterContext,
    AdapterResult,
    AdapterTruncation,
    SurfaceAdapter,
)
from services.exploration.adapters.campaign import CampaignSurfaceAdapter
from services.exploration.adapters.cluster import ClusterSurfaceAdapter
from services.exploration.adapters.geo import GeoSurfaceAdapter
from services.exploration.adapters.graph import GraphSurfaceAdapter
from services.exploration.adapters.profile import ProfileSurfaceAdapter
from services.exploration.adapters.projection import (
    Economic360SurfaceAdapter,
    Infrastructure360SurfaceAdapter,
    Outcome360SurfaceAdapter,
    Population360SurfaceAdapter,
    Temporal360SurfaceAdapter,
)
from services.exploration.adapters.timeline import TimelineSurfaceAdapter

_ADAPTER_TYPES: tuple[type[SurfaceAdapter], ...] = (
    GraphSurfaceAdapter,
    ProfileSurfaceAdapter,
    ClusterSurfaceAdapter,
    TimelineSurfaceAdapter,
    GeoSurfaceAdapter,
    CampaignSurfaceAdapter,
    Outcome360SurfaceAdapter,
    Economic360SurfaceAdapter,
    Infrastructure360SurfaceAdapter,
    Temporal360SurfaceAdapter,
    Population360SurfaceAdapter,
)

_REGISTRY: dict[str, SurfaceAdapter] = {a.surface_id: a() for a in _ADAPTER_TYPES}


def get_adapter(surface: str) -> Optional[SurfaceAdapter]:
    return _REGISTRY.get(surface)


def available_surfaces() -> frozenset[str]:
    return frozenset(_REGISTRY)


__all__ = [
    "AdapterContext",
    "AdapterResult",
    "AdapterTruncation",
    "SurfaceAdapter",
    "get_adapter",
    "available_surfaces",
]
