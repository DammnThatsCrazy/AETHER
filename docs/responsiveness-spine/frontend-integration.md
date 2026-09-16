# Responsiveness & Time-to-Value — Frontend Integration

> How frontend aether and Kyber consume the Responsiveness & Time-to-Value spine.

---

## Backend API

All endpoints are under `/v1/responsiveness`. See [endpoints.md](./endpoints.md) for full request/response shapes.

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/responsiveness` | Full tenant envelope |
| `GET /v1/responsiveness/activation-milestones` | Activation milestone |
| `GET /v1/responsiveness/surface-readiness` | All surfaces' readiness |
| `GET /v1/responsiveness/surface-readiness/{surface}` | One surface's readiness |
| `GET /v1/responsiveness/sdk-heartbeats` | SDK heartbeat states |
| `GET /v1/responsiveness/provider-sync-states` | Provider sync states |
| `GET /v1/responsiveness/graph-hydration` | Graph hydration (query `graph_version`) |
| `GET /v1/responsiveness/projections` | Projection states |
| `GET /v1/responsiveness/lens-projections` | Lens projection states |
| `GET /v1/responsiveness/timeline-projection` | Timeline projection (query `scope_hash`) |
| `GET /v1/responsiveness/background-jobs` | Background jobs |
| `GET /v1/responsiveness/measurements` | Measurements (query `limit`) |
| `GET /v1/responsiveness/performance-budgets` | Budget definitions |
| `GET /v1/responsiveness/first-value-kinds` | Valid first-value kinds |
| `POST /v1/responsiveness/projections/{id}/rebuild` | Stub: rebuild projection |
| `POST /v1/responsiveness/providers/{id}/retry` | Stub: retry provider sync |

All endpoints return `APIResponse(data=...)` envelopes. Missing data is honest — empty lists, `{}`, or `null`, never 404.

---

## Frontend aether

### API client

The aether API client lives at `frontend/aether/src/lib/api/endpoints.ts` under `api.responsiveness.*`:

```ts
import { api } from '@aether/lib/api';

// Full envelope — one call for dashboard overview
const envelope = await api.responsiveness.get();

// Activation milestone
const milestone = await api.responsiveness.activationMilestones();

// All surfaces' readiness
const surfaces = await api.responsiveness.surfaceReadiness();

// One surface's readiness
const dashboard = await api.responsiveness.surfaceReadinessOne('dashboard');

// SDK heartbeats
const heartbeats = await api.responsiveness.sdkHeartbeats();

// Provider sync states
const syncs = await api.responsiveness.providerSyncStates();

// Graph hydration (default: "current")
const graph = await api.responsiveness.graphHydration('current');

// Projections
const projections = await api.responsiveness.projections();

// Lens projections
const lenses = await api.responsiveness.lensProjections();

// Timeline projection (default: "default")
const timeline = await api.responsiveness.timelineProjection('default');

// Background jobs
const jobs = await api.responsiveness.backgroundJobs();
```

### Types

The envelope type is `ResponsivenessEnvelope` (imported from `@aether/types/responsiveness`). Individual surface/heartbeat/provider/etc. types are inferred from `unknownSchema` in the client — they mirror the backend `models.py` shapes.

### Hooks

The following hooks consume the responsiveness API and provide reactive state to components. This is the hook surface as designed — implementations are in `frontend/aether/src/hooks/`.

| Hook | Purpose | Key return values |
|------|---------|-------------------|
| `useResponsiveness()` | Full envelope, polled or event-driven | `envelope`, `loading`, `error` |
| `useSurfaceReadiness(surface?)` | One or all surfaces' readiness | `surfaces`, `loading`, `error` |
| `useSdkHeartbeats()` | SDK heartbeat states | `heartbeats`, `healthyCount`, `degradedCount`, `blockedCount` |
| `useProviderSyncStates()` | Provider sync states | `syncs`, `connectedCount`, `readyCount`, `progressByProvider` |
| `useGraphHydration(graphVersion?)` | Graph hydration state | `hydration`, `status`, `progressPercent`, `nodeCount`, `edgeCount` |
| `useProjections()` | All projection states | `projections`, `readyCount`, `staleCount`, `failedCount` |
| `useLensProjections()` | All lens projection states | `lenses`, `readyCount`, `byLensId` |
| `useTimelineProjection(scopeHash?)` | Timeline projection state | `timeline`, `status`, `availableGrains`, `freshnessMs` |
| `useBackgroundJobs()` | Background job states | `jobs`, `runningCount`, `failedCount`, `jobsByStage` |

### Usage pattern

```tsx
import { useResponsiveness, useSurfaceReadiness } from '@aether/hooks/responsiveness';

