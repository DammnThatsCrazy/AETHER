"""Repositories for reliability records.

All repositories use the shared ``BaseRepository`` (in-memory locally, asyncpg
in staging/production). Records are keyed by their domain id and also carry that
id under the domain field (e.g. ``incident_id``) for round-tripping.
"""
from __future__ import annotations

from repositories.repos import BaseRepository


class ServiceHealthRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("reliability_service_health")


class PipelineHealthRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("reliability_pipeline_health")


class QueueHealthRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("reliability_queue_health")


class IncidentRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("reliability_incidents")


class IncidentAuditRepository(BaseRepository):
    """Internal-only audit trail for incident lifecycle changes."""

    def __init__(self) -> None:
        super().__init__("reliability_incident_audit")


class RunbookRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("reliability_runbooks")


class SLORepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("reliability_slos")


class PostmortemRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("reliability_postmortems")
