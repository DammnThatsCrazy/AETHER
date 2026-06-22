---
title: Profile360 Frontend Architecture
slug: architecture/profile360-frontend
section: architecture
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "8.8.0"
source_files:
  - frontend/kyber/src/components/profile360/
  - frontend/kyber/src/features/profile360/
canonical_owner: frontend@aether
estimated_read_minutes: 10
toc_depth: 3
last_synced_commit: 4db174e
---
# Aether Profile360 Frontend Architecture

This document records the incremental Profile360 migration for the existing Kyber/Aether frontend. It intentionally preserves the current compact entity-card, Entity 360 page, timeline, graph, connections, and event-feed UX while making every backend identity, graph, temporal, financial, reward, delegation, and execution-trace datum surfaceable.

## 1. Current frontend architecture analysis

- **Routing:** `apps/kyber/src/pages/entities/entities-page.tsx` owns `/entities/:type?/:id?`, switches between the entity table and selected entity surface, and delegates selected profile detail to `Entity360Page`.
- **Profile page composition:** `apps/kyber/src/pages/entities/entity-360.tsx` fetches entity detail, timeline, graph neighborhood, interventions, recommendations, notes, and needs-help data before rendering `Entity360View`.
- **Profile UI:** `apps/kyber/src/components/entities/entity-360-view.tsx` already contains the compact 360 profile, overview cards, timeline, graph neighborhood, trust/risk, notes, and actions.
- **Entity cards/list:** `apps/kyber/src/components/entities/entity-list-table.tsx` provides compact operational scanning with trust/risk/anomaly/status indicators.
- **Graph system:** `apps/kyber/src/components/graph/graph-canvas.tsx`, graph controls, toolbar, and inspector provide Cytoscape-backed graph rendering and selection.
- **Temporal/event components:** `apps/kyber/src/components/timelines/*` and live event hooks provide existing timeline/event-feed patterns that Profile360 can reuse.
- **State primitives:** `apps/kyber/src/state/store.ts` exposes a small `useSyncExternalStore` helper suitable for normalized Profile360 slices without introducing a new state library.
- **Realtime primitives:** `apps/kyber/src/hooks/use-websocket.ts` and `apps/kyber/src/lib/api/websocket/client.ts` provide reconnecting websocket subscriptions.
- **Query system:** `apps/kyber/src/lib/api/endpoints.ts` centralizes REST/GraphQL queries for profile, analytics, intelligence, identity, and agent APIs.

## 2. Existing component analysis

Reusable building blocks retained:

- `Card`, `Badge`, `StatusIndicator`, `Tabs`, `ScrollArea`, `Button`, `Input`, `TerminalSeparator` for visual continuity.
- `EntityScoreCard` for trust/risk/anomaly continuity.
- `NeedsHelpPanel` for intervention/action explanations.
- `GraphCanvas` for node/edge visualization.
- Existing mocked fixtures in `apps/kyber/src/fixtures/entities.ts` and graph fixtures for local development.

No stable component was replaced. The new implementation layers Profile360 components above and alongside the existing `Entity360View` detail tabs.

## 3. Extension strategy

Profile360 is implemented as progressive disclosure:

1. Keep the compact top identity pattern recognizable.
2. Add a summary card that adapts by entity type.
3. Add a drill stack that records Human → Agent → Wallet → Transaction → Protocol → Session → Journey → Event → Trace navigation without changing routes.
4. Add six additive views: Identity, System, Financial, Graph, Analytics, Debug.
5. Keep older Overview/Timeline/Graph/Trust/Notes/Actions tabs as familiar deep detail surfaces during migration.

## 4. Updated component hierarchy

```text
EntitiesPage
└─ Entity360Page
   ├─ useEntityData
   ├─ api.profile.timeline / graph / behavioral
   └─ Entity360View
      ├─ Profile360SummaryCard
      ├─ Profile360DrillStack
      ├─ Profile360Views
      │  ├─ RelationshipGraphSurface
      │  ├─ UnifiedTemporalActivityTimeline
      │  ├─ Profile360GraphView
      │  │  └─ GraphCanvas
      │  └─ Profile360AnalyticsPanel
      ├─ RealtimeEventIntelligenceFeed
      └─ Existing legacy-compatible tabs
```

## 5. Drill-stack architecture

- `Profile360DrillItem` is the normalized panel descriptor.
- Timeline events convert with `eventToDrillItem`.
- Relationships convert with `relationshipToDrillItem`.
- Stack state currently lives locally in `Entity360View`; it is shaped to move into a global normalized Profile360 store later.
- Drill items preserve `kind`, `entityId`, `timestamp`, parent context, and metadata for async detail loading.

## 6. Timeline evolution strategy

The existing profile timeline evolves into `UnifiedTemporalActivityTimeline`:

