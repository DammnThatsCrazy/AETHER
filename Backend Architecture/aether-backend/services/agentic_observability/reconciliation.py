"""Agentic observability pipeline diagnostics and reconciliation.

Read-only utilities used by Kyber to inspect the canonical PR-2 pipeline from
Bronze through Silver, canonical activity, and projection outbox. These helpers
observe and explain pipeline state; they do not execute provider actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from repositories.agentic_observability_repos import (
    AgenticProjectionOutboxRepository,
    SilverAgentActivityFactRepository,
    SilverAgentRiskFactRepository,
    SilverAgentToolInvocationFactRepository,
    SilverMCPConnectionFactRepository,
)
from repositories.lake import BronzeRepository
from services.measurement.repositories.activity_repo import ActivityRepository

SILVER_FACT_REPOSITORIES: tuple[tuple[str, Any], ...] = (
    ("silver_agent_activity_facts", SilverAgentActivityFactRepository),
    ("silver_agent_tool_invocation_facts", SilverAgentToolInvocationFactRepository),
    ("silver_mcp_connection_facts", SilverMCPConnectionFactRepository),
    ("silver_agent_risk_facts", SilverAgentRiskFactRepository),
)
OUTBOX_STATUSES = ("queued", "failed", "completed", "dead_lettered")


@dataclass(frozen=True)
class AgenticLineageResult:
    tenant_id: str
    source_event_id: str
    bronze_records: list[dict[str, Any]] = field(default_factory=list)
    silver_records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    canonical_activity: list[dict[str, Any]] = field(default_factory=list)
    outbox_records: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.gaps

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "source_event_id": self.source_event_id,
            "complete": self.complete,
            "counts": {
                "bronze": len(self.bronze_records),
                "silver": sum(len(rows) for rows in self.silver_records.values()),
                "canonical_activity": len(self.canonical_activity),
                "outbox": len(self.outbox_records),
            },
            "gaps": self.gaps,
            "bronze_records": self.bronze_records,
            "silver_records": self.silver_records,
            "canonical_activity": self.canonical_activity,
            "outbox_records": self.outbox_records,
        }


class AgenticReconciliationService:
    """Tenant-scoped agentic pipeline diagnostics."""

    def __init__(self) -> None:
        self.bronze = BronzeRepository("agentic_observations")
        self.activity = ActivityRepository()
        self.outbox = AgenticProjectionOutboxRepository()

    async def pipeline_health(self, *, tenant_id: str) -> dict[str, Any]:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        silver_counts: dict[str, int] = {}
        for table, repo_cls in SILVER_FACT_REPOSITORIES:
            silver_counts[table] = await repo_cls().count({"tenant_id": tenant_id})
        outbox_counts = {
            status: await self.outbox.count({"tenant_id": tenant_id, "status": status})
            for status in OUTBOX_STATUSES
        }
        return {
            "tenant_id": tenant_id,
            "bronze_agentic_observations": await self.bronze.count({"tenant_id": tenant_id}),
            "silver_facts": silver_counts,
            "canonical_activity": await self.activity.count_by_source(
                tenant_id=tenant_id,
                source_system="agentic_observability",
            ),
            "outbox": outbox_counts,
            "pipeline_lag": {
                "graph_backlog": outbox_counts["queued"] + outbox_counts["failed"],
                "dead_lettered": outbox_counts["dead_lettered"],
            },
        }

    async def lineage(self, *, tenant_id: str, source_event_id: str) -> AgenticLineageResult:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not source_event_id:
            raise ValueError("source_event_id is required")
        bronze_records = await self.bronze.find_many(
            {"tenant_id": tenant_id, "provider_record_id": source_event_id},
            limit=100,
        )
        silver_records: dict[str, list[dict[str, Any]]] = {}
        for table, repo_cls in SILVER_FACT_REPOSITORIES:
            rows = await repo_cls().find_many(
                {"tenant_id": tenant_id, "source_event_id": source_event_id},
                limit=100,
            )
            if rows:
                silver_records[table] = rows
        canonical_activity = await self.activity.find_by_source_event(
            tenant_id=tenant_id,
            source_event_id=source_event_id,
        )
        outbox_records = await self.outbox.find_many(
            {"tenant_id": tenant_id, "source_event_id": source_event_id},
            limit=100,
        )
        gaps: list[str] = []
        if not bronze_records:
            gaps.append("bronze_missing")
        if not silver_records:
            gaps.append("silver_missing")
        if not canonical_activity:
            gaps.append("canonical_activity_missing")
        if not outbox_records:
            gaps.append("graph_outbox_missing")
        return AgenticLineageResult(
            tenant_id=tenant_id,
            source_event_id=source_event_id,
            bronze_records=bronze_records,
            silver_records=silver_records,
            canonical_activity=canonical_activity,
            outbox_records=outbox_records,
            gaps=gaps,
        )

    async def reconcile(self, *, tenant_id: str, limit: int = 100) -> dict[str, Any]:
        """Detect missing pipeline stages for recent Bronze records.

        This read-only pass reports gaps for operator action. Replay/repair is a
        separate explicit workflow and is intentionally not performed here.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")
        bronze_records = await self.bronze.find_many({"tenant_id": tenant_id}, limit=limit)
        checked = 0
        gap_counts: dict[str, int] = {}
        events: list[dict[str, Any]] = []
        for bronze in bronze_records:
            source_event_id = bronze.get("provider_record_id") or bronze.get("payload", {}).get("observation_id")
            if not source_event_id:
                continue
            checked += 1
            lineage = await self.lineage(tenant_id=tenant_id, source_event_id=source_event_id)
            if lineage.gaps:
                for gap in lineage.gaps:
                    gap_counts[gap] = gap_counts.get(gap, 0) + 1
                events.append({
                    "source_event_id": source_event_id,
                    "gaps": lineage.gaps,
                    "counts": lineage.as_dict()["counts"],
                })
        return {
            "tenant_id": tenant_id,
            "checked": checked,
            "gap_counts": gap_counts,
            "events_with_gaps": events,
            "status": "ok" if not events else "gaps_detected",
        }
