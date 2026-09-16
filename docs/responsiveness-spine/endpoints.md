---
title: Endpoints
slug: responsiveness-spine/endpoints
section: architecture
visibility: P
audience: [dev-senior, architect]
status: beta
---

# Responsiveness & Time-to-Value API Endpoints

> Mirrors `services/backend/services/responsiveness/routes.py` exactly. All endpoints are single-tenant (tenant from `request.state.tenant`), require `READ` permission, and return an `APIResponse(data=...)` envelope.

---

## Base URL

`GET /v1/responsiveness` and sub-paths.

All query parameters are optional with documented defaults. Path parameters are validated with regex patterns where noted.

---

## 1. GET /v1/responsiveness (full envelope)

**Description:** Returns the complete tenant responsiveness envelope — activation milestone, surface readiness matrix, SDK heartbeats, provider sync states, graph hydration, projections, lens projections, timeline projection, and background jobs in one call.

**Auth:** Bearer API key with `READ` permission.

**Query params:** None.

**Response shape:** `ResponsivenessEnvelope.to_dict()`

```json
{
  "tenant_id": "t_01J...",
  "environment": "local",
  "activation_milestone": {
    "tenant_id": "t_01J...",
    "environment": "local",
    "tenant_created_at": "2026-09-13T10:00:00+00:00",
    "sdk_initialized_at": "2026-09-13T10:05:00+00:00",
    "first_event_received_at": "2026-09-13T10:05:01+00:00",
    "first_event_acked_at": "2026-09-13T10:05:01.500+00:00",
    "first_heartbeat_visible_at": "2026-09-13T10:05:02+00:00",
    "first_graph_stub_visible_at": "2026-09-13T10:06:00+00:00",
    "first_value_kind": "sdk_heartbeat",
    "time_to_first_heartbeat_ms": 5200.0,
    "time_to_first_graph_stub_ms": 60000.0,
    "time_to_first_value_ms": 5200.0,
    "status": "partial_value",
    "updated_at": "2026-09-13T10:06:00+00:00"
  },
  "surfaces": [
    {
      "tenant_id": "t_01J...",
      "surface": "dashboard",
      "data_state": "ready",
      "performance_state": "within_budget",
      "user_visible_state": "ready",
      "last_updated_at": "2026-09-13T10:06:00+00:00",
      "freshness_ms": 200,
      "blocking_reasons": [],
      "degraded_reasons": [],
      "required_milestones": ["first_heartbeat_visible_at", "first_graph_stub_visible_at"],
      "updated_at": "2026-09-13T10:06:00+00:00"
    }
  ],
  "sdk_heartbeats": [
    {
      "tenant_id": "t_01J...",
      "source_id": "web_abc123",
      "sdk_id": "ios_v2.1.0",
      "environment": "production",
      "status": "healthy",
      "first_seen_at": "2026-09-13T10:05:01+00:00",
      "last_seen_at": "2026-09-13T10:10:00+00:00",
      "event_count": 150,
      "valid_event_count": 148,
      "invalid_event_count": 2,
      "last_event_type": "page_view",
      "last_error": null,
      "schema_version": "2.1",
      "ingestion_latency_ms": 450.0,
      "visible_in_dashboard_at": "2026-09-13T10:05:02+00:00",
      "updated_at": "2026-09-13T10:10:00+00:00"
    }
  ],
  "provider_sync_states": [
    {
      "tenant_id": "t_01J...",
      "provider_id": "hubspot",
      "connection_id": "conn_01J...",
      "status": "sampling",
      "connected_at": "2026-09-13T10:07:00+00:00",
      "first_metadata_at": "2026-09-13T10:07:01+00:00",
      "first_sample_record_at": "2026-09-13T10:07:30+00:00",
      "records_discovered": 5000,
      "records_sampled": 200,
      "records_synced": 0,
      "progress_percent": 2.0,
      "rate_limited": false,
      "permission_issues": [],
      "degraded_reasons": [],
      "blocking_reasons": [],
      "updated_at": "2026-09-13T10:07:30+00:00"
    }
  ],
  "graph_hydration": {
    "tenant_id": "t_01J...",
    "graph_version": "current",
    "status": "hydrating_surfaces",
    "raw_events_count": 150,
    "normalized_records_count": 148,
    "entity_count": 30,
    "edge_count": 45,
    "projected_entity_count": 30,
    "projected_edge_count": 45,
    "first_node_created_at": "2026-09-13T10:05:30+00:00",
    "first_edge_created_at": "2026-09-13T10:05:45+00:00",
    "first_projection_created_at": "2026-09-13T10:06:00+00:00",
    "first_stub_visible_at": "2026-09-13T10:06:00+00:00",
    "hydration_progress_percent": null,
    "stale_projection_count": 0,
    "failed_projection_count": 0,
    "degraded_reasons": [],
    "blocking_reasons": [],
    "updated_at": "2026-09-13T10:06:00+00:00"
  },
  "projections": [
    {
      "tenant_id": "t_01J...",
      "projection_id": "profile_360",
      "projection_type": "profile_360",
      "graph_version": "current",
      "status": "ready",
      "freshness_ms": 5000,
      "last_built_at": "2026-09-13T10:00:00+00:00",
      "last_refreshed_at": "2026-09-13T10:10:00+00:00",
      "last_accessed_at": "2026-09-13T10:10:00+00:00",
      "build_duration_ms": 1200.0,
      "p95_read_latency_ms": 350.0,
      "dependency_versions": {"graph": "current"},
      "degraded_reasons": [],
      "failure_reason": null,
      "updated_at": "2026-09-13T10:10:00+00:00"
    }
  ],
  "lens_projections": [
    {
      "tenant_id": "t_01J...",
      "lens_id": "customer_journey_lens",
      "graph_version": "current",
      "entity_scope": "customer",
      "time_window": "30d",
      "grain": "day",
      "permission_scope": "tenant",
      "status": "ready",
      "visual_toggle_latency_ms": 150.0,
      "cached_result_latency_ms": 400.0,
      "first_result_latency_ms": 1200.0,
      "full_hydration_latency_ms": 8000.0,
      "result_count": 15000,
      "delta_count": 200,
      "last_built_at": "2026-09-13T10:00:00+00:00",
      "degraded_reasons": [],
      "updated_at": "2026-09-13T10:10:00+00:00"
    }
  ],
  "timeline_projection": {
    "tenant_id": "t_01J...",
    "graph_version": "current",
    "entity_scope": "customer",
    "available_grains": ["minute", "hour", "day", "week", "month"],
    "status": "ready",
    "first_render_latency_ms": 900.0,
    "pan_latency_ms": 180.0,
    "zoom_latency_ms": 250.0,
    "grain_change_latency_ms": 600.0,
    "last_built_at": "2026-09-13T10:00:00+00:00",
    "freshness_ms": 5000,
    "updated_at": "2026-09-13T10:10:00+00:00"
  },
  "background_jobs": [
    {
      "tenant_id": "t_01J...",
      "job_id": "job_01J...",
      "job_type": "graph_projection_rebuild",
      "status": "running",
      "progress_percent": 45.0,
      "started_at": "2026-09-13T10:00:00+00:00",
      "updated_at": "2026-09-13T10:10:00+00:00",
      "completed_at": null,
      "records_processed": 4500,
      "records_total": 10000,
      "current_stage": "creating_edges",
      "user_visible": true,
      "can_retry": true,
      "can_cancel": false,
      "failure_reason": null,
      "degraded_surface_ids": [],
      "updated_ts": "2026-09-13T10:10:00+00:00"
    }
  ],
  "updated_at": "2026-09-13T10:10:00+00:00"
}
```