- Filters by event type using compact inline controls.
- Groups by `causalityId` or event type for causal-chain views.
- Opens drill panels for every event.
- Carries `relatedEntityIds`, `traceId`, `parentEventId`, and `causalityId` from backend payloads.
- Supports future temporal scrubbing/replay by using event timestamps and the existing replay/debug primitives.

## 7. Graph visualization system

- `GraphCanvas` now recognizes humans, organizations, journeys, sessions, platforms, devices, browsers, rewards, financial activity, delegations, and relationships.
- `Profile360GraphView` embeds the graph inside the profile drawer/page while still linking to Noesis for full-screen exploration.
- Relationship lists are metadata-rich, searchable, risk/trust-aware, and drillable.
- Graph interactions can synchronize with drill stack immediately and with global timeline/event highlights in the normalized-state phase.

## 8. State architecture

`Profile360StateSlice` defines normalized state for:

- `entitiesById`
- `graphNodesById`
- `graphEdgesById`
- `timelineByEntityId`
- `drillStack`
- `analyticsByEntityId`
- `eventFeedsByEntityId`
- `activeSessionIds`
- `streamStatus`

The next migration should instantiate this shape with `createStore` in `apps/kyber/src/state/store.ts` or a new `profile360-store.ts`, then hydrate it from existing hooks and websocket updates.

## 9. Query architecture

Current wiring remains:

- GraphQL entity lists through `api.analytics.graphql`.
- Full profile through `api.profile.full`.
- Timeline through `api.profile.timeline`.
- Graph through `api.profile.graph` and `api.identity.graphNeighborhood` as needed.
- Behavioral/analytics through `api.behavioral.entity`, `api.intelligence.entityCluster`, wallet/profile/protocol intelligence endpoints, and agent graph/trust endpoints.

Future backend-specific endpoints can map directly into the normalized Profile360 types without changing presentational components.

## 10. Websocket integration

Use `useWebSocket` for entity-scoped subscriptions:

- `/v1/realtime/ws?entity_id={id}` for profile deltas (real endpoint; `use-profile360.ts` connects here).
- `/v1/profile/{id}/timeline/stream` for timeline append/prepend.
- `/v1/profile/{id}/graph/stream` for graph node/edge mutations.
- `/v1/wallet/{id}/balances/stream` for balance deltas.
- `/v1/agent/{id}/execution/stream` for execution traces.

Messages should upsert normalized records and leave components subscribed through selectors to avoid full rerenders.

## 11. Current implementation

The following files implement the complete Profile360 frontend product:

### Core state and data layer

- `frontend/kyber/src/features/profile360/profile360-store.ts`: Normalized Profile360 store with `profile360Actions` covering payload upsert, drill stack, quality/consent/provenance upsert, loading/error/stale tracking, live message application with graph deduplication, and websocket status.
- `frontend/kyber/src/features/profile360/use-profile360.ts`: `useProfile360(type, id, window)` hook — fetches all Profile360 dimensions in parallel (19 simultaneous requests), builds normalized sections, subscribes to the entity websocket, and exposes filtered timeline. The `window` parameter (default `'30d'`) is passed to all window-aware API calls and is a `useEffect` dependency so changing `TimeWindowSelector` triggers a data refetch.
- `frontend/kyber/src/lib/api/endpoints.ts`: Complete API client with 50+ profile sub-routes including quality, consent, cluster, identity-confidence, merge/split history, attribution (window-aware), economic (all sub-routes), agent-executions, actions, events, outcomes, outcome-ledger, recommendations, data-freshness, activation-eligibility.

### Profile360 view layer (canonical)

- `frontend/kyber/src/components/profile360/profile360-view.tsx`: Canonical Profile360 view with 21 tabs (identity, system, financial, cluster, sessions, journeys, social, wallets, behavioral, attribution, agents, intelligence, recommendations, outcomes, consent, provenance, quality, graph, timeline, analytics, debug). Uses `TimeWindowSelector` and passes `timeWindow` to `useProfile360`. Renders `Profile360DrillStack` and `Profile360GraphPanel`.
- `frontend/kyber/src/components/profile360/profile360-graph-panel.tsx`: Graph panel with Cytoscape rendering, overlay selection (trust/risk/anomaly), node type filter, full-text search, degree-based chunking for large graphs (>150 nodes), and a graph inspector that renders `Profile360SummaryCard` when a node is selected and its metadata includes `profile_links`.
- `frontend/kyber/src/components/profile360/profile360-drill-stack.tsx`: Stackable drill panel. Each push records `kind`, `entityId`, `depth`, `openedAt` and renders a detail panel from the normalized payload.
- `frontend/kyber/src/components/profile360/profile360-section-grid.tsx`: Renders `Profile360Section` arrays with metric tiles, reference links, and data panels.
- `frontend/kyber/src/components/profile360/profile360-timeline-panel.tsx`: Timeline with filter controls and drill-on-click.
- `frontend/kyber/src/components/profile360/profile360-contextual-panels.tsx`: All 13 contextual tab panels (sessions, journeys, wallets, behavioral, attribution, cluster, agents, consent, quality, recommendations, outcomes, intelligence, provenance). The attribution panel (`Profile360AttributionPanel`) includes an **Acquisition** section surfacing `first_campaign`, `campaign_history`, `attributed_conversions`, and `attributed_revenue` from section data, with links to Journey Explorer (`/measurement/journeys`) and Campaign Intelligence (`/measurement/campaigns`).

