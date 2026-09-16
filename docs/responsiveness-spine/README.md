---
title: Responsiveness Spine
slug: responsiveness-spine/readme
section: architecture
visibility: P
audience: [dev-senior, architect]
status: beta
---

# Responsiveness & Time-to-Value Spine

> **Slice 6 of 6 — documentation.** Mirrors `services/backend/services/responsiveness/` and the integration instrumentation already committed on `feature/responsiveness-spine`.

The Responsiveness & Time-to-Value (RTV) spine is a dedicated observability and performance contract layer that sits beside the existing Tenant Activation & Readiness Spine. It answers, for any tenant at any moment:

- Is Aether responsive?
- Is the tenant seeing value?
- Is a given surface usable yet?
- Is the graph hydrated enough?
- Is a lens fast enough?
- Is this query path acceptable?

It does not fake progress. Every state transition is driven by real integration points — the SDK ingestion ACK, the provider connection lifecycle, the semantic graph projector, the projection engine, the jobs worker, and the analytics query handler.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Frontend aether / Kyber                        │
│   ResponsivenessDashboard · SurfaceReadinessCard · ActivationTimeline   │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ GET /v1/responsiveness + sub-paths
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  services/backend/services/responsiveness/routes.py                     │
│  GET /v1/responsiveness                           # full envelope        │
│  GET /v1/responsiveness/activation-milestones                              │
│  GET /v1/responsiveness/surface-readiness                                 │
│  GET /v1/responsiveness/sdk-heartbeats                                   │
│  GET /v1/responsiveness/provider-sync-states                             │
│  GET /v1/responsiveness/graph-hydration                                  │
│  GET /v1/responsiveness/projections                                      │
│  GET /v1/responsiveness/lens-projections                                 │
│  GET /v1/responsiveness/timeline-projection                              │
│  GET /v1/responsiveness/background-jobs                                  │
│  GET /v1/responsiveness/measurements                                     │
│  GET /v1/responsiveness/performance-budgets                              │
│  POST /v1/responsiveness/projections/{id}/rebuild     (stub, phase 5)   │
│  POST /v1/responsiveness/providers/{id}/retry        (stub, phase 3)    │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ read / write
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  services/backend/services/responsiveness/                                │
│  models.py          — dataclasses + enums (all state shapes)              │
│  service.py         — ResponsivenessService (aggregates + records)      │
│  repository.py      — ResponsivenessRepository (flat BaseRepository rows)│
│  routes.py          — FastAPI router, single-tenant, APIResponse envelope │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ observes / records
              ┌────────────┼──────────────┬──────────────────┐
              ▼            ▼              ▼                  ▼
   ┌──────────────────┐┌──────────────┐┌──────────────┐┌──────────────┐
   │ ingestion/batch  ││ provider_    ││ graph_       ││ analytics/   │
   │ .py  ACK latency ││ runtime/     ││ projector.py ││ routes.py    │
   │ → first_event_ack││ scheduler.py ││ → graph      ││ query exec   │
   │ → heartbeat      ││ → provider   ││ hydration     ││ → query      │
   └──────────────────┘│ sync state   │└──────────────┘│ state        │
                        └──────────────┘                └──────────────┘
                        ┌──────────────┐
                        │ jobs/        │
                        │ worker.py    │
                        │ → bg job     │
                        │ lifecycle    │
                        └──────────────┘

   Contract: contracts/performance/aether-performance-contract.yaml