**Empty state (no data yet):**
```json
{
  "tenant_id": "t_01J...",
  "environment": "local",
  "activation_milestone": null,
  "surfaces": [],
  "sdk_heartbeats": [],
  "provider_sync_states": [],
  "graph_hydration": null,
  "projections": [],
  "lens_projections": [],
  "timeline_projection": null,
  "background_jobs": [],
  "updated_at": "2026-09-13T10:00:00+00:00"
}
```

**Error cases:**
- `401` — missing or invalid API key
- `403` — tenant lacks `READ` permission

---

## 2. GET /v1/responsiveness/activation-milestones

**Description:** Returns the activation milestone for the tenant — the timeline of first-event-ack, first-heartbeat-visible, first-graph-stub-visible, and first-value moments.

**Auth:** Bearer API key with `READ` permission.

**Query params:** None.

**Response shape:** `ActivationMilestone.to_dict()` or `{}` if no milestone yet.

```json
{
  "tenant_id": "t_01J...",
  "environment": "local",
  "tenant_created_at": "2026-09-13T10:00:00+00:00",
  "sdk_key_created_at": "2026-09-13T10:02:00+00:00",
  "sdk_initialized_at": "2026-09-13T10:05:00+00:00",
  "first_event_received_at": "2026-09-13T10:05:01+00:00",
  "first_event_acked_at": "2026-09-13T10:05:01.500+00:00",
  "first_heartbeat_visible_at": "2026-09-13T10:05:02+00:00",
  "first_valid_event_at": "2026-09-13T10:05:01+00:00",
  "first_provider_connected_at": "2026-09-13T10:07:00+00:00",
  "first_provider_sample_at": "2026-09-13T10:07:30+00:00",
  "first_graph_node_at": "2026-09-13T10:05:30+00:00",
  "first_graph_edge_at": "2026-09-13T10:05:45+00:00",
  "first_graph_stub_visible_at": "2026-09-13T10:06:00+00:00",
  "first_lens_ready_at": null,
  "first_timeline_ready_at": null,
  "first_360_ready_at": null,
  "first_recommendation_ready_at": null,
  "time_to_first_heartbeat_ms": 5200.0,
  "time_to_first_graph_stub_ms": 60000.0,
  "time_to_first_value_ms": 5200.0,
  "first_value_kind": "sdk_heartbeat",
  "status": "partial_value",
  "updated_at": "2026-09-13T10:06:00+00:00"
}
```

