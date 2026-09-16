# Responsiveness & Time-to-Value — Integration Guide

> How the spine integrates with existing Aether subsystems. Every integration is best-effort: a failure in the spine never breaks the primary data path.

---

## Architecture overview

The spine observes and records state from five integration points. Each integration calls into `ResponsivenessService` methods via `get_responsiveness_service()`.

```
┌──────────────────────────────────┐
│  ResponsivenessService           │
│  (services/responsiveness/)      │
│  record_first_event_ack()        │
│  update_heartbeat_state()        │
│  update_provider_sync_state()    │
│  update_graph_hydration_state()  │
│  mark_graph_stub_visible()       │
│  mark_first_value()              │
│  update_projection_state()       │
│  update_lens_projection_state()  │
│  update_timeline_projection_state│
│  record_query()                  │
│  update_background_job()         │
│  record_measurement()            │
└──────────┬───────────────────────┘
           │ best-effort calls
     ┌─────┼──────┬───────────┬──────────┐
     ▼     ▼      ▼           ▼          ▼
┌────────┐┌────┐┌──────────┐┌─────────┐┌──────────┐
│ batch  ││ sc ││ graph_   ││ jobs/   ││ analytics│
│ .py    ││hed ││projector ││ worker  ││ /routes  │
│(ACK)   ││u..)││  .py     ││  .py    ││  .py     │
└────────┘└────┘└──────────┘└─────────┘└──────────┘
```

---

## 1. SDK ingestion — `services/backend/services/ingestion/batch.py`

**What's recorded:** First-event-ack latency + SDK heartbeat state.

### Code path

After events are validated and written to Bronze, the batch handler records the first-event-ack:

```python
# services/backend/services/ingestion/batch.py (lines ~660-675)
from services.responsiveness.service import get_responsiveness_service

# ... inside the batch handler, after n_accepted events are written ...
try:
    ack_dt = utc_now()
    ack_latency_ms = (ack_dt - received_dt).total_seconds() * 1000
    await get_responsiveness_service().record_first_event_ack(
        tenant_id=tenant_id,
        event_id=results[0].id if results else batch_id,
        batch_id=batch_id,
        received_at=received_at,
        ack_latency_ms=ack_latency_ms,
        environment=settings.env.value,
    )
except Exception as exc:
    logger.warning("responsiveness first_event_ack failed: %s", exc)
```

### What `record_first_event_ack` does

1. Loads or creates the `ActivationMilestone` for the tenant.
2. Sets `first_event_acked_at` on first call.
3. If the ACK latency is under 15000ms AND `first_heartbeat_visible_at` is not yet set:
   - Sets `first_heartbeat_visible_at` = now
   - Computes `time_to_first_heartbeat_ms` = now − `first_event_received_at`
   - Sets `first_value_kind` = `"sdk_heartbeat"`
   - Sets `time_to_first_value_ms` = delta (if not already set)
   - Advances status from `not_started` → `partial_value`
   - Publishes `tenant.activation.updated` event
4. Records the measurement via metrics: `aether_time_to_first_event_ack_ms`
5. Persists the milestone via `repository.put_activation_milestone()`

### `update_heartbeat_state`

Also called by the ingestion path (not shown in the batch snippet above — called from the heartbeat update path) to keep `HeartbeatState` fresh per `source_id`:

```python
await get_responsiveness_service().update_heartbeat_state(
    tenant_id=tenant_id,
    source_id=source_id,
    sdk_id=sdk_id,
    environment=environment,
    status=status,              # HeartbeatStatus: not_seen | receiving | validating | healthy | degraded | blocked
    event_count=event_count,
    valid_event_count=valid_event_count,
    invalid_event_count=invalid_event_count,
    last_event_type=last_event_type,
    last_error=last_error,
    schema_version=schema_version,
    ingestion_latency_ms=ingestion_latency_ms,
)
```

This sets `visible_in_dashboard_at` on first call — the moment the SDK's events become visible in the dashboard, which is the `first_heartbeat_visible_at` milestone.

---

## 2. Provider runtime — `services/backend/services/provider_runtime/scheduler.py`

**What's recorded:** Provider sync state — connection lifecycle, first sample, progress %.

### Code path

During a provider sync, when the first batch of events is received:

```python
# services/backend/services/provider_runtime/scheduler.py (lines ~312-328)
from services.responsiveness.service import get_responsiveness_service

# ... inside the sync loop, after events are received ...
if not _first_sample_emitted and events:
    _first_sample_emitted = True
    try:
        await get_responsiveness_service().update_provider_sync_state(
            tenant_id=tenant_id,
            provider_id=provider_identity,
            connection_id=connection_id,
            status="sampling",
            connected_at=_sync_started_at,
            first_sample_record_at=datetime.now(timezone.utc).isoformat(),
            records_sampled=len(events),
            records_discovered=records_received,
            progress_percent=min(100.0, (page / max(1, self.MAX_PAGES)) * 100),
        )
    except Exception:
        pass
```