```

---

## Endpoint listing

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/responsiveness` | Full tenant envelope (milestone, surfaces, heartbeats, providers, graph, projections, lenses, timeline, jobs) |
| GET | `/v1/responsiveness/activation-milestones` | Activation milestone (first-event-ack, first heartbeat, first graph stub, first value) |
| GET | `/v1/responsiveness/surface-readiness` | All surfaces' readiness (data_state / performance_state / user_visible_state) |
| GET | `/v1/responsiveness/surface-readiness/{surface}` | One surface's readiness; returns `null` if surface not in SURFACE_NAMES |
| GET | `/v1/responsiveness/sdk-heartbeats` | SDK heartbeat states per source_id |
| GET | `/v1/responsiveness/provider-sync-states` | Provider sync states per provider_id |
| GET | `/v1/responsiveness/graph-hydration` | Graph hydration state (query param `graph_version`, default `current`) |
| GET | `/v1/responsiveness/projections` | All projection states |
| GET | `/v1/responsiveness/lens-projections` | All lens projection states |
| GET | `/v1/responsiveness/timeline-projection` | Timeline projection (query param `scope_hash`, default `default`) |
| GET | `/v1/responsiveness/background-jobs` | Background job states |
| GET | `/v1/responsiveness/measurements` | Responsiveness measurements (query param `limit`, default 200, max 1000) |
| GET | `/v1/responsiveness/performance-budgets` | Seeded performance budget definitions |
| GET | `/v1/responsiveness/first-value-kinds` | Sorted list of valid first-value kinds |
| POST | `/v1/responsiveness/projections/{projection_id}/rebuild` | Stub: records intent, returns queued (real impl phase 5) |
| POST | `/v1/responsiveness/providers/{provider_id}/retry` | Stub: records intent, returns queued (real impl phase 3) |

All endpoints are single-tenant (tenant from `request.state.tenant`), require `READ` permission, and return an `APIResponse(data=...)` envelope. Missing data is honest — it returns an empty envelope, never a 404.

---

## State domains

The spine tracks these state objects (all defined in `models.py`):

| Domain | Model | Shape |
|--------|-------|-------|
| Activation milestone | `ActivationMilestone` | Tenant-level timestamps: `first_event_acked_at`, `first_heartbeat_visible_at`, `first_graph_stub_visible_at`, `first_value_kind`, `time_to_first_value_ms`, `status` |
| SDK heartbeat | `HeartbeatState` | Per `source_id`: status, event counts, ingestion latency, visible-in-dashboard time |
| Provider sync | `ProviderSyncState` | Per `provider_id`: status ladder (not_connected → ready), record counts, progress %, blocking/degraded reasons |
| Graph hydration | `GraphHydrationState` | Per `graph_version`: status ladder, node/edge counts, projected counts, first-node/first-edge/stub timestamps |
| Projection | `ProjectionState` | Per `projection_id`: status, freshness, build duration, p95 read latency, dependency versions |
| Lens projection | `LensProjectionState` | Per `lens_id`+`graph_version`+`scope_hash`: status, toggle/first-result/full-hydration latencies |
| Timeline projection | `TimelineProjectionState` | Per `scope_hash`: status, first-render/pan/zoom/grain-change latencies, available grains |
| Query execution | `QueryExecutionState` | Per `query_id`: lane, status, first-result/total latency, cache_hit, projection_used |
| Background job | `BackgroundJobState` | Per `job_id`: status, progress %, stage, user_visible, retry/cancel flags |
| Surface readiness | `SurfaceReadiness` | Per surface: `data_state`, `performance_state`, `user_visible_state`, blocking/degraded reasons, required milestones |
| Measurement | `ResponsivenessMeasurement` | Per interaction: surface, interaction, metric, value_ms, status, trace/span context |

### Readiness ladders

Three parallel ladders are exposed per surface in `SurfaceReadiness`:

```
data_state (is the data there?)
  missing → empty → partial → hydrating → ready → stale → error

performance_state (is it fast enough?)
  unknown → within_budget → warning → degraded → blocked

user_visible_state (what does the user see?)
  not_started → connected → receiving → syncing → hydrating →
  partially_ready → ready → degraded → blocked
```

See [surface-readiness.md](./surface-readiness.md) for the full derivation logic and per-surface mappings.

---

## Integration points

The spine records real evidence from five integration points. Each is wired as a best-effort call — a failure in the spine never breaks the primary data path.

