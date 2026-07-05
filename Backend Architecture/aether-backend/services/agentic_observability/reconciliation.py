"""
Agentic Reconciliation Service — pipeline health, lineage, and gap detection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from repositories.agentic_observability_repos import (
    AgenticBronzeObservationRepository,
    AgenticProjectionOutboxRepository,
    SilverAgentActivityFactRepository,
    SilverAgentRiskFactRepository,
    SilverAgentToolInvocationFactRepository,
    SilverMCPConnectionFactRepository,
)
from services.measurement.repositories.activity_repo import ActivityRepository
from shared.logger.logger import get_logger

logger = get_logger("aether.agentic_observability.reconciliation")

SILVER_FACT_REPOSITORIES = (
    SilverAgentActivityFactRepository,
    SilverAgentToolInvocationFactRepository,
    SilverMCPConnectionFactRepository,
    SilverAgentRiskFactRepository,
)

OUTBOX_STATUSES = ("queued", "processing", "persisted", "failed", "dead_lettered")


@dataclass(frozen=True)
class AgenticLineageResult:
    source_event_id: str
    bronze_records: list[dict[str, Any]] = field(default_factory=list)
    silver_records: list[dict[str, Any]] = field(default_factory=list)
    canonical_activities: list[dict[str, Any]] = field(default_factory=list)
    outbox_rows: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.bronze_records) and bool(self.canonical_activities) and not self.gaps

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_event_id": self.source_event_id,
            "complete": self.complete,
            "bronze_count": len(self.bronze_records),
            "silver_count": len(self.silver_records),
            "canonical_activity_count": len(self.canonical_activities),
            "outbox_count": len(self.outbox_rows),
            "gaps": list(self.gaps),
        }


class AgenticReconciliationService:
    def __init__(self) -> None:
        self._bronze = AgenticBronzeObservationRepository()
        self._outbox = AgenticProjectionOutboxRepository()
        self._activity = ActivityRepository()
        self._silver_repos = [cls() for cls in SILVER_FACT_REPOSITORIES]

    async def pipeline_health(self, tenant_id: str) -> dict[str, Any]:
        bronze_count = await self._bronze.count(filters={"tenant_id": tenant_id})
        outbox_counts: dict[str, int] = {}
        for status in OUTBOX_STATUSES:
            outbox_counts[status] = await self._outbox.count(
                filters={"tenant_id": tenant_id, "status": status}
            )
        silver_counts: dict[str, int] = {}
        for repo in self._silver_repos:
            silver_counts[repo.table_name] = await repo.count(filters={"tenant_id": tenant_id})
        agentic_count = await self._activity.count_by_source(tenant_id, "agentic_observability")
        dead_lettered = outbox_counts.get("dead_lettered", 0)
        failed = outbox_counts.get("failed", 0)
        return {
            "tenant_id": tenant_id,
            "bronze_observations": bronze_count,
            "silver_facts": silver_counts,
            "canonical_activities": agentic_count,
            "outbox": outbox_counts,
            "health": "degraded" if (dead_lettered > 0 or failed > 10) else "healthy",
            "observation_only": True,
        }

    async def lineage(self, tenant_id: str, source_event_id: str) -> AgenticLineageResult:
        bronze_rows = await self._bronze.find_many(
            filters={"tenant_id": tenant_id, "observation_id": source_event_id}, limit=10
        )
        silver_rows: list[dict[str, Any]] = []
        for repo in self._silver_repos:
            rows = await repo.find_many(
                filters={"tenant_id": tenant_id, "observation_id": source_event_id}, limit=10
            )
            silver_rows.extend(rows)
        canonical_rows = await self._activity.find_by_source_event(tenant_id, source_event_id)
        outbox_rows = await self._outbox.find_many(
            filters={"tenant_id": tenant_id, "observation_id": source_event_id}, limit=20
        )
        gaps: list[str] = []
        if not bronze_rows:
            gaps.append("missing_bronze")
        if not silver_rows:
            gaps.append("missing_silver")
        if not canonical_rows:
            gaps.append("missing_canonical_activity")
        return AgenticLineageResult(
            source_event_id=source_event_id,
            bronze_records=list(bronze_rows),
            silver_records=silver_rows,
            canonical_activities=canonical_rows,
            outbox_rows=list(outbox_rows),
            gaps=gaps,
        )

    async def reconcile(self, tenant_id: str, limit: int = 100) -> dict[str, Any]:
        bronze_rows = await self._bronze.find_many(
            filters={"tenant_id": tenant_id}, limit=limit
        )
        gaps: list[str] = []
        for row in bronze_rows:
            obs_id = row.get("observation_id", "")
            canonical = await self._activity.find_by_source_event(tenant_id, obs_id)
            if not canonical:
                gaps.append(obs_id)
        return {
            "tenant_id": tenant_id,
            "checked": len(bronze_rows),
            "gap_count": len(gaps),
            "gaps": gaps[:20],
            "observation_only": True,
        }