**Status ladder:**
- `not_started` — no events received
- `activating` — events flowing, milestone timers running
- `partial_value` — first heartbeat visible (SDK sees value), but not full value
- `ready` — first-value moment recorded (graph node, lens ready, 360 ready, etc.)
- `degraded` — activation degraded
- `blocked` — activation blocked

**Empty state:**
```json
{}
```

---

## 3. GET /v1/responsiveness/surface-readiness

**Description:** Returns readiness state for all surfaces the tenant has.

**Auth:** Bearer API key with `READ` permission.

**Query params:** None.

**Response shape:** `list[SurfaceReadiness.to_dict()]`

```json
[
  {
    "tenant_id": "t_01J...",
    "surface": "dashboard",
    "data_state": "ready",
    "performance_state": "within_budget",
    "user_visible_state": "ready",
    "last_updated_at": "2026-09-13T10:06:00+00:00",
    "freshness_ms": 200,
    "blocking_reasons": [],
    "degraded_reasons": [],
    "required_milestones": ["first_heartbeat_visible_at", "first_graph_stub_visible_at"],
    "updated_at": "2026-09-13T10:06:00+00:00"
  },
  {
    "tenant_id": "t_01J...",
    "surface": "graph",
    "data_state": "partial",
    "performance_state": "unknown",
    "user_visible_state": "hydrating",
    "last_updated_at": "2026-09-13T10:06:00+00:00",
    "freshness_ms": null,
    "blocking_reasons": [],
    "degraded_reasons": [],
    "required_milestones": ["first_graph_node_at", "first_graph_edge_at", "first_graph_stub_visible_at"],
    "updated_at": "2026-09-13T10:06:00+00:00"
  },
  {
    "tenant_id": "t_01J...",
    "surface": "timeline",
    "data_state": "missing",
    "performance_state": "unknown",
    "user_visible_state": "not_started",
    "last_updated_at": null,
    "freshness_ms": null,
    "blocking_reasons": ["activation blocked"],
    "degraded_reasons": [],
    "required_milestones": ["first_timeline_ready_at"],
    "updated_at": "2026-09-13T10:06:00+00:00"
  }
]
```

