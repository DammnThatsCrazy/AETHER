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
last_synced_commit: 24892a7
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
4. Add 21 additive view tabs: Identity, System, Financial, Cluster, Sessions, Journeys, Social, Web3, Behavioral, Attribution, Agents, Intelligence, Recommendations, Outcomes, Consent, Provenance, Quality, Graph, Timeline, Analytics, Debug.
5. Keep older Overview/Timeline/Graph/Trust/Notes/Actions tabs as familiar deep detail surfaces during migration.
6. New tabs added in this iteration: Cluster, Agents, Intelligence, Recommendations, Outcomes, Consent, Provenance, Quality — each backed by a dedicated panel component in `profile360-contextual-panels.tsx`.

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

- `/v1/profile/{id}/stream` for profile deltas.
- `/v1/profile/{id}/timeline/stream` for timeline append/prepend.
- `/v1/profile/{id}/graph/stream` for graph node/edge mutations.
- `/v1/wallet/{id}/balances/stream` for balance deltas.
- `/v1/agent/{id}/execution/stream` for execution traces.

Messages should upsert normalized records and leave components subscribed through selectors to avoid full rerenders.

## 11. File-by-file implementation plan

Implemented now:

- `apps/kyber/src/types/entities.ts`: expands entity taxonomy and adds Profile360 types.
- `apps/kyber/src/components/entities/profile360-utils.ts`: converts existing metadata, timeline, and graph data into Profile360 summary, relationships, analytics, and drill items.
- `apps/kyber/src/components/entities/profile360-summary-card.tsx`: adaptive compact top card.
- `apps/kyber/src/components/entities/profile360-drill-stack.tsx`: stackable drill context panel.
- `apps/kyber/src/components/entities/profile360-surfaces.tsx`: views for timeline, relationships, realtime events, analytics, and embedded graph.
- `apps/kyber/src/components/entities/entity-360-view.tsx`: wires new Profile360 surfaces into the existing profile UI.
- `apps/kyber/src/pages/entities/entities-page.tsx`: exposes expanded entity type filters.
- `apps/kyber/src/components/graph/graph-canvas.tsx`: adds visual support for new node classes.
- `apps/kyber/src/components/graph/graph-toolbar.tsx`: adds filters for new graph node types.
- `apps/kyber/src/lib/schemas/index.ts`: accepts expanded entity taxonomy.

Additionally implemented (migration steps 3–6):

- `apps/kyber/src/features/profile360/profile360-store.ts`: normalized `Profile360State` store with 17 dimension caches, per-entity loading/error/stale keys, stream status, and live-message upsert reducers.
- `apps/kyber/src/features/profile360/use-profile360.ts`: fetches all 19 profile dimensions (sessions, devices, journeys, wallets, attribution, signals, cluster, clusters, agents, consent, quality, recommendations, outcomes, intelligence, provenance) in parallel; wires timeline/graph delta websocket streams alongside the main profile stream.
- `apps/kyber/src/components/profile360/profile360-timeline-panel.tsx`: windowed timeline rendering — events beyond 200 are paged in 100-at-a-time with a "Load more" control.

Next steps:

- Add graph chunking/clustering controls for very large neighborhoods.
- Gradually deprecate duplicated legacy tab content once parity is verified.

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
3. ✅ Introduce normalized Profile360 store.
4. ✅ Move drill stack from local state to store.
5. ✅ Connect websocket streams as normalized deltas (profile, timeline, graph streams).
6. ✅ Add timeline virtualization (page-windowed at 200-event threshold).
7. Gradually deprecate duplicated legacy tab content once parity is verified.
