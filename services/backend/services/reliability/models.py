"""Pydantic contracts for reliability, SRE, and incident response.

These mirror the shared TypeScript contracts in
``frontend/shared/src/types/reliability.ts``. Field names are kept identical
across both layers so payloads round-trip cleanly between backend and frontend.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# Enums (string literals so they serialize transparently)
# ─────────────────────────────────────────────────────────────────────────────

ServiceHealthStatus = Literal["healthy", "degraded", "critical", "offline", "unknown"]
IncidentSeverity = Literal["sev1", "sev2", "sev3", "sev4"]
IncidentStatus = Literal[
    "open", "investigating", "mitigating", "resolved", "postmortem_pending", "closed"
]
SLOWindow = Literal["1h", "24h", "7d", "30d", "90d"]
SLOStatus = Literal["meeting", "at_risk", "breached", "unknown"]
PostmortemStatus = Literal["draft", "reviewed", "closed"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# 1-4. Service / Pipeline / Queue health records
# ─────────────────────────────────────────────────────────────────────────────

class ServiceHealthRecord(BaseModel):
    service_key: str
    label: str
    status: ServiceHealthStatus = "unknown"
    latency_ms: float | None = None
    error_rate: float | None = None
    last_heartbeat_at: str | None = None
    last_successful_job_at: str | None = None
    open_incident_ids: list[str] = Field(default_factory=list)
    affected_tenant_count: int | None = None
    metadata: dict[str, Any] | None = None
    updated_at: str = Field(default_factory=now_iso)


class PipelineHealthRecord(BaseModel):
    pipeline_key: str
    label: str
    source: str
    destination: str
    status: ServiceHealthStatus = "unknown"
    throughput_per_minute: float | None = None
    latency_ms: float | None = None
    error_rate: float | None = None
    retry_count: int | None = None
    dead_letter_count: int | None = None
    last_successful_run_at: str | None = None
    freshness_seconds: float | None = None
    affected_tenant_count: int | None = None
    updated_at: str = Field(default_factory=now_iso)


class QueueHealthRecord(BaseModel):
    queue_key: str
    label: str
    status: ServiceHealthStatus = "unknown"
    depth: int = 0
    oldest_message_age_seconds: float | None = None
    worker_count: int | None = None
    active_worker_count: int | None = None
    retry_count: int | None = None
    dead_letter_count: int | None = None
    processing_latency_ms: float | None = None
    updated_at: str = Field(default_factory=now_iso)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Incidents
# ─────────────────────────────────────────────────────────────────────────────

class IncidentRecord(BaseModel):
    incident_id: str
    title: str
    severity: IncidentSeverity
    status: IncidentStatus = "open"
    affected_services: list[str] = Field(default_factory=list)
    affected_tenants: list[str] | None = None
    affected_pipelines: list[str] | None = None
    affected_modules: list[str] | None = None
    started_at: str = Field(default_factory=now_iso)
    detected_at: str | None = None
    resolved_at: str | None = None
    owner_id: str | None = None
    runbook_id: str | None = None
    summary: str | None = None
    root_cause: str | None = None
    mitigation_steps: list[str] = Field(default_factory=list)
    customer_impact: str | None = None
    internal_notes: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Runbooks
# ─────────────────────────────────────────────────────────────────────────────

class OperationalRunbook(BaseModel):
    runbook_id: str
    title: str
    incident_type: str
    severity_hint: IncidentSeverity = "sev3"
    detection_signals: list[str] = Field(default_factory=list)
    diagnostic_steps: list[str] = Field(default_factory=list)
    mitigation_steps: list[str] = Field(default_factory=list)
    escalation_paths: list[str] = Field(default_factory=list)
    customer_comms_template: str | None = None
    postmortem_required: bool = False
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# ─────────────────────────────────────────────────────────────────────────────
# 7. SLOs
# ─────────────────────────────────────────────────────────────────────────────

class ServiceLevelObjective(BaseModel):
    slo_id: str
    service_key: str
    metric_key: str
    target: float
    window: SLOWindow = "30d"
    current_value: float | None = None
    status: SLOStatus = "unknown"
    error_budget_remaining: float | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Postmortems
# ─────────────────────────────────────────────────────────────────────────────

class IncidentPostmortem(BaseModel):
    postmortem_id: str
    incident_id: str
    summary: str
    timeline: list[str] = Field(default_factory=list)
    root_cause: str
    contributing_factors: list[str] = Field(default_factory=list)
    customer_impact: str
    detection_gap: str | None = None
    mitigation_gap: str | None = None
    prevention_actions: list[str] = Field(default_factory=list)
    owner_id: str | None = None
    status: PostmortemStatus = "draft"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Tenant status summary (tenant-safe)
# ─────────────────────────────────────────────────────────────────────────────

class TenantStatusSummary(BaseModel):
    tenant_id: str
    overall_status: ServiceHealthStatus = "unknown"
    data_freshness: str = "unknown"
    active_incidents: int = 0
    integration_status: str = "unknown"
    audit_export_status: str = "unknown"
    recommendation_status: str = "unknown"
    outcome_capture_status: str = "unknown"
    updated_at: str = Field(default_factory=now_iso)