**Surfaces included:** `dashboard`, `graph`, `timeline`, `profile_360`, `campaign_360`, `journey_360`, `communications_360`, `agent_360`, `execution_360`, `value`, `signals`, `syndicates`, `lenses`, `providers`, `sdk_fleet` (15 surfaces total — see `SURFACE_NAMES` in models.py).

---

## 4. GET /v1/responsiveness/surface-readiness/{surface}

**Description:** Returns readiness state for a single surface.

**Auth:** Bearer API key with `READ` permission.

**Path params:**
- `surface` — string, pattern `^[a-z][a-z0-9_]*$`

**Query params:** None.

**Response shape:** `SurfaceReadiness.to_dict()` or `null` if surface not in `SURFACE_NAMES`.

```json
{
  "tenant_id": "t_01J...",
  "surface": "dashboard",
  "data_state": "ready",
  "performance_state": "within_budget",
  "user_visible_state": "ready",
  "last_updated_at": "2026-09-13T10:06:00+00:00",
  "freshness_ms": 200,
  "blocking_reasons": [],
  "degraded_reasons": [],
  "required_milestones": ["first_heartbeat_visible_at", "first_graph_stub_visible_at"],
  "updated_at": "2026-09-13T10:06:00+00:00"
}
```

**Invalid surface (not in SURFACE_NAMES):**
```json
null
```
(Returns `APIResponse(data=null)` — the endpoint does not 404 for unknown surfaces.)

**Error cases:**
- `400` — surface path parameter fails regex `^[a-z][a-z0-9_]*$`
- `401` — missing or invalid API key
- `403` — tenant lacks `READ` permission

---

## 5. GET /v1/responsiveness/sdk-heartbeats

**Description:** Returns SDK heartbeat states for all sources in the tenant.

**Auth:** Bearer API key with `READ` permission.

**Query params:** None.

**Response shape:** `list[HeartbeatState.to_dict()]`

```json
[
  {
    "tenant_id": "t_01J...",
    "source_id": "web_abc123",
    "sdk_id": "web_v3.2.0",
    "environment": "production",
    "status": "healthy",
    "first_seen_at": "2026-09-13T10:05:01+00:00",
    "last_seen_at": "2026-09-13T10:10:00+00:00",
    "event_count": 150,
    "valid_event_count": 148,
    "invalid_event_count": 2,
    "last_event_type": "page_view",
    "last_error": null,
    "schema_version": "3.2",
    "ingestion_latency_ms": 450.0,
    "visible_in_dashboard_at": "2026-09-13T10:05:02+00:00",
    "updated_at": "2026-09-13T10:10:00+00:00"
  }
]
```

**HeartbeatStatus ladder:** `not_seen` → `receiving` → `validating` → `healthy` → `degraded` → `blocked`.

**Empty state:** `[]`

---

## 6. GET /v1/responsiveness/provider-sync-states

**Description:** Returns provider sync states for all providers connected to the tenant.

**Auth:** Bearer API key with `READ` permission.

**Query params:** None.

**Response shape:** `list[ProviderSyncState.to_dict()]`

```json
[
  {
    "tenant_id": "t_01J...",
    "provider_id": "hubspot",
    "connection_id": "conn_01J...",
    "status": "sampling",
    "connected_at": "2026-09-13T10:07:00+00:00",
    "first_metadata_at": "2026-09-13T10:07:01+00:00",
    "first_sample_record_at": "2026-09-13T10:07:30+00:00",
    "first_graph_hydration_at": null,
    "last_sync_started_at": "2026-09-13T10:07:00+00:00",
    "last_sync_completed_at": null,
    "next_sync_at": "2026-09-13T10:08:00+00:00",
    "records_discovered": 5000,
    "records_sampled": 200,
    "records_synced": 0,
    "records_failed": 0,
    "rate_limited": false,
    "permission_issues": [],
    "degraded_reasons": [],
    "blocking_reasons": [],
    "progress_percent": 2.0,
    "visible_status_updated_at": "2026-09-13T10:07:30+00:00",
    "updated_at": "2026-09-13T10:07:30+00:00"
  }
]
```

