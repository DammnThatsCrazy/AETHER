"""
Responsiveness & Time-to-Value spine service.

Records real evidence from the platform's integration points:

* SDK ingestion ACK (batch.py) → HeartbeatState + ActivationMilestone
* Provider connection lifecycle (provider_runtime/connection.py) →
  ProviderSyncState
* Graph projector (semantic_intelligence/graph_projector.py) →
  GraphHydrationState
* Projection runtime (projection_engine/runtime.py) → ProjectionState +
  LensProjectionState
* Jobs worker (jobs/worker.py) → BackgroundJobState
* Analytics query handler (analytics/routes.py) → QueryExecutionState +
  SurfaceReadiness

The service is intentionally read-heavy for the API surface and write-heavy
at the integration points. Integration-point writers are exposed as explicit
methods so the calling code can pass a real latency measurement and a trace
context.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics
from shared.observability import new_traceparent

from .models import (
    ActivationMilestone,
    BackgroundJobState,
    DataState,
    GraphHydrationState,
    HeartbeatState,
    LensProjectionState,
    PerformanceBudget,
    ProjectionState,
    ProviderSyncState,
    QueryExecutionState,
    QueryLane,
    QueryStatus,
    ResponsivenessEnvelope,
    SurfaceReadiness,
    TimelineProjectionState,
    UserVisibleProgressState,
)
from .repository import ResponsivenessRepository

logger = get_logger("aether.responsiveness")

# ── surface → required milestones mapping (readiness formula) ────────────

_SURFACE_MILESTONES: dict[str, list[str]] = {
    "dashboard": [
        "first_heartbeat_visible_at",
        "first_graph_stub_visible_at",
    ],
    "graph": [
        "first_graph_node_at",
        "first_graph_edge_at",
        "first_graph_stub_visible_at",
    ],
    "timeline": ["first_timeline_ready_at"],
    "profile_360": ["first_360_ready_at"],
    "campaign_360": ["first_360_ready_at"],
    "journey_360": ["first_360_ready_at"],
    "communications_360": ["first_360_ready_at"],
    "agent_360": ["first_360_ready_at"],
    "execution_360": ["first_360_ready_at"],
    "value": ["first_360_ready_at"],
    "signals": ["first_360_ready_at"],
    "syndicates": ["first_360_ready_at"],
    "lenses": ["first_lens_ready_at"],
    "providers": ["first_provider_sample_at"],
    "sdk_fleet": ["first_heartbeat_visible_at"],
}


# ── service ──────────────────────────────────────────────────────────────

class ResponsivenessService:
    """Records and aggregates responsiveness state for one or more tenants."""

    def __init__(self, repo: Optional[ResponsivenessRepository] = None) -> None:
        self._repo = repo or ResponsivenessRepository()

    # ── activation milestones ────────────────────────────────────────────

    async def record_first_event_ack(
        self,
        tenant_id: str,
        event_id: str,
        batch_id: Optional[str],
        received_at: str,
        ack_latency_ms: float,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        environment: str = "local",
    ) -> ActivationMilestone:
        """Called by the ingestion ACK path (batch.py) after an event is accepted.

        This is the spine's SDK heartbeat fast-path hook: it records the first
        visible ACK and advances the activation milestone when the tenant
        crosses the first-value threshold.
        """
        milestone = await self._load_milestone(tenant_id)
        now = utc_now().isoformat()

        if milestone.first_event_acked_at is None:
            milestone.first_event_acked_at = now
            milestone.first_event_received_at = milestone.first_event_received_at or received_at

        milestone.updated_at = now
        metrics.increment(
            "aether_time_to_first_event_ack_ms",
            value=ack_latency_ms,
            labels={"tenant_id": tenant_id},
        )

        if milestone.first_heartbeat_visible_at is None and ack_latency_ms < 15000:
            milestone.first_heartbeat_visible_at = now
            ttl = (
                milestone.time_to_first_heartbeat_ms
                if milestone.time_to_first_heartbeat_ms is not None
                else 0
            )
            delta = 0
            if milestone.first_event_received_at:
                try:
                    r = datetime.fromisoformat(milestone.first_event_received_at)
                    a = datetime.fromisoformat(now)
                    delta = (a - r).total_seconds() * 1000
                except ValueError:
                    delta = 0
            milestone.time_to_first_heartbeat_ms = delta
            milestone.first_value_kind = milestone.first_value_kind or "sdk_heartbeat"
            milestone.time_to_first_value_ms = milestone.time_to_first_value_ms or delta
            milestone.status = milestone.status or "not_started"
            if milestone.status == "not_started":
                milestone.status = "partial_value"
            await self._publish_activation_update(tenant_id)

        await self._repo.put_activation_milestone(tenant_id, milestone.to_dict())
        return milestone

    async def record_first_valid_event(
        self,
        tenant_id: str,
        event_id: str,
        received_at: str,
        trace_id: Optional[str] = None,
    ) -> ActivationMilestone:
        """Called when an event passes validation (batch.py validate_event)."""
        milestone = await self._load_milestone(tenant_id)
        if milestone.first_valid_event_at is None:
            milestone.first_valid_event_at = received_at
            milestone.updated_at = utc_now().isoformat()
            await self._repo.put_activation_milestone(tenant_id, milestone.to_dict())
        return milestone

    async def mark_first_value(
        self,
        tenant_id: str,
        kind: str,
        occurred_at: Optional[str] = None,
    ) -> ActivationMilestone:
        """Record a first-value moment (graph node, lens ready, 360 ready, etc.)."""
        if kind not in {
            "sdk_heartbeat", "live_event", "provider_sample",
            "graph_node", "graph_edge", "profile_360", "campaign_360",
            "journey_360", "timeline", "lens", "recommendation",
        }:
            kind = "sdk_heartbeat"
        milestone = await self._load_milestone(tenant_id)
        now = occurred_at or utc_now().isoformat()
        field = {
            "graph_node": "first_graph_node_at",
            "graph_edge": "first_graph_edge_at",
            "provider_sample": "first_provider_sample_at",
            "lens": "first_lens_ready_at",
            "timeline": "first_timeline_ready_at",
            "profile_360": "first_360_ready_at",
            "campaign_360": "first_360_ready_at",
            "journey_360": "first_360_ready_at",
            "recommendation": "first_recommendation_ready_at",
        }.get(kind)
        if field and getattr(milestone, field) is None:
            setattr(milestone, field, now)
        milestone.first_value_kind = milestone.first_value_kind or kind
        milestone.time_to_first_value_ms = milestone.time_to_first_value_ms or 0
        milestone.status = "ready" if milestone.status == "partial_value" else milestone.status
        milestone.updated_at = utc_now().isoformat()
        await self._repo.put_activation_milestone(tenant_id, milestone.to_dict())
        await self._publish_activation_update(tenant_id)
        return milestone

    async def get_activation_milestone(self, tenant_id: str) -> Optional[dict]:
        row = await self._repo.get_activation_milestone(tenant_id)
        return row

    # ── heartbeat state ──────────────────────────────────────────────────

    async def update_heartbeat_state(
        self,
        tenant_id: str,
        source_id: str,
        sdk_id: Optional[str],
        environment: str,
        status: str,
        event_count: int,
        valid_event_count: int,
        invalid_event_count: int,
        last_event_type: Optional[str],
        last_error: Optional[str],
        schema_version: Optional[str],
        ingestion_latency_ms: Optional[float],
        now: Optional[str] = None,
    ) -> HeartbeatState:
        """Called by the ingestion ACK path to keep HeartbeatState fresh."""
        state = HeartbeatState(
            tenant_id=tenant_id,
            source_id=source_id,
            sdk_id=sdk_id,
            environment=environment,
            status=status,
            event_count=event_count,
            valid_event_count=valid_event_count,
            invalid_event_count=invalid_event_count,
            last_event_type=last_event_type,
            last_error=last_error,
            schema_version=schema_version,
            ingestion_latency_ms=ingestion_latency_ms,
            updated_at=now or utc_now().isoformat(),
        )
        existing = await self._repo.get_heartbeat_state(tenant_id, source_id)
        if existing:
            state.first_seen_at = existing.get("first_seen_at") or state.first_seen_at
            state.visible_in_dashboard_at = existing.get("visible_in_dashboard_at")
        state.visible_in_dashboard_at = state.visible_in_dashboard_at or utc_now().isoformat()
        await self._repo.put_heartbeat_state(
            tenant_id, source_id, state.to_dict()
        )
        return state

    async def get_heartbeat_states(self, tenant_id: str) -> list[dict]:
        return await self._repo.list_heartbeat_states(tenant_id)

    # ── provider sync state ──────────────────────────────────────────────

    async def update_provider_sync_state(
        self,
        tenant_id: str,
        provider_id: str,
        connection_id: str,
        status: str,
        *,
        connected_at: Optional[str] = None,
        first_metadata_at: Optional[str] = None,
        first_sample_record_at: Optional[str] = None,
        first_graph_hydration_at: Optional[str] = None,
        last_sync_started_at: Optional[str] = None,
        last_sync_completed_at: Optional[str] = None,
        next_sync_at: Optional[str] = None,
        records_discovered: Optional[int] = None,
        records_sampled: Optional[int] = None,
        records_synced: Optional[int] = None,
        records_failed: Optional[int] = None,
        rate_limited: bool = False,
        permission_issues: Optional[list[str]] = None,
        degraded_reasons: Optional[list[str]] = None,
        blocking_reasons: Optional[list[str]] = None,
        progress_percent: Optional[float] = None,
    ) -> ProviderSyncState:
        """Called by the provider connection orchestrator / scheduler."""
        state = ProviderSyncState(
            tenant_id=tenant_id,
            provider_id=provider_id,
            connection_id=connection_id,
            status=status,
            connected_at=connected_at,
            first_metadata_at=first_metadata_at,
            first_sample_record_at=first_sample_record_at,
            first_graph_hydration_at=first_graph_hydration_at,
            last_sync_started_at=last_sync_started_at,
            last_sync_completed_at=last_sync_completed_at,
            next_sync_at=next_sync_at,
            records_discovered=records_discovered,
            records_sampled=records_sampled,
            records_synced=records_synced,
            records_failed=records_failed,
            rate_limited=rate_limited,
            permission_issues=permission_issues or [],
            degraded_reasons=degraded_reasons or [],
            blocking_reasons=blocking_reasons or [],
            progress_percent=progress_percent,
            updated_at=utc_now().isoformat(),
        )
        existing = await self._repo.get_provider_sync_state(tenant_id, provider_id)
        if existing:
            state.visible_status_updated_at = existing.get("visible_status_updated_at")
        state.visible_status_updated_at = state.visible_status_updated_at or utc_now().isoformat()
        await self._repo.put_provider_sync_state(
            tenant_id, provider_id, state.to_dict()
        )
        await self._publish_provider_update(tenant_id, provider_id)
        return state

    async def get_provider_sync_states(self, tenant_id: str) -> list[dict]:
        return await self._repo.list_provider_sync_states(tenant_id)

    # ── graph hydration state ────────────────────────────────────────────

    async def update_graph_hydration_state(
        self,
        tenant_id: str,
        graph_version: str,
        status: str,
        *,
        raw_events_count: int = 0,
        normalized_records_count: int = 0,
        entity_count: int = 0,
        edge_count: int = 0,
        projected_entity_count: int = 0,
        projected_edge_count: int = 0,
        first_node_created_at: Optional[str] = None,
        first_edge_created_at: Optional[str] = None,
        first_projection_created_at: Optional[str] = None,
        first_stub_visible_at: Optional[str] = None,
        hydration_progress_percent: Optional[float] = None,
        stale_projection_count: Optional[int] = None,
        failed_projection_count: Optional[int] = None,
        degraded_reasons: Optional[list[str]] = None,
        blocking_reasons: Optional[list[str]] = None,
        mark_first_stub: bool = False,
    ) -> GraphHydrationState:
        """Called by the graph projector / projection builder."""
        state = GraphHydrationState(
            tenant_id=tenant_id,
            graph_version=graph_version,
            status=status,
            raw_events_count=raw_events_count,
            normalized_records_count=normalized_records_count,
            entity_count=entity_count,
            edge_count=edge_count,
            projected_entity_count=projected_entity_count,
            projected_edge_count=projected_edge_count,
            first_node_created_at=first_node_created_at,
            first_edge_created_at=first_edge_created_at,
            first_projection_created_at=first_projection_created_at,
            first_stub_visible_at=first_stub_visible_at,
            hydration_progress_percent=hydration_progress_percent,
            stale_projection_count=stale_projection_count,
            failed_projection_count=failed_projection_count,
            degraded_reasons=degraded_reasons or [],
            blocking_reasons=blocking_reasons or [],
            updated_at=utc_now().isoformat(),
        )
        existing = await self._repo.get_graph_hydration_state(tenant_id, graph_version)
        if existing:
            state.first_stub_visible_at = existing.get("first_stub_visible_at") or state.first_stub_visible_at
        if mark_first_stub and state.first_stub_visible_at is None:
            state.first_stub_visible_at = utc_now().isoformat()
            milestone = await self._load_milestone(tenant_id)
            if milestone.first_graph_stub_visible_at is None:
                milestone.first_graph_stub_visible_at = state.first_stub_visible_at
                milestone.time_to_first_graph_stub_ms = milestone.time_to_first_graph_stub_ms or 0
                milestone.updated_at = utc_now().isoformat()
                await self._repo.put_activation_milestone(tenant_id, milestone.to_dict())
        await self._repo.put_graph_hydration_state(
            tenant_id, graph_version, state.to_dict()
        )
        return state

    async def get_graph_hydration_state(
        self, tenant_id: str, graph_version: str
    ) -> Optional[dict]:
        return await self._repo.get_graph_hydration_state(tenant_id, graph_version)

    async def mark_graph_stub_visible(self, tenant_id: str, graph_version: str) -> GraphHydrationState:
        """Explicit hook for the graph stub renderer to call."""
        existing = await self._repo.get_graph_hydration_state(tenant_id, graph_version)
        status = (existing or {}).get("status") or "not_started"
        return await self.update_graph_hydration_state(
            tenant_id,
            graph_version,
            status=status,
            first_stub_visible_at=utc_now().isoformat(),
            mark_first_stub=True,
        )

    # ── projection state ─────────────────────────────────────────────────

    async def update_projection_state(
        self,
        tenant_id: str,
        projection_id: str,
        projection_type: str,
        status: str,
        *,
        graph_version: Optional[str] = None,
        source_version: Optional[str] = None,
        freshness_ms: Optional[float] = None,
        last_built_at: Optional[str] = None,
        last_refreshed_at: Optional[str] = None,
        build_duration_ms: Optional[float] = None,
        p95_read_latency_ms: Optional[float] = None,
        degraded_reasons: Optional[list[str]] = None,
        failure_reason: Optional[str] = None,
    ) -> ProjectionState:
        state = ProjectionState(
            tenant_id=tenant_id,
            projection_id=projection_id,
            projection_type=projection_type,
            graph_version=graph_version,
            source_version=source_version,
            status=status,
            freshness_ms=freshness_ms,
            last_built_at=last_built_at,
            last_refreshed_at=last_refreshed_at,
            build_duration_ms=build_duration_ms,
            p95_read_latency_ms=p95_read_latency_ms,
            degraded_reasons=degraded_reasons or [],
            failure_reason=failure_reason,
            updated_at=utc_now().isoformat(),
        )
        existing = await self._repo.get_projection_state(tenant_id, projection_id)
        if existing:
            state.last_accessed_at = utc_now().isoformat()
            state.last_built_at = existing.get("last_built_at") or state.last_built_at
        else:
            state.last_built_at = state.last_built_at or utc_now().isoformat()
        await self._repo.put_projection_state(
            tenant_id, projection_id, state.to_dict()
        )
        return state

    async def get_projection_states(self, tenant_id: str) -> list[dict]:
        return await self._repo.list_projection_states(tenant_id)

    # ── lens projection state ────────────────────────────────────────────

    async def update_lens_projection_state(
        self,
        tenant_id: str,
        lens_id: str,
        graph_version: str,
        scope_hash: str,
        status: str,
        *,
        entity_scope: Optional[str] = None,
        time_window: Optional[str] = None,
        grain: Optional[str] = None,
        permission_scope: Optional[str] = None,
        visual_toggle_latency_ms: Optional[float] = None,
        cached_result_latency_ms: Optional[float] = None,
        first_result_latency_ms: Optional[float] = None,
        full_hydration_latency_ms: Optional[float] = None,
        result_count: Optional[int] = None,
        delta_count: Optional[int] = None,
        degraded_reasons: Optional[list[str]] = None,
    ) -> LensProjectionState:
        state = LensProjectionState(
            tenant_id=tenant_id,
            lens_id=lens_id,
            graph_version=graph_version,
            entity_scope=entity_scope,
            time_window=time_window,
            grain=grain,
            permission_scope=permission_scope,
            status=status,
            visual_toggle_latency_ms=visual_toggle_latency_ms,
            cached_result_latency_ms=cached_result_latency_ms,
            first_result_latency_ms=first_result_latency_ms,
            full_hydration_latency_ms=full_hydration_latency_ms,
            result_count=result_count,
            delta_count=delta_count,
            degraded_reasons=degraded_reasons or [],
            updated_at=utc_now().isoformat(),
        )
        existing = await self._repo.get_lens_projection_state(
            tenant_id, lens_id, graph_version, scope_hash
        )
        if existing:
            state.last_built_at = existing.get("last_built_at") or state.last_built_at
        state.last_built_at = state.last_built_at or utc_now().isoformat()
        await self._repo.put_lens_projection_state(
            tenant_id, lens_id, graph_version, scope_hash, state.to_dict()
        )
        await self._publish_lens_update(tenant_id, lens_id, graph_version, scope_hash)
        return state

    async def get_lens_projection_state(
        self,
        tenant_id: str,
        lens_id: str,
        graph_version: str,
        scope_hash: str,
    ) -> Optional[dict]:
        return await self._repo.get_lens_projection_state(
            tenant_id, lens_id, graph_version, scope_hash
        )

    async def list_lens_projection_states(self, tenant_id: str) -> list[dict]:
        return await self._repo.list_lens_projection_states(tenant_id)

    # ── timeline projection state ────────────────────────────────────────

    async def update_timeline_projection_state(
        self,
        tenant_id: str,
        scope_hash: str,
        status: str,
        *,
        graph_version: Optional[str] = None,
        entity_scope: Optional[str] = None,
        available_grains: Optional[list[str]] = None,
        first_render_latency_ms: Optional[float] = None,
        pan_latency_ms: Optional[float] = None,
        zoom_latency_ms: Optional[float] = None,
        grain_change_latency_ms: Optional[float] = None,
        freshness_ms: Optional[float] = None,
    ) -> TimelineProjectionState:
        state = TimelineProjectionState(
            tenant_id=tenant_id,
            graph_version=graph_version,
            entity_scope=entity_scope,
            available_grains=available_grains or [],
            status=status,
            first_render_latency_ms=first_render_latency_ms,
            pan_latency_ms=pan_latency_ms,
            zoom_latency_ms=zoom_latency_ms,
            grain_change_latency_ms=grain_change_latency_ms,
            freshness_ms=freshness_ms,
            updated_at=utc_now().isoformat(),
        )
        existing = await self._repo.get_timeline_projection_state(tenant_id, scope_hash)
        if existing:
            state.last_built_at = existing.get("last_built_at") or state.last_built_at
        state.last_built_at = state.last_built_at or utc_now().isoformat()
        await self._repo.put_timeline_projection_state(
            tenant_id, scope_hash, state.to_dict()
        )
        return state

    async def get_timeline_projection_state(
        self, tenant_id: str, scope_hash: str
    ) -> Optional[dict]:
        return await self._repo.get_timeline_projection_state(tenant_id, scope_hash)

    # ── query execution state ────────────────────────────────────────────

    async def record_query(
        self,
        tenant_id: str,
        query_id: str,
        lane: str,
        status: str,
        *,
        user_id: Optional[str] = None,
        first_result_latency_ms: Optional[float] = None,
        total_latency_ms: Optional[float] = None,
        cache_hit: Optional[bool] = None,
        projection_used: Optional[str] = None,
        graph_version: Optional[str] = None,
        first_result_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        degraded_reasons: Optional[list[str]] = None,
        failure_reason: Optional[str] = None,
        user_visible_progress: Optional[dict] = None,
    ) -> QueryExecutionState:
        state = QueryExecutionState(
            tenant_id=tenant_id,
            query_id=query_id,
            user_id=user_id,
            lane=lane,
            status=status,
            first_result_latency_ms=first_result_latency_ms,
            total_latency_ms=total_latency_ms,
            cache_hit=cache_hit,
            projection_used=projection_used,
            graph_version=graph_version,
            first_result_at=first_result_at,
            completed_at=completed_at,
            degraded_reasons=degraded_reasons or [],
            failure_reason=failure_reason,
            user_visible_progress=user_visible_progress,
            updated_at=utc_now().isoformat(),
        )
        existing = await self._repo.get_query_execution_state(tenant_id, query_id)
        if existing:
            state.submitted_at = existing.get("submitted_at") or state.submitted_at
            state.completed_at = completed_at or existing.get("completed_at")
        else:
            state.submitted_at = state.submitted_at or utc_now().isoformat()
        await self._repo.put_query_execution_state(
            tenant_id, query_id, state.to_dict()
        )
        metrics.increment(
            "aether_query_execution_total",
            labels={"tenant_id": tenant_id, "lane": lane, "status": status},
        )
        if total_latency_ms is not None:
            metrics.observe(
                "aether_query_total_latency_ms",
                total_latency_ms,
                labels={"tenant_id": tenant_id, "lane": lane},
            )
        return state

    async def get_query_execution_state(
        self, tenant_id: str, query_id: str
    ) -> Optional[dict]:
        return await self._repo.get_query_execution_state(tenant_id, query_id)

    # ── background job state ─────────────────────────────────────────────

    async def update_background_job(
        self,
        tenant_id: str,
        job_id: str,
        job_type: str,
        status: str,
        *,
        progress_percent: Optional[float] = None,
        started_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        records_processed: Optional[int] = None,
        records_total: Optional[int] = None,
        current_stage: Optional[str] = None,
        user_visible: bool = True,
        can_retry: bool = True,
        can_cancel: bool = False,
        failure_reason: Optional[str] = None,
        degraded_surface_ids: Optional[list[str]] = None,
    ) -> BackgroundJobState:
        state = BackgroundJobState(
            tenant_id=tenant_id,
            job_id=job_id,
            job_type=job_type,
            status=status,
            progress_percent=progress_percent,
            started_at=started_at,
            updated_at=updated_at or utc_now().isoformat(),
            completed_at=completed_at,
            records_processed=records_processed,
            records_total=records_total,
            current_stage=current_stage,
            user_visible=user_visible,
            can_retry=can_retry,
            can_cancel=can_cancel,
            failure_reason=failure_reason,
            degraded_surface_ids=degraded_surface_ids or [],
            updated_ts=utc_now().isoformat(),
        )
        existing = await self._repo.get_background_job(tenant_id, job_id)
        if existing:
            state.started_at = existing.get("started_at") or state.started_at
            state.completed_at = completed_at or existing.get("completed_at")
        if state.started_at is None:
            state.started_at = state.started_at or utc_now().isoformat()
        await self._repo.put_background_job(
            tenant_id, job_id, state.to_dict()
        )
        await self._publish_job_update(tenant_id, job_id)
        return state

    async def get_background_job(self, tenant_id: str, job_id: str) -> Optional[dict]:
        return await self._repo.get_background_job(tenant_id, job_id)

    async def list_background_jobs(self, tenant_id: str) -> list[dict]:
        return await self._repo.list_background_jobs(tenant_id)

    # ── surface readiness (derived) ──────────────────────────────────────

    async def derive_surface_readiness(
        self, tenant_id: str, surface: str
    ) -> SurfaceReadiness:
        """Derive SurfaceReadiness from milestone + projection + sync state.

        Surface Ready = required data exists + contracts validate +
        read model is current + user-visible state exists +
        p95 latency is within budget + no blocking errors.
        """
        milestone = await self._load_milestone(tenant_id)
        required = _SURFACE_MILESTONES.get(surface, [])
        blocking: list[str] = []
        degraded: list[str] = []
        data_state = "missing"
        user_visible_state = "not_started"
        performance_state = "unknown"

        # data state
        if not required:
            data_state = "ready"
            user_visible_state = "ready"
        elif all(
            getattr(milestone, f, None) for f in required
        ):
            data_state = "ready"
            user_visible_state = "ready"
        elif any(getattr(milestone, f) for f in required):
            data_state = "partial"
            user_visible_state = "partially_ready"

        # blocking reasons
        if milestone.status == "blocked":
            blocking.append("activation blocked")
        if milestone.status == "degraded":
            degraded.append("activation degraded")

        # performance state
        budgets = await self._repo.get_performance_budgets()
        for b in budgets:
            if b.get("surface") != surface:
                continue
            target = b.get("target_ms")
            if target is None:
                continue
            sev = b.get("severity", "info")
            if sev in ("degrade", "block"):
                performance_state = "degraded"
                degraded.append(f"budget {b.get('id')} exceeds target {target}ms")

        return SurfaceReadiness(
            tenant_id=tenant_id,
            surface=surface,
            data_state=data_state,
            performance_state=performance_state,
            user_visible_state=user_visible_state,
            blocking_reasons=blocking,
            degraded_reasons=degraded,
            required_milestones=required,
            updated_at=utc_now().isoformat(),
        )

    async def get_surface_readiness(self, tenant_id: str, surface: str) -> SurfaceReadiness:
        existing = await self._repo.get_surface_readiness(tenant_id, surface)
        if existing:
            # Same stripped-``tenant_id`` payload as ``_load_milestone``.
            return SurfaceReadiness(**{
                **{k: v for k, v in existing.items() if k != "id"},
                "tenant_id": tenant_id,
            })
        readiness = await self.derive_surface_readiness(tenant_id, surface)
        await self._repo.put_surface_readiness(
            tenant_id, surface, readiness.to_dict()
        )
        return readiness

    async def list_surface_readiness(self, tenant_id: str) -> list[dict]:
        rows = await self._repo.list_surface_readiness(tenant_id)
        out: list[dict] = []
        for r in rows:
            out.append({k: v for k, v in r.items() if k != "id"})
        if not out:
            surfaces = list(_SURFACE_MILESTONES.keys())
            for s in surfaces:
                readiness = await self.derive_surface_readiness(tenant_id, s)
                out.append(readiness.to_dict())
        return out

    # ── full responsiveness envelope ─────────────────────────────────────

    async def get_responsiveness(self, tenant_id: str, environment: str = "local") -> dict:
        milestone = await self._load_milestone(tenant_id)
        surfaces = await self.list_surface_readiness(tenant_id)
        heartbeats = await self.get_heartbeat_states(tenant_id)
        provider_syncs = await self.get_provider_sync_states(tenant_id)
        graph_hydration = await self._repo.get_graph_hydration_state(tenant_id, "current")
        projections = await self.get_projection_states(tenant_id)
        lens_projections = await self.list_lens_projection_states(tenant_id)
        timeline_projection = None
        jobs = await self.list_background_jobs(tenant_id)

        # timeline: pick the most recent scope hash for this tenant
        timeline_rows = await self._repo.list_timeline_projection_states_for_tenant(tenant_id)
        if timeline_rows:
            # choose the row with the latest updated_at
            timeline_projection = max(
                timeline_rows, key=lambda r: r.get("updated_at", "")
            )

        return ResponsivenessEnvelope(
            tenant_id=tenant_id,
            environment=environment,
            activation_milestone=milestone.to_dict() if milestone else None,
            surfaces=surfaces,
            sdk_heartbeats=heartbeats,
            provider_sync_states=provider_syncs,
            graph_hydration=graph_hydration,
            projections=projections,
            lens_projections=lens_projections,
            timeline_projection=timeline_projection,
            background_jobs=jobs,
        ).to_dict()

    # ── performance budgets (management) ────────────────────────────────

    async def seed_performance_budgets(self) -> list[dict]:
        """Seed the canonical budget set from the contract YAML shape.

        Called once at startup (idempotent: put overwrites by id).
        """
        budgets = [
            PerformanceBudget(
                id="frontend_lcp_p75",
                version="1",
                surface="frontend",
                metric="lcp_ms",
                target_ms=2500,
                percentile="p75",
                severity="degrade",
                applies_to=["frontend"],
            ).to_dict(),
            PerformanceBudget(
                id="frontend_inp_p75",
                version="1",
                surface="frontend",
                metric="inp_ms",
                target_ms=200,
                percentile="p75",
                severity="degrade",
                applies_to=["frontend"],
            ).to_dict(),
            PerformanceBudget(
                id="interaction_button_p95",
                version="1",
                surface="interaction",
                interaction="button_click",
                metric="latency_ms",
                target_ms=100,
                percentile="p95",
                severity="degrade",
                applies_to=["frontend"],
            ).to_dict(),
            PerformanceBudget(
                id="sdk_first_heartbeat_visible_p95",
                version="1",
                surface="sdk",
                metric="latency_ms",
                target_ms=15000,
                percentile="p95",
                severity="block",
                applies_to=["sdk"],
            ).to_dict(),
            PerformanceBudget(
                id="provider_oauth_connected_p95",
                version="1",
                surface="provider",
                metric="latency_ms",
                target_ms=2000,
                percentile="p95",
                severity="degrade",
                applies_to=["provider"],
            ).to_dict(),
            PerformanceBudget(
                id="graph_first_stub_p95",
                version="1",
                surface="graph",
                metric="latency_ms",
                target_ms=30000,
                percentile="p95",
                severity="degrade",
                applies_to=["graph"],
            ).to_dict(),
            PerformanceBudget(
                id="lens_toggle_visual_p95",
                version="1",
                surface="lenses",
                interaction="lens_toggle",
                metric="latency_ms",
                target_ms=200,
                percentile="p95",
                severity="degrade",
                applies_to=["lens"],
            ).to_dict(),
            PerformanceBudget(
                id="timeline_pan_p95",
                version="1",
                surface="timeline",
                interaction="pan",
                metric="latency_ms",
                target_ms=200,
                percentile="p95",
                severity="degrade",
                applies_to=["timeline"],
            ).to_dict(),
            PerformanceBudget(
                id="query_cached_p95",
                version="1",
                surface="query",
                lane="cached",
                metric="latency_ms",
                target_ms=750,
                percentile="p95",
                severity="degrade",
                applies_to=["query"],
            ).to_dict(),
        ]
        return await self._repo.put_performance_budgets(budgets)

    async def get_performance_budgets(self) -> list[dict]:
        return await self._repo.get_performance_budgets()

    # ── measurements (external recording) ───────────────────────────────

    async def record_measurement(self, tenant_id: str, measurement: dict) -> dict:
        mid = measurement.get("id") or str(uuid.uuid4())
        measurement["id"] = mid
        await self._repo.put_measurement(tenant_id, mid, measurement)
        return measurement

    # ── internal helpers ─────────────────────────────────────────────────

    async def _load_milestone(self, tenant_id: str) -> ActivationMilestone:
        row = await self._repo.get_activation_milestone(tenant_id)
        if row:
            # ``ResponsivenessRepository._get`` strips the row-level metadata
            # keys (``tenant_id`` included) from the stored payload, so the
            # tenant the record is keyed by must be passed back explicitly —
            # without it every milestone read after the first write raised
            # ``missing 1 required positional argument: 'tenant_id'``.
            return ActivationMilestone(**{**row, "tenant_id": tenant_id})
        return ActivationMilestone(tenant_id=tenant_id)

    async def _publish_activation_update(self, tenant_id: str) -> None:
        try:
            from shared.events.events import Event, Topic
            from dependencies.providers import get_producer

            event = Event(
                topic=Topic.TENANT_ACTIVATION_UPDATED,
                tenant_id=tenant_id,
                source_service="responsiveness",
                correlation_id="",
                payload={},
            )
            await get_producer().publish(event)
        except Exception as exc:
            logger.warning(f"responsiveness activation publish failed: {exc}")

    async def _publish_provider_update(
        self, tenant_id: str, provider_id: str
    ) -> None:
        try:
            from shared.events.events import Event, Topic
            from dependencies.providers import get_producer

            event = Event(
                topic=Topic.TENANT_SURFACE_READINESS_UPDATED,
                tenant_id=tenant_id,
                source_service="responsiveness",
                correlation_id="",
                payload={"provider_id": provider_id},
            )
            await get_producer().publish(event)
        except Exception as exc:
            logger.warning(f"responsiveness provider publish failed: {exc}")

    async def _publish_lens_update(
        self, tenant_id: str, lens_id: str, graph_version: str, scope_hash: str
    ) -> None:
        try:
            from shared.events.events import Event, Topic
            from dependencies.providers import get_producer

            event = Event(
                topic=Topic.LENS_PROJECTION_UPDATED,
                tenant_id=tenant_id,
                source_service="responsiveness",
                correlation_id="",
                payload={"lens_id": lens_id, "graph_version": graph_version, "scope_hash": scope_hash},
            )
            await get_producer().publish(event)
        except Exception as exc:
            logger.warning(f"responsiveness lens publish failed: {exc}")

    async def _publish_job_update(
        self, tenant_id: str, job_id: str
    ) -> None:
        try:
            from shared.events.events import Event, Topic
            from dependencies.providers import get_producer

            event = Event(
                topic=Topic.BACKGROUND_JOB_UPDATED,
                tenant_id=tenant_id,
                source_service="responsiveness",
                correlation_id="",
                payload={"job_id": job_id},
            )
            await get_producer().publish(event)
        except Exception as exc:
            logger.warning(f"responsiveness job publish failed: {exc}")


# module-level singleton, matching the pattern used by activation/sdk_health/jobs
_service: Optional[ResponsivenessService] = None


def get_responsiveness_service() -> ResponsivenessService:
    global _service
    if _service is None:
        _service = ResponsivenessService()
    return _service