### Entity360View graph tab (embedded)

- `frontend/kyber/src/components/entities/entity-360-view.tsx`: The graph tab now renders `GraphCanvas` with full Cytoscape graph (not a placeholder). Overlay controls (none/trust/risk/anomaly) and node selection drives the drill stack. `profile_links` metadata on graph nodes enables direct profile navigation.

### Summary card and helpers

- `frontend/kyber/src/components/entities/profile360-summary-card.tsx`: Compact preview card showing avatar initials, trust/wallet/agent tiles, primary metrics with tone colours, tags, and NEEDS HELP badge.
- `frontend/kyber/src/components/entities/needs-help-panel.tsx`: Needs-help intervention panel.

### Fixtures and tests

- `frontend/kyber/src/fixtures/entities.ts`: Includes edge-case fixtures — `mockConsentRestrictedEntity`, `mockStaleEntity`, `mockHighConfidenceEntity`, `mockAgentEntity`, `mockKyberInternalProfile`.
- `frontend/kyber/src/test/component/profile360.test.ts`: Unit tests for `profile360Actions` (upsertPayload, drill stack, quality/consent upsert, loading/error/stale), `applyLiveMessage` (graph deduplication, timeline prepend), and `toTimelineEvent` normalizer.

## 12. Window propagation

`useProfile360(type, id, window)` accepts a `window: string` parameter (default `'30d'`). It is:
- Passed to `api.profile.attribution(id, window)`
- In the `useEffect` dependency array — window change triggers a full data refetch

`Profile360View` passes its `TimeWindowSelector` state (`timeWindow`) directly to `useProfile360(type, id, timeWindow)`.

Panels that render window-specific data (social intelligence, behavioral) receive `window` as a prop directly from `Profile360View`.

## 13. Graph node profile preview

Backend graph nodes from `ProfileComposer._compose_graph()` include:
```json
{
  "id": "...",
  "type": "wallet",
  "label": "...",
  "profile_id": "...",
  "entity_type": "wallet",
  "display_label": "...",
  "profile_links": {
    "summary": "/v1/profile/{id}/summary",
    "full": "/v1/profile360/wallet/{id}",
    "drill": null
  }
}
```

When a node is selected in `Profile360GraphPanel`, the graph inspector:
1. Calls `nodeToEntity()` and `nodeToSummary()` to normalize the node
2. Renders `Profile360SummaryCard` with structured data
3. Shows "Open full profile →" link using `profile_links.full`
4. Renders "Drill into node" button that pushes to the drill stack

## 14. Kyber vs end-user surface

The `surface` field on `Profile360Response` controls visibility:
- `kyber_internal` + `visibility: internal_full` → full unredacted data including alignment audit
- `end_user` + `visibility: redacted` → tenant-permitted data only

The `Profile360View` does not apply redaction itself — that is the responsibility of the backend surface selector. The `alignment_audit.end_user_surface_requires_redaction` flag is always `true` for `kyber_internal` responses.

## 15. Websocket integration

`use-profile360.ts` connects to `/v1/realtime/ws?entity_id={id}` via `useWebSocket`. Messages are processed by `profile360Actions.applyLiveMessage`:
- `event` field → prepended to the entity timeline (capped at 1000 events)
- `node` field → appended to graph nodes if not already present (deduped by `node.id`)
- `edge` field → appended to graph edges if not already present (deduped by `edge.id`)
- Global `liveEvents` feed capped at 200 items

Next steps:

- Add virtualized long timeline rendering once event counts exceed the compact threshold.
- Add graph clustering controls for very large neighborhoods (>500 nodes).

## 12. React implementations

The React implementation is intentionally additive and colocated with existing entity components. It uses existing system primitives and Cytoscape graph rendering, preserving the operational Aether/Kyber visual language.

## 13. Backend API wiring strategy

Backend payloads should prefer normalized references:

```json
{
  "entities": {},
  "relationships": [],
  "timeline": [],
  "analytics": {},
  "drill_refs": []
}
```

Frontend adapters should perform thin field normalization only. Backend should provide pre-joined aggregations where possible to avoid frontend-side joins.

## 14. Incremental migration strategy

1. Ship additive Profile360 components alongside existing tabs.
2. Feed mocked and existing profile APIs through adapters.
3. Introduce normalized Profile360 store.
4. Move drill stack from local state to store.
5. Connect websocket streams as normalized deltas.
6. Add virtualization and graph chunking behind thresholds.
7. Gradually deprecate duplicated legacy tab content once parity is verified.