function ResponsivenessDashboard() {
  const { envelope, loading, error } = useResponsiveness();
  const { surfaces } = useSurfaceReadiness();

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorPanel error={error} />;

  return (
    <div className="responsiveness-dashboard">
      <ActivationMilestoneTimeline milestone={envelope.activation_milestone} />
      {surfaces.map(surface => (
        <SurfaceReadinessCard key={surface.surface} surface={surface} />
      ))}
    </div>
  );
}
```

### Components

| Component | Purpose | Props |
|-----------|---------|-------|
| `ResponsivenessDashboard` | Full envelope overview — milestone timeline + surface grid | `envelope` (ResponsivenessEnvelope) |
| `SurfaceReadinessCard` | Single surface ladder (data_state / performance_state / user_visible_state) | `surface` (SurfaceReadiness) |
| `ActivationMilestoneTimeline` | Timeline of first-event-ack, first-heartbeat, first-graph-stub, first-value | `milestone` (ActivationMilestone) |
| `SDKHeartbeatCard` | Per-source heartbeat state, status badge, latency | `heartbeat` (HeartbeatState) |
| `ProviderSyncProgressCard` | Per-provider sync progress bar, status ladder, record counts | `sync` (ProviderSyncState) |
| `GraphHydrationStatus` | Graph hydration ladder, node/edge counts, projection counts | `hydration` (GraphHydrationState) |
| `ProjectionFreshnessBadge` | Projection freshness indicator (fresh / stale / refreshing) | `projection` (ProjectionState), `thresholdMs?`) |

### Routing

The aether frontend routes to a `/responsiveness` (or `/settings/performance`) page that renders `ResponsivenessDashboard` as the primary view. Surface-level drill-down is via `SurfaceReadinessCard` expansion or a dedicated `/responsiveness/surfaces/{surface}` route.

---

## Kyber operator console

Kyber is the all-tenant aggregate layer. It consumes the same backend endpoints but renders operator-facing views: responsiveness index across tenants, tenant comparison, and regression detection.

### API client

Kyber's API client lives at `frontend/kyber/src/lib/api/endpoints.ts`. As of the current commit, Kyber does not yet have a dedicated `api.responsiveness.*` section — it consumes the endpoints via the shared `restClient` directly or through the aether API client where Kyber has tenant-scoped access.

When wired, the Kyber client will look like:

```ts
// Planned Kyber responsiveness API surface
export const api = {
  // ... existing Kyber endpoints ...
  responsiveness: {
    /** Aggregate index across all tenants (Kyber-scoped). */
    index: () => restClient.get('/v1/kyber/responsiveness', wrap(unknownSchema)).then(r => r.data),
    /** Tenant comparison: readiness + time-to-value side by side. */
    tenants: (params?: { limit?: number; status?: string }) =>
      restClient.get('/v1/kyber/responsiveness/tenants', wrap(unknownSchema)).then(r => r.data),
    /** Regressions: tenants that degraded since last check. */
    regressions: (params?: { window?: string }) =>
      restClient.get('/v1/kyber/responsiveness/regressions', wrap(unknownSchema)).then(r => r.data),
  },
};
```

Note: the `/v1/kyber/responsiveness/*` routes are planned operator endpoints — they aggregate across tenants and are not part of the single-tenant `/v1/responsiveness` spine. They are implemented in a later phase.

### Hooks (Kyber)

| Hook | Purpose |
|------|---------|
| `useKyberResponsivenessIndex()` | Aggregate index across tenants |
| `useTenantResponsivenessComparison(tenantIds?)` | Side-by-side comparison |
| `useResponsivenessRegressions(window?)` | Tenants that degraded |

### Components (Kyber)

| Component | Purpose |
|-----------|---------|
| `PerformanceDebugPanel` | Full responsiveness debug view for an operator — envelope + surfaces + jobs + measurements |
| `LiveEventCounter` | Live count of events ingested (from SDK heartbeats) |
| `LastUpdatedLabel` | "Last updated X ago" label for any responsiveness surface |
| `BlockedSurfaceCallout` | Callout banner for a surface in `blocked` state |
| `DegradedSurfaceBanner` | Banner for a surface in `degraded` state |
| `BackgroundJobToast` | Toast notification for background job status changes |
| `QueryProgressIndicator` | Query progress indicator (from `QueryExecutionState`) |
| `TimelineHydrationIndicator` | Timeline hydration status indicator |
| `LensHydrationIndicator` | Lens hydration status indicator |
| `GraphHydrationStatus` | Graph hydration status (shared with aether) |
| `ProviderSyncProgressCard` | Provider sync progress (shared with aether) |
| `SDKHeartbeatCard` | SDK heartbeat card (shared with aether) |
| `ActivationMilestoneTimeline` | Activation milestone timeline (shared with aether) |
| `SurfaceReadinessBadge` | Compact badge for surface readiness state |
| `ResponsivenessBadge` | Overall responsiveness badge (healthy / degraded / blocked / unknown) |

### Shared components

Several components are shared between aether and Kyber via `@aether/components/responsiveness`:

- `GraphHydrationStatus`
- `ProviderSyncProgressCard`
- `SDKHeartbeatCard`
- `ActivationMilestoneTimeline`

These live in the shared package and are imported by both aether and Kyber.

---

## State management

### Polling vs events

The spine publishes event bus messages on state transitions:
- `tenant.activation.updated`
- `tenant.surface_readiness.updated`
- `lens.projection.updated`
- `background_job.updated`

Frontend hooks can choose between:
1. **Polling** — periodic refetch (e.g. every 30s) — simple, always fresh enough for dashboards.
2. **Event-driven** — subscribe to the event bus (via WebSocket or SSE) and refetch on relevant events — more responsive, more complex.

The default pattern for aether is polling with a 30s interval. Kyber uses event-driven updates for the operator console to catch regressions quickly.

### Polling pattern

```ts
function useResponsiveness() {
  const { data: envelope, loading, error } = useQuery({
    queryKey: ['responsiveness', 'envelope'],
    queryFn: () => api.responsiveness.get(),
    refetchInterval: 30000, // 30s polling
    staleTime: 10000,
  });
  return { envelope, loading, error };
}
```

### Event-driven pattern

```ts
function useResponsivenessEventDriven() {
  const { data: envelope } = useQuery({
    queryKey: ['responsiveness', 'envelope'],
    queryFn: () => api.responsiveness.get(),
    refetchInterval: false,
  });

  usesubscribe('tenant.activation.updated', (event) => {
    if (event.tenant_id === currentTenantId) {
      queryClient.invalidateQueries({ queryKey: ['responsiveness', 'envelope'] });
    }
  });

  return { envelope };
}
```

---

## Error handling

All responsiveness endpoints return honest empty states when the spine has not yet recorded data:

| Scenario | Response |
|----------|----------|
| No data yet | `envelope.activation_milestone` is `null`, `surfaces` is `[]`, etc. |
| Invalid surface name | `surfaceReadinessOne(surface)` returns `null` (not 404) |
| Tenant not found | Same as no data — the endpoint is single-tenant and the tenant context is from the request, not the path |

Components should render empty-state UI (e.g. "No data yet — the spine hasn't observed anything for this tenant") rather than error states for these cases.

---

## Performance considerations

- The full envelope (`GET /v1/responsiveness`) is the heaviest call — it aggregates 8 sub-resources. Use it for dashboard overviews, not for per-surface updates.
- Per-surface calls (`surfaceReadinessOne(surface)`) are lightweight — use them for surface-level detail panels.
- Polling interval should be tuned per surface: SDK heartbeats and provider syncs change frequently (seconds), surface readiness changes less frequently (minutes).
- The event-driven pattern avoids unnecessary polling for surfaces that don't change often.

---

## Adding a new consumer

To add a new frontend consumer of the spine:

1. Add the API endpoint to the relevant client (`api.responsiveness.*` in aether or Kyber).
2. Add a typed schema if the consumer needs type safety (otherwise use `unknownSchema`).
3. Add a hook that wraps the API call with polling or event-driven refresh.
4. Add a component that renders the state.
5. Wire the component into the relevant page or dashboard.
6. Handle the honest empty state — don't treat missing data as an error.
