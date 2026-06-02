"""Reliability services: health registries, SLOs, incidents, and tenant impact.

All logic is additive and reads from existing repositories. Tenant-facing
projections are deliberately stripped of infrastructure internals.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from shared.logger.logger import get_logger

from services.reliability.definitions import (
    LOWER_IS_BETTER_SUFFIXES,
    PIPELINE_DEFINITIONS,
    QUEUE_DEFINITIONS,
    RUNBOOK_DEFINITIONS,
    SERVICE_DEFINITIONS,
    SLO_DEFINITIONS,
)
from services.reliability.models import (
    IncidentRecord,
    OperationalRunbook,
    PipelineHealthRecord,
    QueueHealthRecord,
    ServiceHealthRecord,
    ServiceLevelObjective,
    TenantStatusSummary,
    now_iso,
)
from services.reliability.repositories import (
    IncidentAuditRepository,
    IncidentRepository,
    PipelineHealthRepository,
    PostmortemRepository,
    QueueHealthRepository,
    RunbookRepository,
    SLORepository,
    ServiceHealthRepository,
)

logger = get_logger("aether.service.reliability")

# Module-level repository singletons (shared in-memory store across instances).
_services = ServiceHealthRepository()
_pipelines = PipelineHealthRepository()
_queues = QueueHealthRepository()
_incidents = IncidentRepository()
_incident_audit = IncidentAuditRepository()
_runbooks = RunbookRepository()
_slos = SLORepository()
_postmortems = PostmortemRepository()


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds_since(value: Any) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 — Service Health Registry
# ═══════════════════════════════════════════════════════════════════════════

class ServiceHealthRegistry:
    """Tracks per-service health, heartbeats, status, and incident linkage."""

    def __init__(self) -> None:
        self.repo = _services

    async def seed(self) -> None:
        for definition in SERVICE_DEFINITIONS:
            existing = await self.repo.find_by_id(definition["service_key"])
            if existing is None:
                record = ServiceHealthRecord(**definition)
                await self.repo.insert(definition["service_key"], record.model_dump())

    async def list(self) -> list[dict[str, Any]]:
        await self.seed()
        rows = await self.repo.find_many(limit=1000)
        return sorted(rows, key=lambda r: r.get("service_key", ""))

    async def get(self, service_key: str) -> dict[str, Any] | None:
        await self.seed()
        return await self.repo.find_by_id(service_key)

    async def _update(self, service_key: str, patch: dict[str, Any]) -> dict[str, Any]:
        await self.seed()
        existing = await self.repo.find_by_id(service_key)
        if existing is None:
            existing = ServiceHealthRecord(service_key=service_key, label=service_key).model_dump()
            await self.repo.insert(service_key, existing)
        patch["updated_at"] = now_iso()
        return await self.repo.update(service_key, patch)

    async def heartbeat(self, service_key: str, *, latency_ms: float | None = None, error_rate: float | None = None) -> dict[str, Any]:
        patch: dict[str, Any] = {"last_heartbeat_at": now_iso()}
        if latency_ms is not None:
            patch["latency_ms"] = latency_ms
        if error_rate is not None:
            patch["error_rate"] = error_rate
        return await self._update(service_key, patch)

    async def set_status(self, service_key: str, status: str) -> dict[str, Any]:
        return await self._update(service_key, {"status": status})

    async def set_metadata(self, service_key: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return await self._update(service_key, {"metadata": metadata})

    async def record_successful_job(self, service_key: str) -> dict[str, Any]:
        return await self._update(service_key, {"last_successful_job_at": now_iso()})

    async def link_incident(self, service_key: str, incident_id: str) -> dict[str, Any]:
        existing = await self.get(service_key) or ServiceHealthRecord(service_key=service_key, label=service_key).model_dump()
        ids = list(existing.get("open_incident_ids") or [])
        if incident_id not in ids:
            ids.append(incident_id)
        return await self._update(service_key, {"open_incident_ids": ids})

    async def unlink_incident(self, service_key: str, incident_id: str) -> dict[str, Any]:
        existing = await self.get(service_key)
        if existing is None:
            return await self._update(service_key, {})
        ids = [i for i in (existing.get("open_incident_ids") or []) if i != incident_id]
        return await self._update(service_key, {"open_incident_ids": ids})


service_registry = ServiceHealthRegistry()


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3 — Pipeline Health
# ═══════════════════════════════════════════════════════════════════════════

class PipelineHealthService:
    def __init__(self) -> None:
        self.repo = _pipelines

    async def seed(self) -> None:
        for definition in PIPELINE_DEFINITIONS:
            existing = await self.repo.find_by_id(definition["pipeline_key"])
            if existing is None:
                record = PipelineHealthRecord(**definition)
                await self.repo.insert(definition["pipeline_key"], record.model_dump())

    async def list(self) -> list[dict[str, Any]]:
        await self.seed()
        rows = await self.repo.find_many(limit=1000)
        for row in rows:
            if row.get("freshness_seconds") is None and row.get("last_successful_run_at"):
                row["freshness_seconds"] = _seconds_since(row.get("last_successful_run_at"))
        return sorted(rows, key=lambda r: r.get("pipeline_key", ""))

    async def report(self, pipeline_key: str, metrics: dict[str, Any]) -> dict[str, Any]:
        await self.seed()
        existing = await self.repo.find_by_id(pipeline_key)
        if existing is None:
            raise KeyError(pipeline_key)
        metrics["updated_at"] = now_iso()
        return await self.repo.update(pipeline_key, metrics)


pipeline_service = PipelineHealthService()


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4 — Queue + Worker Health
# ═══════════════════════════════════════════════════════════════════════════

class QueueHealthService:
    """Queue/worker health. No real queue abstraction exists yet, so records are
    seeded locally and updated via ``report`` (adapter interface)."""

    def __init__(self) -> None:
        self.repo = _queues

    async def seed(self) -> None:
        for definition in QUEUE_DEFINITIONS:
            existing = await self.repo.find_by_id(definition["queue_key"])
            if existing is None:
                record = QueueHealthRecord(**definition)
                await self.repo.insert(definition["queue_key"], record.model_dump())

    async def list(self) -> list[dict[str, Any]]:
        await self.seed()
        rows = await self.repo.find_many(limit=1000)
        return sorted(rows, key=lambda r: r.get("queue_key", ""))

    async def report(self, queue_key: str, metrics: dict[str, Any]) -> dict[str, Any]:
        await self.seed()
        existing = await self.repo.find_by_id(queue_key)
        if existing is None:
            raise KeyError(queue_key)
        metrics["updated_at"] = now_iso()
        return await self.repo.update(queue_key, metrics)


queue_service = QueueHealthService()


# ═══════════════════════════════════════════════════════════════════════════
# Phase 6 — Runbooks
# ═══════════════════════════════════════════════════════════════════════════

class RunbookService:
    def __init__(self) -> None:
        self.repo = _runbooks

    async def seed(self) -> None:
        for definition in RUNBOOK_DEFINITIONS:
            existing = await self.repo.find_by_id(definition.runbook_id)
            if existing is None:
                await self.repo.insert(definition.runbook_id, definition.model_dump())

    async def list(self) -> list[dict[str, Any]]:
        await self.seed()
        rows = await self.repo.find_many(limit=1000)
        return sorted(rows, key=lambda r: r.get("title", ""))

    async def get(self, runbook_id: str) -> dict[str, Any] | None:
        await self.seed()
        return await self.repo.find_by_id(runbook_id)

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        await self.seed()
        runbook_id = data.get("runbook_id") or f"rb_{uuid.uuid4().hex[:12]}"
        runbook = OperationalRunbook(runbook_id=runbook_id, **{k: v for k, v in data.items() if k != "runbook_id"})
        return await self.repo.insert(runbook_id, runbook.model_dump())

    async def update(self, runbook_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        await self.seed()
        existing = await self.repo.find_by_id_or_fail(runbook_id)
        existing.update({k: v for k, v in patch.items() if v is not None})
        existing["updated_at"] = now_iso()
        return await self.repo.update(runbook_id, existing)


runbook_service = RunbookService()


# ═══════════════════════════════════════════════════════════════════════════
# Phase 7 — SLO tracking
# ═══════════════════════════════════════════════════════════════════════════

def _is_lower_better(metric_key: str) -> bool:
    return any(metric_key.endswith(suffix) for suffix in LOWER_IS_BETTER_SUFFIXES)


def compute_slo_status(target: float, current: float | None, metric_key: str) -> tuple[str, float | None]:
    """Return (status, error_budget_remaining 0..1) for an SLO.

    Internal objective only — not an external SLA commitment.
    """
    if current is None:
        return "unknown", None
    lower_better = _is_lower_better(metric_key)
    if lower_better:
        # target is a ceiling; budget = headroom below the ceiling
        if target <= 0:
            return ("meeting" if current <= target else "breached"), None
        budget = (target - current) / target
    else:
        # target is a floor (e.g. availability ratio); budget vs perfect (1.0)
        denom = 1.0 - target
        budget = (current - target) / denom if denom > 0 else (1.0 if current >= target else -1.0)
    budget = max(-1.0, min(1.0, budget))
    if budget < 0:
        status = "breached"
    elif budget < 0.2:
        status = "at_risk"
    else:
        status = "meeting"
    return status, round(max(0.0, budget), 4)


class SLOService:
    def __init__(self) -> None:
        self.repo = _slos

    async def seed(self) -> None:
        for definition in SLO_DEFINITIONS:
            existing = await self.repo.find_by_id(definition.slo_id)
            if existing is None:
                await self.repo.insert(definition.slo_id, definition.model_dump())

    async def list(self) -> list[dict[str, Any]]:
        await self.seed()
        rows = await self.repo.find_many(limit=1000)
        for row in rows:
            status, budget = compute_slo_status(row.get("target", 0.0), row.get("current_value"), row.get("metric_key", ""))
            row["status"] = status
            row["error_budget_remaining"] = budget
        return sorted(rows, key=lambda r: r.get("slo_id", ""))

    async def set_current_value(self, slo_id: str, current_value: float) -> dict[str, Any]:
        await self.seed()
        existing = await self.repo.find_by_id_or_fail(slo_id)
        status, budget = compute_slo_status(existing.get("target", 0.0), current_value, existing.get("metric_key", ""))
        existing.update({"current_value": current_value, "status": status, "error_budget_remaining": budget, "updated_at": now_iso()})
        return await self.repo.update(slo_id, existing)


slo_service = SLOService()


# ═══════════════════════════════════════════════════════════════════════════
# Phase 5 — Incident management
# ═══════════════════════════════════════════════════════════════════════════

class IncidentService:
    def __init__(self) -> None:
        self.repo = _incidents
        self.audit = _incident_audit

    async def _record_audit(self, incident_id: str, action: str, actor: str | None, detail: dict[str, Any]) -> None:
        """Best-effort internal audit trail for incident changes."""
        entry_id = f"ia_{uuid.uuid4().hex[:16]}"
        try:
            await self.audit.insert(entry_id, {
                "audit_id": entry_id,
                "incident_id": incident_id,
                "action": action,
                "actor": actor or "system",
                "detail": detail,
                "recorded_at": now_iso(),
            })
        except Exception as exc:  # pragma: no cover - audit must never break flow
            logger.warning(f"incident audit write failed: {exc}")
        logger.info(f"incident_audit incident={incident_id} action={action} actor={actor or 'system'}")

    async def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        rows = await self.repo.find_many(limit=1000, sort_by="created_at", sort_order="desc")
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    async def get(self, incident_id: str) -> dict[str, Any] | None:
        return await self.repo.find_by_id(incident_id)

    async def audit_trail(self, incident_id: str) -> list[dict[str, Any]]:
        rows = await self.audit.find_many(filters={"incident_id": incident_id}, limit=1000, sort_by="created_at", sort_order="asc")
        return rows

    async def create(self, data: dict[str, Any], actor: str | None = None) -> dict[str, Any]:
        incident_id = data.get("incident_id") or f"inc_{uuid.uuid4().hex[:12]}"
        incident = IncidentRecord(incident_id=incident_id, **{k: v for k, v in data.items() if k != "incident_id"})
        stored = await self.repo.insert(incident_id, incident.model_dump())
        for service_key in incident.affected_services:
            await service_registry.link_incident(service_key, incident_id)
        await self._record_audit(incident_id, "created", actor, {"severity": incident.severity, "status": incident.status})
        return stored

    async def update(self, incident_id: str, patch: dict[str, Any], actor: str | None = None) -> dict[str, Any]:
        existing = await self.repo.find_by_id_or_fail(incident_id)
        clean = {k: v for k, v in patch.items() if v is not None}

        new_status = clean.get("status")
        if new_status == "resolved" and not clean.get("resolved_at") and not existing.get("resolved_at"):
            clean["resolved_at"] = now_iso()

        # Maintain service incident linkage when affected_services changes.
        if "affected_services" in clean:
            old = set(existing.get("affected_services") or [])
            new = set(clean["affected_services"])
            for svc in new - old:
                await service_registry.link_incident(svc, incident_id)
            for svc in old - new:
                await service_registry.unlink_incident(svc, incident_id)

        existing.update(clean)
        existing["updated_at"] = now_iso()
        stored = await self.repo.update(incident_id, existing)

        # On terminal states, detach incident from services.
        if new_status in ("resolved", "closed"):
            for svc in existing.get("affected_services") or []:
                await service_registry.unlink_incident(svc, incident_id)

        await self._record_audit(incident_id, "updated", actor, clean)
        return stored

    async def assign_owner(self, incident_id: str, owner_id: str, actor: str | None = None) -> dict[str, Any]:
        return await self.update(incident_id, {"owner_id": owner_id}, actor)

    async def link_runbook(self, incident_id: str, runbook_id: str, actor: str | None = None) -> dict[str, Any]:
        return await self.update(incident_id, {"runbook_id": runbook_id}, actor)

    async def add_mitigation_step(self, incident_id: str, step: str, actor: str | None = None) -> dict[str, Any]:
        existing = await self.repo.find_by_id_or_fail(incident_id)
        steps = list(existing.get("mitigation_steps") or [])
        steps.append(step)
        return await self.update(incident_id, {"mitigation_steps": steps}, actor)

    async def resolve(self, incident_id: str, actor: str | None = None) -> dict[str, Any]:
        return await self.update(incident_id, {"status": "resolved", "resolved_at": now_iso()}, actor)

    async def mark_postmortem_pending(self, incident_id: str, actor: str | None = None) -> dict[str, Any]:
        return await self.update(incident_id, {"status": "postmortem_pending"}, actor)

    async def close(self, incident_id: str, actor: str | None = None) -> dict[str, Any]:
        return await self.update(incident_id, {"status": "closed"}, actor)


incident_service = IncidentService()


# ═══════════════════════════════════════════════════════════════════════════
# Postmortems (Phase 13 process, surfaced via Phase 10 routes)
# ═══════════════════════════════════════════════════════════════════════════

class PostmortemService:
    def __init__(self) -> None:
        self.repo = _postmortems

    async def list(self) -> list[dict[str, Any]]:
        return await self.repo.find_many(limit=1000, sort_by="created_at", sort_order="desc")

    async def get(self, postmortem_id: str) -> dict[str, Any] | None:
        return await self.repo.find_by_id(postmortem_id)

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        from services.reliability.models import IncidentPostmortem
        postmortem_id = data.get("postmortem_id") or f"pm_{uuid.uuid4().hex[:12]}"
        pm = IncidentPostmortem(postmortem_id=postmortem_id, **{k: v for k, v in data.items() if k != "postmortem_id"})
        return await self.repo.insert(postmortem_id, pm.model_dump())

    async def update(self, postmortem_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = await self.repo.find_by_id_or_fail(postmortem_id)
        existing.update({k: v for k, v in patch.items() if v is not None})
        existing["updated_at"] = now_iso()
        return await self.repo.update(postmortem_id, existing)


postmortem_service = PostmortemService()