### What `update_provider_sync_state` does

1. Creates a `ProviderSyncState` with the given status and counters.
2. Preserves `visible_status_updated_at` from the existing record (so the visible state doesn't flicker).
3. Sets `visible_status_updated_at` = now on first call.
4. Persists via `repository.put_provider_sync_state()`.
5. Publishes `tenant.surface_readiness.updated` event with `provider_id`.

### Status transitions

The scheduler calls `update_provider_sync_state` at key lifecycle points:

| When | Status | Fields set |
|------|--------|-----------|
| Connection established | `connected` | `connected_at`, `first_metadata_at` |
| First records received | `sampling` | `first_sample_record_at`, `records_sampled`, `records_discovered`, `progress_percent` |
| Sync in progress | `syncing` | `last_sync_started_at`, `records_synced`, `progress_percent` |
| Sync complete | `ready` / `partially_ready` | `last_sync_completed_at`, `records_synced`, `progress_percent` |
| Error / rate limited | `degraded` / `blocked` | `degraded_reasons`, `blocking_reasons`, `rate_limited` |

---

## 3. Graph projector — `services/backend/services/semantic_intelligence/graph_projector.py`

**What's recorded:** Graph hydration state — node/edge counts, projection progress, first-stub visibility, first-value milestones.

### Code path A: post-sweep update

After each tenant's projection sweep completes:

```python
# services/backend/services/semantic_intelligence/graph_projector.py (lines ~693-705)
from services.responsiveness.service import get_responsiveness_service

# ... after projecting all pairs for a tenant ...
try:
    await get_responsiveness_service().update_graph_hydration_state(
        tenant_id=tenant_id,
        graph_version="current",
        status="hydrating_surfaces" if report.projected else "building_projections",
        raw_events_count=report.relationships_seen,
        edge_count=report.projected,
        projected_edge_count=report.projected,
        hydration_progress_percent=None,
    )
except Exception as exc:
    logger.warning("responsiveness graph_hydration_state update failed: %s", exc)
```

### Code path B: first-stub visibility + first-value

In `project_pair()` (single-pair projection), after a canonical edge is written:

```python
# services/backend/services/semantic_intelligence/graph_projector.py (lines ~822-839)
if projected:
    # ... existing edge/write logic ...

    try:
        await get_responsiveness_service().update_graph_hydration_state(
            tenant_id=tenant_id,
            graph_version="current",
            status="hydrating_surfaces",
            first_node_created_at=...,
            first_edge_created_at=...,
            first_projection_created_at=...,
            hydration_progress_percent=...,
        )
        await get_responsiveness_service().mark_graph_stub_visible(tenant_id, "current")
        await get_responsiveness_service().mark_first_value(tenant_id, "graph_edge")
    except Exception:
        pass
```

### What these methods do

**`update_graph_hydration_state`:**
- Creates/updates `GraphHydrationState` per `(tenant_id, graph_version)`.
- If `mark_first_stub=True` and `first_stub_visible_at` is not set:
  - Sets `first_stub_visible_at` = now
  - Sets `milestone.first_graph_stub_visible_at` = now
  - Advances `milestone.time_to_first_graph_stub_ms` (delta from `first_event_received_at`)
  - Persists the milestone

**`mark_graph_stub_visible`:**
- Explicit hook for the graph stub renderer to call when the stub becomes visible.
- Delegates to `update_graph_hydration_state` with `mark_first_stub=True`.

**`mark_first_value`:**
- Records a first-value moment for the given kind (`"graph_edge"`, `"graph_node"`, etc.).
- Sets the corresponding milestone field (`first_graph_edge_at`, etc.) on first call.
- Sets `first_value_kind` if not already set.
- Advances milestone status to `ready` if currently `partial_value`.

---

## 4. Jobs worker — `services/backend/services/jobs/worker.py`

**What's recorded:** Background job lifecycle timing — status transitions, progress, stage.

### Code path

The jobs worker imports `get_responsiveness_service` but the actual `update_background_job` calls are wired in a later phase. The import is present:

```python
# services/backend/services/jobs/worker.py (line 49)
from services.responsiveness.service import get_responsiveness_service
```

### Planned integration points

When wired, the worker will call `update_background_job` at each lifecycle transition:

| Transition | Status | Fields |
|------------|--------|--------|
| Job claimed | `running` | `started_at`, `current_stage` |
| Progress update | `running` | `progress_percent`, `records_processed`, `records_total`, `current_stage` |
| Job complete | `complete` | `completed_at`, `records_processed`, `progress_percent` |
| Job failed | `failed` | `completed_at`, `failure_reason`, `degraded_surface_ids` |
| Job retrying | `retrying` | `current_stage`, `failure_reason` |
| Job cancelled | `cancelled` | `completed_at` |

```python
# Pseudocode for the planned integration
await get_responsiveness_service().update_background_job(
    tenant_id=tenant_id,
    job_id=job_id,
    job_type=job_type,
    status=new_status,
    progress_percent=progress,
    records_processed=processed,
    records_total=total,
    current_stage=stage,
    user_visible=True,
    can_retry=can_retry,
    can_cancel=can_cancel,
    failure_reason=failure_reason,
)
```

---

## 5. Analytics queries — `services/backend/services/analytics/routes.py`

**What's recorded:** Query execution state — lane, status, first-result latency, total latency, cache hit, projection used.

### Code path A: successful query

After a successful `/v1/analytics/events/query`:

```python
# services/backend/services/analytics/routes.py (lines ~80-95)
from services.responsiveness.service import get_responsiveness_service

# ... after query results are returned ...
completed_at = utc_now()
total_ms = (completed_at - submitted_at).total_seconds() * 1000
lane = "cached" if False else "indexed_graph"  # Redis cache path = cached in budget terms
await get_responsiveness_service().record_query(
    tenant_id=tenant.tenant_id,
    query_id=query_id,
    lane=lane,
    status="complete",
    first_result_latency_ms=total_ms,
    total_latency_ms=total_ms,
    cache_hit=True,
    completed_at=completed_at.isoformat(),
)
```

### Code path B: failed query

After a failed query:

```python
# services/backend/services/analytics/routes.py (lines ~105-115)
except Exception as exc:
    completed_at = utc_now()
    total_ms = (completed_at - submitted_at).total_seconds() * 1000
    await get_responsiveness_service().record_query(
        tenant_id=tenant.tenant_id,
        query_id=query_id,
        lane="analytical",
        status="failed",
        total_latency_ms=total_ms,
        completed_at=completed_at.isoformat(),
        failure_reason=str(exc),
    )
    raise
```

### What `record_query` does

1. Creates a `QueryExecutionState` with the given lane, status, and latencies.
2. Preserves `submitted_at` from the existing record (so the submission time is from the first recording).
3. Preserves `completed_at` if already set.
4. Persists via `repository.put_query_execution_state()`.
5. Emits metrics: `aether_query_execution_total` (counter by lane + status) and `aether_query_total_latency_ms` (histogram by lane).

### Lanes

The `lane` parameter maps to `QueryLane` enum values:

| Lane | Meaning |
|------|---------|
| `cached` | Cached query result |
| `indexed_graph` | Indexed graph query |
| `projection` | Projection-backed query |
| `analytical` | Analytical query (full scan) |
| `semantic` | Semantic query |
| `heavy_background` | Heavy query offloaded to background |
| `generative` | Generative query |

The `record_query` in analytics/routes.py currently uses `lane="indexed_graph"` for successful queries and `lane="analytical"` for failed queries. In a full implementation, the lane would be determined by the actual query path taken.

---

## Best-effort contract

Every integration point wraps the responsiveness call in a try/except that logs a warning (or passes silently for provider sync). This is intentional:

```python
# Pattern used across all integration points
try:
    await get_responsiveness_service().some_method(...)
except Exception as exc:
    logger.warning("responsiveness <method> failed: %s", exc)
    # or: pass  (for provider sync, where the primary path must not be interrupted)
```

The spine is observability, not a data path. If the spine is down, events still flow, providers still sync, graphs still hydrate, queries still execute.

---

## Dependency graph

```
services/responsiveness/service.py
  ├── models.py          (dataclasses + enums)
  ├── repository.py      (ResponsivenessRepository → BaseRepository)
  └── routes.py          (FastAPI router, depends on service)

integration points (call service methods):
  ├── ingestion/batch.py         → record_first_event_ack + update_heartbeat_state
  ├── provider_runtime/scheduler.py → update_provider_sync_state
  ├── semantic_intelligence/graph_projector.py → update_graph_hydration_state + mark_graph_stub_visible + mark_first_value
  ├── jobs/worker.py             → update_background_job (imported, wired in later phase)
  └── analytics/routes.py        → record_query

shared infrastructure used by service:
  ├── shared/events/events.py    (Event, Topic — for publish)
  ├── dependencies.providers     (get_producer — for publish)
  ├── shared.logger.logger       (get_logger, metrics)
  └── shared.common.common       (utc_now)
```

---

## Adding a new integration point

To wire a new integration point into the spine:

1. Import `get_responsiveness_service` in the integration file.
2. Call the appropriate service method at the right lifecycle point, wrapped in try/except.
3. Pass real latency measurements and trace context where available.
4. Record a measurement if the interaction is user-visible or performance-critical.
5. Add the surface/interaction to the contract YAML if it has a budget target.
6. Add a CI gate if the target is critical.