**ProviderSyncStatus ladder:** `not_connected` → `connected` → `discovering` → `sampling` → `syncing` → `hydrating_graph` → `partially_ready` → `ready` → `degraded` → `blocked`.

**Empty state:** `[]`

---

## 7. GET /v1/responsiveness/graph-hydration

**Description:** Returns graph hydration state for a specific graph version.

**Auth:** Bearer API key with `READ` permission.

**Query params:**
- `graph_version` — string, default `"current"`. Identifies the graph version (e.g. `"current"`, `"v2026-09-13"`).

**Response shape:** `GraphHydrationState.to_dict()` or `{}` if no state yet.

```json
{
  "tenant_id": "t_01J...",
  "graph_version": "current",
  "status": "hydrating_surfaces",
  "raw_events_count": 150,
  "normalized_records_count": 148,
  "entity_count": 30,
  "edge_count": 45,
  "projected_entity_count": 30,
  "projected_edge_count": 45,
  "first_node_created_at": "2026-09-13T10:05:30+00:00",
  "first_edge_created_at": "2026-09-13T10:05:45+00:00",
  "first_projection_created_at": "2026-09-13T10:06:00+00:00",
  "first_stub_visible_at": "2026-09-13T10:06:00+00:00",
  "hydration_progress_percent": null,
  "stale_projection_count": 0,
  "failed_projection_count": 0,
  "degraded_reasons": [],
  "blocking_reasons": [],
  "updated_at": "2026-09-13T10:06:00+00:00"
}
```

**GraphHydrationStatus ladder:** `not_started` → `receiving` → `normalizing` → `resolving_entities` → `creating_edges` → `building_projections` → `hydrating_surfaces` → `partially_ready` → `ready` → `degraded` → `blocked`.

**Empty state:**
```json
{}
```

---

## 8. GET /v1/responsiveness/projections

**Description:** Returns projection states for all projections in the tenant.

**Auth:** Bearer API key with `READ` permission.

**Query params:** None.

**Response shape:** `list[ProjectionState.to_dict()]`

```json
[
  {
    "tenant_id": "t_01J...",
    "projection_id": "profile_360",
    "projection_type": "profile_360",
    "graph_version": "current",
    "source_version": "v2.1",
    "status": "ready",
    "freshness_ms": 5000,
    "last_built_at": "2026-09-13T10:00:00+00:00",
    "last_refreshed_at": "2026-09-13T10:10:00+00:00",
    "last_accessed_at": "2026-09-13T10:10:00+00:00",
    "build_duration_ms": 1200.0,
    "p95_read_latency_ms": 350.0,
    "dependency_versions": {"graph": "current"},
    "degraded_reasons": [],
    "failure_reason": null,
    "updated_at": "2026-09-13T10:10:00+00:00"
  }
]
```

**ProjectionStatus ladder:** `missing` → `building` → `ready` → `stale` → `refreshing` → `degraded` → `failed`.

**Empty state:** `[]`

---

## 9. GET /v1/responsiveness/lens-projections

**Description:** Returns lens projection states for all lenses in the tenant.

**Auth:** Bearer API key with `READ` permission.

**Query params:** None.

**Response shape:** `list[LensProjectionState.to_dict()]`

```json
[
  {
    "tenant_id": "t_01J...",
    "lens_id": "customer_journey_lens",
    "graph_version": "current",
    "entity_scope": "customer",
    "time_window": "30d",
    "grain": "day",
    "permission_scope": "tenant",
    "status": "ready",
    "visual_toggle_latency_ms": 150.0,
    "cached_result_latency_ms": 400.0,
    "first_result_latency_ms": 1200.0,
    "full_hydration_latency_ms": 8000.0,
    "result_count": 15000,
    "delta_count": 200,
    "last_built_at": "2026-09-13T10:00:00+00:00",
    "degraded_reasons": [],
    "updated_at": "2026-09-13T10:10:00+00:00"
  }
]
```

