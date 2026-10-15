# Profile360 Frontend Architecture

## Existing frontend analysis

- Routing uses `react-router-dom` inside `AppShell`, lazy page modules, and route constants from `src/routes`.
- Layout conventions are preserved through `PageWrapper`, `AppShell`, and existing card/tabs/table primitives.
- Styling is token-driven Tailwind/CSS with reusable `components/system` primitives; Profile360 uses these instead of introducing a new design system.
- State management uses a lightweight external store built on `useSyncExternalStore`; Profile360 extends this with a normalized store for payloads, entities, timelines, graph chunks, drill state, websocket status, and live events.
- Query access is centralized in `lib/api/endpoints.ts`; Profile360 adds normalized endpoint helpers while falling back to established profile/behavioral APIs.
- Websocket integration already exists via `useWebSocket` and `WebSocketClient`; Profile360 subscribes per entity and merges live events into normalized state.
- Graph visualization already uses Cytoscape through `GraphCanvas`; Profile360 wraps it with search, overlays, inspector, highlights, and drill behavior.
- Timeline rendering already uses `EventTimeline`; Profile360 adds causality filters, graph highlighting, and drill references.

## Component hierarchy

```text
Profile360Page / Entity360Page
└── Profile360View
    ├── Profile header and summary metrics
    ├── Tabs: Identity | System | Financial | Graph | Timeline | Analytics | Debug
    ├── Profile360SectionGrid
    ├── Profile360GraphPanel
    │   ├── GraphCanvas
    │   └── Graph inspector
    ├── Profile360TimelinePanel
    │   └── EventTimeline
    └── Profile360DrillStack
```

## Routing extensions

- `/profile360/:type/:id` is the direct Profile360 route.
- `/entities/:type/:id` remains intact and now surfaces the Profile360 system from the existing entity detail flow.
- `profile360Path(type, id)` provides a wiring helper for drill navigation.

## Query architecture

- Primary normalized APIs:
  - `GET /v1/profile360/:entityType/:entityId`
  - `GET /v1/profile360/:entityType/:entityId/graph`
  - `GET /v1/profile360/:entityType/:entityId/timeline`
- Fallback APIs:
  - `api.profile.full`
  - `api.profile.timeline`
  - `api.profile.graph`
  - `api.behavioral.entity`
- The hook normalizes unknown backend payloads into `Entity`, `TimelineEvent`, `GraphNode`, `GraphEdge`, and `Profile360Section` objects for easy backend wiring.

## Websocket integration

- `useProfile360` subscribes to `/v1/profile/:id/stream` using the existing websocket hook.
- Live messages can carry an event, node, edge, or patch.
- Events append into `timelines[entityId]` and `liveEvents`; nodes/edges merge into graph state without duplicate inserts.

## Drill-stack system

- `Profile360DrillStack` renders stacked right-side panels.
- `profile360Store.drillStack` preserves context, depth, metadata, and opened timestamps.
- Any section reference, graph node, or timeline event can push a drill item.
- Drill panels can promote an item into a full `/profile360/:type/:id` route.

## Graph system

- `Profile360GraphPanel` layers search, overlays, selection, edge inspection, and drill actions over the existing Cytoscape canvas.
- Node selection highlights corresponding timeline context through normalized state.
- Edge metadata is exposed in the inspector for ownership, delegation, protocol, causality, and temporal metadata.
- The architecture supports graph chunking through cursor/limit params in `api.profile360.graph`.

## Timeline system

- `Profile360TimelinePanel` renders filtered events with type filters and search.
- Timeline event clicks highlight graph nodes when entity/wallet/agent IDs are present in metadata.
- Timeline clicks also open drill stack panels with trace and session metadata.
- The API helper accepts cursor, limit, start, end, and event type parameters for virtualization/infinite loading wiring.

## State architecture

```text
Profile360State
├── entities: Record<id, Entity>
├── payloads: Record<id, Profile360Payload>
├── timelines: Record<id, TimelineEvent[]>
├── graphs: Record<id, Profile360Graph>
├── drillStack: Profile360DrillItem[]
├── highlightedNodeIds: string[]
├── activeTimelineFilters: string[]
├── websocketStatus
└── liveEvents
```

## File-by-file implementation plan

- `src/types/profile360.ts`: shared type contracts for payloads, views, sections, drill items, live messages, and normalized state.
- `src/features/profile360/profile360-store.ts`: normalized frontend state and mutation actions.
- `src/features/profile360/use-profile360.ts`: data loading, fallback queries, normalization, websocket subscription, and derived timeline state.
- `src/components/profile360/profile360-view.tsx`: top-level Profile360 shell and view orchestration.
- `src/components/profile360/profile360-section-grid.tsx`: progressive disclosure cards for identity, system, financial, analytics, and debug data.
- `src/components/profile360/profile360-drill-stack.tsx`: stacked side-panel drill-down interaction.
- `src/components/profile360/profile360-graph-panel.tsx`: graph search, overlays, inspector, relationship drill actions.
- `src/components/profile360/profile360-timeline-panel.tsx`: filtered causality timeline and graph highlighting.
- `src/pages/profile360.tsx`: route-level page.
- `src/pages/entities/entity-360.tsx`: existing entity route integration.
- `src/lib/api/endpoints.ts`: normalized Profile360 API wiring helpers.

## Performance strategy

- Route-level lazy loading keeps Profile360 off the initial bundle until needed.
- Normalized store avoids duplicated fetches and permits incremental graph/timeline updates.
- API helpers support cursor/limit/time-window parameters for timeline virtualization and graph chunking.
- Cytoscape rendering remains isolated to the graph tab and receives filtered node/edge arrays.
- Live websocket patches merge by ID and cap live/timeline buffers to prevent unbounded growth.
- Drill stack panels progressively reveal raw metadata only when users expand/inspect.

## UI interaction flows

1. User opens a human, agent, organization, wallet, journey, or session profile.
2. Header exposes identity type, health, websocket status, and dense summary metrics.
3. Identity/System/Financial/Analytics tabs summarize attributable intelligence in cards.
4. Clicking a reference opens a stacked drill panel without losing page context.
5. Opening a drill panel as a full profile navigates to `/profile360/:type/:id`.
6. Clicking graph nodes highlights relationship context and enables node drill-down.
7. Clicking timeline events highlights related graph nodes and opens trace/session details.
8. Live websocket events append to the active timeline and graph state in place.

## Backend wiring strategy

- Start with the normalized `profile360` endpoints for new backend surfaces.
- Continue supporting legacy profile, graph, timeline, behavioral, intelligence, and agent endpoints as fallback adapters.
- Emit websocket messages with `{ entityId, event, node, edge, patch }` to update the existing store without custom per-message code.
- Include drill references in each section as `{ id, type, label, metadata }` for automatic panel and route linking.

## Tenant and Surface Alignment Audit

- Kyber uses the internal `/v1/profile360/:entityType/:entityId` surface and expects `surface: "kyber_internal"` with `visibility: "internal_full"`; this route is intentionally broader than any end-user profile presentation.
- Every Profile360 graph/timeline/profile read is scoped by the authenticated tenant from `request.state.tenant.tenant_id`; Kyber may inspect all Profile360 dimensions, but only for the active client/tenant.
- Backend graph composition returns an `alignment_audit` object that records the tenant, excluded cross-tenant neighbors, legacy unscoped graph neighbors, and the sections returned to Kyber.
- Future end-user front ends should not reuse the Kyber route directly. They should call a redacted Profile360 projection that omits debug/audit internals and applies product-specific presentation rules.
