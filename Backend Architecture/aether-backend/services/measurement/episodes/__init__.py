"""Episode domain (WS-D item 2): canonical episodes + the episode360 surface.

``engine.EpisodeEngine`` groups observations/outcomes into durable
:class:`~shared.backend_interpretation.primitives.EpisodeRecord` spans;
``provider.register_provider`` exposes the ``episode360`` intelligence
projection over those records (registry row ``episode360`` is ``in_flight``;
this provider is the WS-D surface). Neither is a competing system of record —
episodes index canonical observations/outcomes and never replace them.
"""

from __future__ import annotations

from services.measurement.episodes.engine import EpisodeEngine

__all__ = ["EpisodeEngine"]