**LensProjectionStatus ladder:** `not_available` → `cached` → `building` → `partial` → `ready` → `stale` → `degraded` → `failed`.

**Empty state:** `[]`

---

## 10. GET /v1/responsiveness/timeline-projection

**Description:** Returns timeline projection state for a specific scope hash.

**Auth:** Bearer API key with `READ` permission.

**Query params:**
- `scope_hash` — string, default `"default"`. Timeline scope identifier (format: `entity_scope:grain:window`).

**Response shape:** `TimelineProjectionState.to_dict()` or `{}` if no state yet.

```json
{
  "tenant_id": "t_01J...",
  "graph_version": "current",
  "entity_scope": "customer",
  "available_grains": ["minute", "hour", "day", "week", "month"],
  "status": "ready",
  "first_render_latency_ms": 900.0,
  "pan_latency_ms": 180.0,
  "zoom_latency_ms": 250.0,
  "grain_change_latency_ms": 600.0,
  "last_built_at": "2026-09-13T10:00:00+00:00",
  "freshness_ms": 5000,
  "updated_at": "2026-09-13T10:10:00+00:00"
}
```

**TimelineStatus ladder:** `missing` → `building` → `partial` → `ready` → `stale` → `degraded` → `failed`.

**Empty state:**
```json
{}
```

---

## 11. GET /v1/responsiveness/background-jobs

**Description:** Returns background job states for all jobs in the tenant.

**Auth:** Bearer API key with `READ` permission.

**Query params:** None.

**Response shape:** `list[BackgroundJobState.to_dict()]`

```json
[
  {
    "tenant_id": "t_01J...",
    "job_id": "job_01J...",
    "job_type": "graph_projection_rebuild",
    "status": "running",
    "progress_percent": 45.0,
    "started_at": "2026-09-13T10:00:00+00:00",
    "updated_at": "2026-09-13T10:10:00+00:00",
    "completed_at": null,
    "records_processed": 4500,
    "records_total": 10000,
    "current_stage": "creating_edges",
    "user_visible": true,
    "can_retry": true,
    "can_cancel": false,
    "failure_reason": null,
    "degraded_surface_ids": [],
    "updated_ts": "2026-09-13T10:10:00+00:00"
  }
]
```

**JobStatus ladder:** `queued` → `running` → `partial` → `complete` → `failed` → `retrying` → `cancelled`.

**Empty state:** `[]`

---

## 12. GET /v1/responsiveness/measurements

**Description:** Returns recorded responsiveness measurements for the tenant (latency measurements, budget violation records, interaction measurements).

**Auth:** Bearer API key with `READ` permission.

**Query params:**
- `limit` — integer, default `200`, range `1..1000`.

**Response shape:** `list[dict]` — each dict is a `ResponsivenessMeasurement`-shaped record.

```json
[
  {
    "id": "meas_01J...",
    "tenant_id": "t_01J...",
    "surface": "projection",
    "interaction": "rebuild:profile_360",
    "metric": "rebuild_intent",
    "value_ms": null,
    "value": 1,
    "percentile_window": null,
    "status": "queued",
    "measured_at": "2026-09-13T10:10:00+00:00",
    "trace_id": null,
    "span_id": null,
    "release_version": null,
    "environment": "local"
  }
]
```

**Empty state:** `[]`

---

## 13. GET /v1/responsiveness/performance-budgets

**Description:** Returns the seeded performance budget definitions. These are the canonical targets the spine checks against.

**Auth:** Bearer API key with `READ` permission.

**Query params:** None.

**Response shape:** `list[dict]` — each dict is a `PerformanceBudget.to_dict()`.

