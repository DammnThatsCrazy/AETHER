"""
Responsiveness & Time-to-Value domain models.

Defines the runtime entities the new spine tracks:
  * PerformanceBudget
  * ActivationMilestone
  * HeartbeatState
  * ProviderSyncState
  * GraphHydrationState
  * ProjectionState
  * LensProjectionState
  * TimelineProjectionState
  * QueryExecutionState
  * BackgroundJobState
  * SurfaceReadiness (aggregates a single surface's state)

All types are plain dataclasses + helpers so they serialize cleanly to the API
envelope (APIResponse(data=...)). Status enums use stable string values so
frontend/CLI consumers never depend on ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Status enums ──────────────────────────────────────────────────────────

class DataState(str, Enum):
    missing = "missing"
    empty = "empty"
    partial = "partial"
    hydrating = "hydrating"
    ready = "ready"
    stale = "stale"
    error = "error"


class PerformanceState(str, Enum):
    unknown = "unknown"
    within_budget = "within_budget"
    warning = "warning"
    degraded = "degraded"
    blocked = "blocked"


class UserVisibleState(str, Enum):
    not_started = "not_started"
    connected = "connected"
    receiving = "receiving"
    syncing = "syncing"
    hydrating = "hydrating"
    partially_ready = "partially_ready"
    ready = "ready"
    degraded = "degraded"
    blocked = "blocked"


class MilestoneStatus(str, Enum):
    not_started = "not_started"
    activating = "activating"
    partial_value = "partial_value"
    ready = "ready"
    degraded = "degraded"
    blocked = "blocked"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    partial = "partial"
    complete = "complete"
    failed = "failed"
    retrying = "retrying"
    cancelled = "cancelled"


class QueryLane(str, Enum):
    cached = "cached"
    indexed_graph = "indexed_graph"
    projection = "projection"
    analytical = "analytical"
    semantic = "semantic"
    heavy_background = "heavy_background"
    generative = "generative"


class QueryStatus(str, Enum):
    queued = "queued"
    running = "running"
    streaming = "streaming"
    partial = "partial"
    complete = "complete"
    backgrounded = "backgrounded"
    degraded = "degraded"
    failed = "failed"


class ProjectionStatus(str, Enum):
    missing = "missing"
    building = "building"
    ready = "ready"
    stale = "stale"
    refreshing = "refreshing"
    degraded = "degraded"
    failed = "failed"


class LensProjectionStatus(str, Enum):
    not_available = "not_available"
    cached = "cached"
    building = "building"
    partial = "partial"
    ready = "ready"
    stale = "stale"
    degraded = "degraded"
    failed = "failed"


class TimelineStatus(str, Enum):
    missing = "missing"
    building = "building"
    partial = "partial"
    ready = "ready"
    stale = "stale"
    degraded = "degraded"
    failed = "failed"


# ── PerformanceBudget ─────────────────────────────────────────────────────

@dataclass
class PerformanceBudget:
    id: str
    version: str
    surface: str
    interaction: Optional[str] = None
    metric: str = "latency_ms"
    target_ms: Optional[float] = None
    target_value: Optional[float] = None
    percentile: str = "p95"  # p50 | p75 | p95 | p99
    severity: str = "info"  # info | warn | degrade | block
    applies_to: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "surface": self.surface,
            "interaction": self.interaction,
            "metric": self.metric,
            "target_ms": self.target_ms,
            "target_value": self.target_value,
            "percentile": self.percentile,
            "severity": self.severity,
            "applies_to": self.applies_to,
        }


# ── ResponsivenessMeasurement ─────────────────────────────────────────────

@dataclass
class ResponsivenessMeasurement:
    id: str
    tenant_id: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    surface: str = ""
    interaction: str = ""
    metric: str = "latency_ms"
    value_ms: Optional[float] = None
    value: Optional[float] = None
    percentile_window: Optional[str] = None
    status: str = "within_budget"  # within_budget | warning | degraded | blocked
    measured_at: str = field(default_factory=_now_iso)
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    release_version: Optional[str] = None
    environment: str = "local"  # local | preview | staging | production

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "surface": self.surface,
            "interaction": self.interaction,
            "metric": self.metric,
            "value_ms": self.value_ms,
            "value": self.value,
            "percentile_window": self.percentile_window,
            "status": self.status,
            "measured_at": self.measured_at,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "release_version": self.release_version,
            "environment": self.environment,
        }


# ── ActivationMilestone ───────────────────────────────────────────────────

FIRST_VALUE_KINDS = frozenset({
    "sdk_heartbeat", "live_event", "provider_sample",
    "graph_node", "graph_edge", "profile_360", "campaign_360",
    "journey_360", "timeline", "lens", "recommendation",
})


@dataclass
class ActivationMilestone:
    tenant_id: str
    environment: str = "local"

    tenant_created_at: Optional[str] = None
    sdk_key_created_at: Optional[str] = None
    sdk_initialized_at: Optional[str] = None
    first_event_received_at: Optional[str] = None
    first_event_acked_at: Optional[str] = None
    first_heartbeat_visible_at: Optional[str] = None
    first_valid_event_at: Optional[str] = None
    first_provider_connected_at: Optional[str] = None
    first_provider_sample_at: Optional[str] = None
    first_graph_node_at: Optional[str] = None
    first_graph_edge_at: Optional[str] = None
    first_graph_stub_visible_at: Optional[str] = None
    first_lens_ready_at: Optional[str] = None
    first_timeline_ready_at: Optional[str] = None
    first_360_ready_at: Optional[str] = None
    first_recommendation_ready_at: Optional[str] = None

    time_to_first_heartbeat_ms: Optional[float] = None
    time_to_first_graph_stub_ms: Optional[float] = None
    time_to_first_value_ms: Optional[float] = None
    first_value_kind: Optional[str] = None

    status: str = "not_started"  # not_started | activating | partial_value | ready | degraded | blocked

    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "environment": self.environment,
            "tenant_created_at": self.tenant_created_at,
            "sdk_key_created_at": self.sdk_key_created_at,
            "sdk_initialized_at": self.sdk_initialized_at,
            "first_event_received_at": self.first_event_received_at,
            "first_event_acked_at": self.first_event_acked_at,
            "first_heartbeat_visible_at": self.first_heartbeat_visible_at,
            "first_valid_event_at": self.first_valid_event_at,
            "first_provider_connected_at": self.first_provider_connected_at,
            "first_provider_sample_at": self.first_provider_sample_at,
            "first_graph_node_at": self.first_graph_node_at,
            "first_graph_edge_at": self.first_graph_edge_at,
            "first_graph_stub_visible_at": self.first_graph_stub_visible_at,
            "first_lens_ready_at": self.first_lens_ready_at,
            "first_timeline_ready_at": self.first_timeline_ready_at,
            "first_360_ready_at": self.first_360_ready_at,
            "first_recommendation_ready_at": self.first_recommendation_ready_at,
            "time_to_first_heartbeat_ms": self.time_to_first_heartbeat_ms,
            "time_to_first_graph_stub_ms": self.time_to_first_graph_stub_ms,
            "time_to_first_value_ms": self.time_to_first_value_ms,
            "first_value_kind": self.first_value_kind,
            "status": self.status,
            "updated_at": self.updated_at,
        }


# ── HeartbeatState ────────────────────────────────────────────────────────

class HeartbeatStatus(str, Enum):
    not_seen = "not_seen"
    receiving = "receiving"
    validating = "validating"
    healthy = "healthy"
    degraded = "degraded"
    blocked = "blocked"


@dataclass
class HeartbeatState:
    tenant_id: str
    source_id: str
    sdk_id: Optional[str] = None
    environment: str = "local"  # development | preview | staging | production
    status: str = "not_seen"
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    event_count: int = 0
    valid_event_count: int = 0
    invalid_event_count: int = 0
    last_event_type: Optional[str] = None
    last_error: Optional[str] = None
    schema_version: Optional[str] = None
    ingestion_latency_ms: Optional[float] = None
    visible_in_dashboard_at: Optional[str] = None
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "source_id": self.source_id,
            "sdk_id": self.sdk_id,
            "environment": self.environment,
            "status": self.status,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "event_count": self.event_count,
            "valid_event_count": self.valid_event_count,
            "invalid_event_count": self.invalid_event_count,
            "last_event_type": self.last_event_type,
            "last_error": self.last_error,
            "schema_version": self.schema_version,
            "ingestion_latency_ms": self.ingestion_latency_ms,
            "visible_in_dashboard_at": self.visible_in_dashboard_at,
            "updated_at": self.updated_at,
        }


# ── ProviderSyncState ─────────────────────────────────────────────────────

class ProviderSyncStatus(str, Enum):
    not_connected = "not_connected"
    connected = "connected"
    discovering = "discovering"
    sampling = "sampling"
    syncing = "syncing"
    hydrating_graph = "hydrating_graph"
    partially_ready = "partially_ready"
    ready = "ready"
    degraded = "degraded"
    blocked = "blocked"


@dataclass
class ProviderSyncState:
    tenant_id: str
    provider_id: str
    connection_id: str
    status: str = "not_connected"
    connected_at: Optional[str] = None
    first_metadata_at: Optional[str] = None
    first_sample_record_at: Optional[str] = None
    first_graph_hydration_at: Optional[str] = None
    last_sync_started_at: Optional[str] = None
    last_sync_completed_at: Optional[str] = None
    next_sync_at: Optional[str] = None
    records_discovered: Optional[int] = None
    records_sampled: Optional[int] = None
    records_synced: Optional[int] = None
    records_failed: Optional[int] = None
    rate_limited: bool = False
    permission_issues: list[str] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    progress_percent: Optional[float] = None
    visible_status_updated_at: Optional[str] = None
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "provider_id": self.provider_id,
            "connection_id": self.connection_id,
            "status": self.status,
            "connected_at": self.connected_at,
            "first_metadata_at": self.first_metadata_at,
            "first_sample_record_at": self.first_sample_record_at,
            "first_graph_hydration_at": self.first_graph_hydration_at,
            "last_sync_started_at": self.last_sync_started_at,
            "last_sync_completed_at": self.last_sync_completed_at,
            "next_sync_at": self.next_sync_at,
            "records_discovered": self.records_discovered,
            "records_sampled": self.records_sampled,
            "records_synced": self.records_synced,
            "records_failed": self.records_failed,
            "rate_limited": self.rate_limited,
            "permission_issues": self.permission_issues,
            "degraded_reasons": self.degraded_reasons,
            "blocking_reasons": self.blocking_reasons,
            "progress_percent": self.progress_percent,
            "visible_status_updated_at": self.visible_status_updated_at,
            "updated_at": self.updated_at,
        }


# ── GraphHydrationState ───────────────────────────────────────────────────

class GraphHydrationStatus(str, Enum):
    not_started = "not_started"
    receiving = "receiving"
    normalizing = "normalizing"
    resolving_entities = "resolving_entities"
    creating_edges = "creating_edges"
    building_projections = "building_projections"
    hydrating_surfaces = "hydrating_surfaces"
    partially_ready = "partially_ready"
    ready = "ready"
    degraded = "degraded"
    blocked = "blocked"


@dataclass
class GraphHydrationState:
    tenant_id: str
    graph_version: str
    status: str = "not_started"
    raw_events_count: int = 0
    normalized_records_count: int = 0
    entity_count: int = 0
    edge_count: int = 0
    projected_entity_count: int = 0
    projected_edge_count: int = 0
    first_node_created_at: Optional[str] = None
    first_edge_created_at: Optional[str] = None
    first_projection_created_at: Optional[str] = None
    first_stub_visible_at: Optional[str] = None
    hydration_progress_percent: Optional[float] = None
    stale_projection_count: Optional[int] = None
    failed_projection_count: Optional[int] = None
    degraded_reasons: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "graph_version": self.graph_version,
            "status": self.status,
            "raw_events_count": self.raw_events_count,
            "normalized_records_count": self.normalized_records_count,
            "entity_count": self.entity_count,
            "edge_count": self.edge_count,
            "projected_entity_count": self.projected_entity_count,
            "projected_edge_count": self.projected_edge_count,
            "first_node_created_at": self.first_node_created_at,
            "first_edge_created_at": self.first_edge_created_at,
            "first_projection_created_at": self.first_projection_created_at,
            "first_stub_visible_at": self.first_stub_visible_at,
            "hydration_progress_percent": self.hydration_progress_percent,
            "stale_projection_count": self.stale_projection_count,
            "failed_projection_count": self.failed_projection_count,
            "degraded_reasons": self.degraded_reasons,
            "blocking_reasons": self.blocking_reasons,
            "updated_at": self.updated_at,
        }


# ── ProjectionState ───────────────────────────────────────────────────────

@dataclass
class ProjectionState:
    tenant_id: str
    projection_id: str
    projection_type: str
    graph_version: Optional[str] = None
    source_version: Optional[str] = None
    status: str = "missing"
    freshness_ms: Optional[float] = None
    last_built_at: Optional[str] = None
    last_refreshed_at: Optional[str] = None
    last_accessed_at: Optional[str] = None
    build_duration_ms: Optional[float] = None
    p95_read_latency_ms: Optional[float] = None
    dependency_versions: dict[str, str] = field(default_factory=dict)
    degraded_reasons: list[str] = field(default_factory=list)
    failure_reason: Optional[str] = None
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "projection_id": self.projection_id,
            "projection_type": self.projection_type,
            "graph_version": self.graph_version,
            "source_version": self.source_version,
            "status": self.status,
            "freshness_ms": self.freshness_ms,
            "last_built_at": self.last_built_at,
            "last_refreshed_at": self.last_refreshed_at,
            "last_accessed_at": self.last_accessed_at,
            "build_duration_ms": self.build_duration_ms,
            "p95_read_latency_ms": self.p95_read_latency_ms,
            "dependency_versions": self.dependency_versions,
            "degraded_reasons": self.degraded_reasons,
            "failure_reason": self.failure_reason,
            "updated_at": self.updated_at,
        }


# ── LensProjectionState ───────────────────────────────────────────────────

@dataclass
class LensProjectionState:
    tenant_id: str
    lens_id: str
    graph_version: str
    entity_scope: Optional[str] = None
    time_window: Optional[str] = None
    grain: Optional[str] = None
    permission_scope: Optional[str] = None
    status: str = "not_available"
    visual_toggle_latency_ms: Optional[float] = None
    cached_result_latency_ms: Optional[float] = None
    first_result_latency_ms: Optional[float] = None
    full_hydration_latency_ms: Optional[float] = None
    result_count: Optional[int] = None
    delta_count: Optional[int] = None
    last_built_at: Optional[str] = None
    degraded_reasons: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "lens_id": self.lens_id,
            "graph_version": self.graph_version,
            "entity_scope": self.entity_scope,
            "time_window": self.time_window,
            "grain": self.grain,
            "permission_scope": self.permission_scope,
            "status": self.status,
            "visual_toggle_latency_ms": self.visual_toggle_latency_ms,
            "cached_result_latency_ms": self.cached_result_latency_ms,
            "first_result_latency_ms": self.first_result_latency_ms,
            "full_hydration_latency_ms": self.full_hydration_latency_ms,
            "result_count": self.result_count,
            "delta_count": self.delta_count,
            "last_built_at": self.last_built_at,
            "degraded_reasons": self.degraded_reasons,
            "updated_at": self.updated_at,
        }


# ── TimelineProjectionState ───────────────────────────────────────────────

class TimelineGrain(str, Enum):
    minute = "minute"
    hour = "hour"
    day = "day"
    week = "week"
    month = "month"


@dataclass
class TimelineProjectionState:
    tenant_id: str
    graph_version: Optional[str] = None
    entity_scope: Optional[str] = None
    available_grains: list[str] = field(default_factory=list)
    status: str = "missing"
    first_render_latency_ms: Optional[float] = None
    pan_latency_ms: Optional[float] = None
    zoom_latency_ms: Optional[float] = None
    grain_change_latency_ms: Optional[float] = None
    last_built_at: Optional[str] = None
    freshness_ms: Optional[float] = None
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "graph_version": self.graph_version,
            "entity_scope": self.entity_scope,
            "available_grains": self.available_grains,
            "status": self.status,
            "first_render_latency_ms": self.first_render_latency_ms,
            "pan_latency_ms": self.pan_latency_ms,
            "zoom_latency_ms": self.zoom_latency_ms,
            "grain_change_latency_ms": self.grain_change_latency_ms,
            "last_built_at": self.last_built_at,
            "freshness_ms": self.freshness_ms,
            "updated_at": self.updated_at,
        }


# ── QueryExecutionState ───────────────────────────────────────────────────

@dataclass
class QueryExecutionState:
    tenant_id: str
    query_id: str
    user_id: Optional[str] = None
    lane: str = "projection"
    status: str = "queued"
    submitted_at: str = field(default_factory=_now_iso)
    first_result_at: Optional[str] = None
    completed_at: Optional[str] = None
    first_result_latency_ms: Optional[float] = None
    total_latency_ms: Optional[float] = None
    cache_hit: Optional[bool] = None
    projection_used: Optional[str] = None
    graph_version: Optional[str] = None
    user_visible_progress: Optional[dict[str, Any]] = None
    degraded_reasons: list[str] = field(default_factory=list)
    failure_reason: Optional[str] = None
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "query_id": self.query_id,
            "user_id": self.user_id,
            "lane": self.lane,
            "status": self.status,
            "submitted_at": self.submitted_at,
            "first_result_at": self.first_result_at,
            "completed_at": self.completed_at,
            "first_result_latency_ms": self.first_result_latency_ms,
            "total_latency_ms": self.total_latency_ms,
            "cache_hit": self.cache_hit,
            "projection_used": self.projection_used,
            "graph_version": self.graph_version,
            "user_visible_progress": self.user_visible_progress,
            "degraded_reasons": self.degraded_reasons,
            "failure_reason": self.failure_reason,
            "updated_at": self.updated_at,
        }


# ── BackgroundJobState ────────────────────────────────────────────────────

@dataclass
class BackgroundJobState:
    tenant_id: str
    job_id: str
    job_type: str
    status: str = "queued"
    progress_percent: Optional[float] = None
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    records_processed: Optional[int] = None
    records_total: Optional[int] = None
    current_stage: Optional[str] = None
    user_visible: bool = True
    can_retry: bool = True
    can_cancel: bool = False
    failure_reason: Optional[str] = None
    degraded_surface_ids: list[str] = field(default_factory=list)
    updated_ts: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "records_processed": self.records_processed,
            "records_total": self.records_total,
            "current_stage": self.current_stage,
            "user_visible": self.user_visible,
            "can_retry": self.can_retry,
            "can_cancel": self.can_cancel,
            "failure_reason": self.failure_reason,
            "degraded_surface_ids": self.degraded_surface_ids,
            "updated_ts": self.updated_ts,
        }


# ── SurfaceReadiness ──────────────────────────────────────────────────────

SURFACE_NAMES = frozenset({
    "dashboard", "graph", "timeline", "profile_360", "campaign_360",
    "journey_360", "communications_360", "agent_360", "execution_360",
    "value", "signals", "syndicates", "lenses", "providers", "sdk_fleet",
})


@dataclass
class SurfaceReadiness:
    tenant_id: str
    surface: str
    data_state: str = "missing"
    performance_state: str = "unknown"
    user_visible_state: str = "not_started"
    last_updated_at: Optional[str] = None
    freshness_ms: Optional[float] = None
    blocking_reasons: list[str] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)
    required_milestones: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "surface": self.surface,
            "data_state": self.data_state,
            "performance_state": self.performance_state,
            "user_visible_state": self.user_visible_state,
            "last_updated_at": self.last_updated_at,
            "freshness_ms": self.freshness_ms,
            "blocking_reasons": self.blocking_reasons,
            "degraded_reasons": self.degraded_reasons,
            "required_milestones": self.required_milestones,
            "updated_at": self.updated_at,
        }


# ── UserVisibleProgressState ──────────────────────────────────────────────

PROGRESS_LABELS = frozenset({
    "Connecting", "Connected", "Receiving events", "Validating", "Syncing",
    "Hydrating graph", "Building timeline", "Applying lens",
    "Preparing result", "Running in background", "Partially ready", "Ready",
    "Degraded", "Blocked",
})


@dataclass
class UserVisibleProgressState:
    label: str
    detail: Optional[str] = None
    progress_percent: Optional[float] = None
    last_updated_at: Optional[str] = None
    estimated_next_step: Optional[str] = None
    action_required: bool = False
    action_label: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "detail": self.detail,
            "progress_percent": self.progress_percent,
            "last_updated_at": self.last_updated_at,
            "estimated_next_step": self.estimated_next_step,
            "action_required": self.action_required,
            "action_label": self.action_label,
        }


# ── Responsiveness summary envelope (for GET /tenants/:id/responsiveness) ─

@dataclass
class ResponsivenessEnvelope:
    tenant_id: str
    environment: str = "local"
    activation_milestone: Optional[dict[str, Any]] = None
    surfaces: list[dict[str, Any]] = field(default_factory=list)
    sdk_heartbeats: list[dict[str, Any]] = field(default_factory=list)
    provider_sync_states: list[dict[str, Any]] = field(default_factory=list)
    graph_hydration: Optional[dict[str, Any]] = None
    projections: list[dict[str, Any]] = field(default_factory=list)
    lens_projections: list[dict[str, Any]] = field(default_factory=list)
    timeline_projection: Optional[dict[str, Any]] = None
    background_jobs: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "environment": self.environment,
            "activation_milestone": self.activation_milestone,
            "surfaces": self.surfaces,
            "sdk_heartbeats": self.sdk_heartbeats,
            "provider_sync_states": self.provider_sync_states,
            "graph_hydration": self.graph_hydration,
            "projections": self.projections,
            "lens_projections": self.lens_projections,
            "timeline_projection": self.timeline_projection,
            "background_jobs": self.background_jobs,
            "updated_at": self.updated_at,
        }
