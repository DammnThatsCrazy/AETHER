"""Repositories for data-quality / intelligence-quality records.

All repositories use the shared ``BaseRepository`` (in-memory locally, asyncpg
in staging/production). Records are keyed by their domain id and also carry that
id under the domain field (e.g. ``drift_event_id``) for round-tripping.
"""
from __future__ import annotations

from repositories.repos import BaseRepository


class IntelligenceQualityRepository(BaseRepository):
    """Latest computed intelligence-quality score snapshot, keyed by scope.

    Key is ``{scope}:{tenant_id or '*'}`` so per-tenant and platform snapshots
    never collide.
    """

    def __init__(self) -> None:
        super().__init__("data_quality_scores")


class DriftEventRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("data_quality_drift_events")