```json
[
  {
    "id": "frontend_lcp_p75",
    "version": "1",
    "surface": "frontend",
    "interaction": null,
    "metric": "lcp_ms",
    "target_ms": 2500,
    "target_value": null,
    "percentile": "p75",
    "severity": "degrade",
    "applies_to": ["frontend"]
  },
  {
    "id": "sdk_first_heartbeat_visible_p95",
    "version": "1",
    "surface": "sdk",
    "interaction": null,
    "metric": "latency_ms",
    "target_ms": 15000,
    "target_value": null,
    "percentile": "p95",
    "severity": "block",
    "applies_to": ["sdk"]
  }
]
```

**Empty state:** `[]` (budgets not yet seeded — happens once at service startup).

---

## 14. GET /v1/responsiveness/first-value-kinds

**Description:** Returns the sorted list of valid first-value kinds. This is a read-only contract aid — the kinds that can be recorded as a tenant's `first_value_kind`.

**Auth:** Bearer API key with `READ` permission.

**Query params:** None.

**Response shape:** `list[str]`

```json
[
  "campaign_360",
  "graph_edge",
  "graph_node",
  "journey_360",
  "lens",
  "profile_360",
  "provider_sample",
  "recommendation",
  "sdk_heartbeat",
  "timeline",
  "live_event"
]
```

**Note:** `live_event` appears in the sorted list but is not in the `FIRST_VALUE_KINDS` frozenset in models.py — this endpoint returns `sorted(FIRST_VALUE_KINDS)` so it matches the frozenset exactly.

---

## 15. POST /v1/responsiveness/projections/{projection_id}/rebuild

**Description:** Stub — trigger an async projection rebuild. Records a measurement and returns the intent. Real implementation (phase 5) enqueues a `projection_rebuild_job` via the job center and returns the job id.

**Auth:** Bearer API key with `READ` permission.

**Path params:**
- `projection_id` — string, `1..200` chars.

**Query params:** None.

**Response shape:**

```json
{
  "projection_id": "profile_360",
  "tenant_id": "t_01J...",
  "status": "queued",
  "message": "projection rebuild not yet wired (phase 5)"
}
```

**Side effect:** Records a `ResponsivenessMeasurement`:
```json
{
  "surface": "projection",
  "interaction": "rebuild:profile_360",
  "metric": "rebuild_intent",
  "value": 1,
  "status": "queued",
  "measured_at": "<utc_now>",
  "environment": "local"
}
```

**Error cases:**
- `400` — projection_id fails validation (empty, >200 chars)
- `401` — missing or invalid API key
- `403` — tenant lacks `READ` permission

---

## 16. POST /v1/responsiveness/providers/{provider_id}/retry

**Description:** Stub — retry a provider sync. Records a measurement and returns the intent. Real implementation (phase 3) re-runs the provider sample/pull path and returns the operation id.

**Auth:** Bearer API key with `READ` permission.

**Path params:**
- `provider_id` — string, `1..200` chars.

**Query params:** None.

**Response shape:**

```json
{
  "provider_id": "hubspot",
  "tenant_id": "t_01J...",
  "status": "queued",
  "message": "provider retry not yet wired (phase 3)"
}
```

**Side effect:** Records a `ResponsivenessMeasurement`:
```json
{
  "surface": "provider",
  "interaction": "retry:hubspot",
  "metric": "retry_intent",
  "value": 1,
  "status": "queued",
  "measured_at": "<utc_now>",
  "environment": "local"
}
```

**Error cases:**
- `400` — provider_id fails validation (empty, >200 chars)
- `401` — missing or invalid API key
- `403` — tenant lacks `READ` permission

---

## Common error patterns

| Status | Cause |
|--------|-------|
| `401` | Missing, expired, or invalid Bearer API key |
| `403` | API key lacks `READ` permission for this tenant |
| `400` | Path parameter validation failure (surface regex, projection_id/provider_id length) |
| `503` | Dependent service unavailable — never returned by responsiveness endpoints themselves (they degrade gracefully), but possible if the APIResponse serialization fails |

**Graceful degradation:** All GET endpoints return honest empty states (empty lists, `{}`, or `null`) when the spine has not yet recorded state. Missing data is not an error — it means the spine hasn't observed anything yet for this tenant.