| Integration | File | What's recorded |
|-------------|------|-----------------|
| SDK ingestion ACK | `services/backend/services/ingestion/batch.py` | `record_first_event_ack()` — first-event-ack latency, first heartbeat visible |
| Provider runtime | `services/backend/services/provider_runtime/scheduler.py` | `update_provider_sync_state()` — provider connection lifecycle, first sample, progress % |
| Graph projector | `services/backend/services/semantic_intelligence/graph_projector.py` | `update_graph_hydration_state()` + `mark_graph_stub_visible()` + `mark_first_value()` |
| Jobs worker | `services/backend/services/jobs/worker.py` | `update_background_job()` — job lifecycle timing (imported, phase 2+) |
| Analytics queries | `services/backend/services/analytics/routes.py` | `record_query()` — query execution state, lane, latency, cache hit |

See [integration-guide.md](./integration-guide.md) for code-level detail.

---

## Performance budget summary

The contract YAML at `contracts/performance/aether-performance-contract.yaml` defines per-surface and per-action targets. Key budget highlights:

| Surface | Target | Threshold | Severity |
|---------|--------|-----------|----------|
| SDK first-event-ack | p95 | 1000 ms | info |
| SDK first-heartbeat-visible | p95 | 15000 ms | block |
| Provider oauth-connected | p95 | 2000 ms | degrade |
| Graph first-stub-visible | p95 | 30000 ms | degrade |
| Lens toggle-visual | p95 | 200 ms | degrade |
| Timeline pan | p95 | 200 ms | degrade |
| Cached query | p95 | 750 ms | degrade |
| Frontend LCP | p75 | 2500 ms | degrade |
| Frontend INP | p75 | 200 ms | degrade |

See [performance-budget.md](./performance-budget.md) for the full budget table, CI enforcement, and violation detection.

---

## How to observe

### API (primary)
Fetch the full envelope for a tenant:
```bash
curl -H "Authorization: Bearer $API_KEY" \
     https://aether.example/v1/responsiveness
```

Drill into a single surface:
```bash
curl -H "Authorization: Bearer $API_KEY" \
     https://aether.example/v1/responsiveness/surface-readiness/dashboard
```

### Frontend aether
```ts
import { api } from '@aether/lib/api';

// Full envelope
const envelope = await api.responsiveness.get();

// Drill into one surface
const dashboard = await api.responsiveness.surfaceReadinessOne('dashboard');
console.log(dashboard.data_state, dashboard.performance_state, dashboard.user_visible_state);
```

### Frontend components (aether)
- `ResponsivenessDashboard` — full envelope overview
- `SurfaceReadinessCard` — single surface ladder
- `ActivationMilestoneTimeline` — milestone timestamps + time-to-value
- `SDKHeartbeatCard` — per-source heartbeat state
- `ProviderSyncProgressCard` — per-provider sync progress
- `GraphHydrationStatus` — graph hydration ladder + counts
- `ProjectionFreshnessBadge` — projection freshness indicator

### Kyber operator console
Kyber exposes an aggregate responsiveness index, tenant comparison, and regressions. Components: `PerformanceDebugPanel`, `LiveEventCounter`, `LastUpdatedLabel`, `BlockedSurfaceCallout`, `DegradedSurfaceBanner`, `BackgroundJobToast`, `QueryProgressIndicator`, `TimelineHydrationIndicator`, `LensHydrationIndicator`, `GraphHydrationStatus`, `ProviderSyncProgressCard`, `SDKHeartbeatCard`, `ActivationMilestoneTimeline`, `SurfaceReadinessBadge`, `ResponsivenessBadge`.

See [frontend-integration.md](./frontend-integration.md) for hook and component references.

### Events
The service publishes best-effort event bus messages on state transitions:
- `tenant.activation.updated` — activation milestone change
- `tenant.surface_readiness.updated` — provider sync / surface readiness change
- `lens.projection.updated` — lens projection change
- `background_job.updated` — background job status change

---

## Related documentation

- [endpoints.md](./endpoints.md) — full API reference
- [performance-budget.md](./performance-budget.md) — contract targets and CI
- [integration-guide.md](./integration-guide.md) — subsystem integration detail
- [frontend-integration.md](./frontend-integration.md) — aether + Kyber consumption
- [activation-milestones.md](./activation-milestones.md) — first-event-ack, first-heartbeat, first-graph-stub, first-value
- [surface-readiness.md](./surface-readiness.md) — 9-surface readiness ladders
