import { createStore, useStore } from '@kyber/state';
import type { Entity, Profile360PanelDrillItem, Profile360Graph, Profile360LiveMessage, Profile360Payload, Profile360State, Profile360Quality, Profile360Consent, Profile360Provenance, Profile360StreamStatus, TimelineEvent } from '@kyber/types';

const initialState: Profile360State = {
  entities: {},
  payloads: {},
  timelines: {},
  graphs: {},
  drillStack: [],
  highlightedNodeIds: [],
  activeTimelineFilters: [],
  websocketStatus: 'disconnected',
  liveEvents: [],
  summariesById: {},
  clustersByEntityId: {},
  journeysByEntityId: {},
  campaignsByEntityId: {},
  attributionByEntityId: {},
  walletsByEntityId: {},
  agentsByEntityId: {},
  sessionsByEntityId: {},
  devicesByEntityId: {},
  recommendationsByEntityId: {},
  qualityByEntityId: {},
  consentByEntityId: {},
  provenanceByEntityId: {},
  streamStatusByEntityId: {},
  loadingByKey: {},
  errorsByKey: {},
  staleByKey: {},
};

export const profile360Store = createStore<Profile360State>(initialState);

export function useProfile360Store<S>(selector: (state: Profile360State) => S): S {
  return useStore(profile360Store, selector);
}

export const profile360Actions = {
  upsertPayload(payload: Profile360Payload) {
    profile360Store.setState((state) => ({
      ...state,
      entities: { ...state.entities, [payload.entity.id]: payload.entity },
      payloads: { ...state.payloads, [payload.entity.id]: payload },
      timelines: { ...state.timelines, [payload.entity.id]: payload.timeline },
      graphs: { ...state.graphs, [payload.entity.id]: payload.graph },
    }));
  },
  upsertEntity(entity: Entity) {
    profile360Store.setState((state) => ({ ...state, entities: { ...state.entities, [entity.id]: entity } }));
  },
  upsertGraph(entityId: string, graph: Profile360Graph) {
    profile360Store.setState((state) => ({ ...state, graphs: { ...state.graphs, [entityId]: graph } }));
  },
  pushDrill(item: Omit<Profile360PanelDrillItem, 'depth' | 'openedAt'>) {
    profile360Store.setState((state) => ({
      ...state,
      drillStack: [
        ...state.drillStack,
        { ...item, depth: state.drillStack.length, openedAt: new Date().toISOString() },
      ],
    }));
  },
  popDrill(depth?: number) {
    profile360Store.setState((state) => ({
      ...state,
      drillStack: depth === undefined ? state.drillStack.slice(0, -1) : state.drillStack.slice(0, depth + 1),
    }));
  },
  clearDrill() {
    profile360Store.setState((state) => ({ ...state, drillStack: [] }));
  },
  highlightNodes(nodeIds: readonly string[]) {
    profile360Store.setState((state) => ({ ...state, highlightedNodeIds: nodeIds }));
  },
  setTimelineFilters(filters: readonly string[]) {
    profile360Store.setState((state) => ({ ...state, activeTimelineFilters: filters }));
  },
  setWebsocketStatus(status: Profile360State['websocketStatus']) {
    profile360Store.setState((state) => ({ ...state, websocketStatus: status }));
  },
  upsertDimension(entityId: string, dimension: string, data: unknown) {
    const key = `${dimension}ByEntityId` as keyof typeof initialState;
    profile360Store.setState((state) => ({
      ...state,
      [key]: { ...(state[key] as Record<string, unknown>), [entityId]: data },
    }));
  },
  upsertQuality(entityId: string, quality: Profile360Quality) {
    profile360Store.setState((state) => ({
      ...state,
      qualityByEntityId: { ...state.qualityByEntityId, [entityId]: quality },
    }));
  },
  upsertConsent(entityId: string, consent: Profile360Consent) {
    profile360Store.setState((state) => ({
      ...state,
      consentByEntityId: { ...state.consentByEntityId, [entityId]: consent },
    }));
  },
  upsertProvenance(entityId: string, provenance: Profile360Provenance) {
    profile360Store.setState((state) => ({
      ...state,
      provenanceByEntityId: { ...state.provenanceByEntityId, [entityId]: provenance },
    }));
  },
  setLoading(key: string, loading: boolean) {
    profile360Store.setState((state) => ({
      ...state,
      loadingByKey: { ...state.loadingByKey, [key]: loading },
    }));
  },
  setError(key: string, error: string | null) {
    profile360Store.setState((state) => ({
      ...state,
      errorsByKey: { ...state.errorsByKey, [key]: error },
    }));
  },
  markStale(key: string) {
    profile360Store.setState((state) => ({
      ...state,
      staleByKey: { ...state.staleByKey, [key]: true },
    }));
  },
  clearStale(key: string) {
    profile360Store.setState((state) => ({
      ...state,
      staleByKey: { ...state.staleByKey, [key]: false },
    }));
  },
  setStreamStatus(entityId: string, status: Profile360StreamStatus) {
    profile360Store.setState((state) => ({
      ...state,
      streamStatusByEntityId: { ...state.streamStatusByEntityId, [entityId]: status },
    }));
  },
  resetDrillStack() {
    profile360Store.setState((state) => ({ ...state, drillStack: [] }));
  },
  applyLiveMessage(message: Profile360LiveMessage) {
    profile360Store.setState((state) => {
      const entityId = message.entityId;
      const liveEvent = message.event;
      const nextLiveEvents = liveEvent ? [liveEvent, ...state.liveEvents].slice(0, 200) : state.liveEvents;
      if (!entityId) return { ...state, liveEvents: nextLiveEvents };

      const currentTimeline = state.timelines[entityId] ?? [];
      const nextTimelines = liveEvent
        ? { ...state.timelines, [entityId]: [liveEvent, ...currentTimeline].slice(0, 1000) }
        : state.timelines;

      const currentGraph = state.graphs[entityId];
      const nextGraph: Profile360Graph | undefined = currentGraph
        ? {
            ...currentGraph,
            nodes: message.node && !currentGraph.nodes.some((node) => node.id === message.node?.id)
              ? [...currentGraph.nodes, message.node]
              : currentGraph.nodes,
            edges: message.edge && !currentGraph.edges.some((edge) => edge.id === message.edge?.id)
              ? [...currentGraph.edges, message.edge]
              : currentGraph.edges,
          }
        : undefined;

      return {
        ...state,
        liveEvents: nextLiveEvents,
        timelines: nextTimelines,
        graphs: nextGraph ? { ...state.graphs, [entityId]: nextGraph } : state.graphs,
      };
    });
  },
};

export function toTimelineEvent(input: unknown, fallbackId: string): TimelineEvent {
  const value = (input && typeof input === 'object' ? input : {}) as Record<string, unknown>;
  return {
    id: String(value.id ?? fallbackId),
    timestamp: String(value.timestamp ?? value.created_at ?? new Date().toISOString()),
    type: String(value.type ?? value.event_type ?? 'event'),
    title: String(value.title ?? value.event_type ?? value.type ?? 'Profile event'),
    description: String(value.description ?? value.summary ?? ''),
    severity: (value.severity === 'P0' || value.severity === 'P1' || value.severity === 'P2' || value.severity === 'P3' || value.severity === 'info') ? value.severity : 'info',
    controller: value.controller ? String(value.controller) : undefined,
    traceId: value.trace_id || value.traceId ? String(value.trace_id ?? value.traceId) : undefined,
    metadata: (value.metadata ?? value.properties ?? {}) as Record<string, unknown>,
  };
}
