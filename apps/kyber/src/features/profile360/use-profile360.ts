import { useEffect, useMemo, useState } from 'react';
import { api } from '@kyber/lib/api/endpoints';
import { isLocalMocked } from '@kyber/lib/env';
import { useWebSocket } from '@kyber/hooks/use-websocket';
import { getMockEntity } from '@kyber/fixtures/entities';
import { getMockEntityNeighborhood } from '@kyber/fixtures/graph';
import { getMockTimeline } from '@kyber/fixtures/entities';
import type { Entity, EntityType, GraphEdge, GraphNode, Profile360EntityType, Profile360LiveMessage, Profile360Payload, Profile360Reference, Profile360Section } from '@kyber/types';
import { profile360Actions, profile360Store, toTimelineEvent, useProfile360Store } from './profile360-store';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function normalizeEntity(raw: unknown, id: string, type: Profile360EntityType): Entity {
  const data = asRecord(raw);
  const now = new Date().toISOString();
  return {
    id: String(data.id ?? data.user_id ?? data.entity_id ?? id),
    type: (data.type ?? type) as EntityType,
    name: String(data.name ?? data.label ?? data.displayLabel ?? id),
    displayLabel: String(data.displayLabel ?? data.label ?? data.name ?? id),
    createdAt: String(data.createdAt ?? data.created_at ?? now),
    updatedAt: String(data.updatedAt ?? data.updated_at ?? now),
    health: { status: String(asRecord(data.health).status ?? 'unknown') as Entity['health']['status'], lastChecked: now },
    trustScore: Number(data.trustScore ?? data.trust_score ?? asRecord(data.intelligence).trust_score ?? 0),
    riskScore: Number(data.riskScore ?? data.risk_score ?? asRecord(data.risk).score ?? 0),
    anomalyScore: Number(data.anomalyScore ?? data.anomaly_score ?? 0),
    needsHelp: Boolean(data.needsHelp ?? data.needs_help ?? false),
    needsHelpReason: data.needsHelpReason || data.needs_help_reason ? String(data.needsHelpReason ?? data.needs_help_reason) : undefined,
    tags: Array.isArray(data.tags) ? data.tags.map(String) : [],
    metadata: data,
  };
}

function normalizeNode(input: unknown, index: number): GraphNode {
  const node = asRecord(input);
  const id = String(node.id ?? node.entity_id ?? `node-${index}`);
  return {
    id,
    type: (node.type ?? node.entity_type ?? 'external') as GraphNode['type'],
    label: String(node.label ?? node.name ?? id),
    trustScore: node.trustScore === undefined && node.trust_score === undefined ? undefined : Number(node.trustScore ?? node.trust_score),
    riskScore: node.riskScore === undefined && node.risk_score === undefined ? undefined : Number(node.riskScore ?? node.risk_score),
    anomalyScore: node.anomalyScore === undefined && node.anomaly_score === undefined ? undefined : Number(node.anomalyScore ?? node.anomaly_score),
    metadata: asRecord(node.metadata ?? node.properties),
  };
}

function normalizeEdge(input: unknown, index: number): GraphEdge {
  const edge = asRecord(input);
  return {
    id: String(edge.id ?? `${edge.source ?? 'source'}-${edge.target ?? 'target'}-${index}`),
    source: String(edge.source ?? edge.from ?? ''),
    target: String(edge.target ?? edge.to ?? ''),
    type: String(edge.type ?? edge.relationship ?? 'related'),
    weight: Number(edge.weight ?? edge.confidence ?? 1),
    label: edge.label ? String(edge.label) : String(edge.type ?? edge.relationship ?? 'related'),
    metadata: asRecord(edge.metadata ?? edge.properties),
  };
}

function normalizeProfile360Payload(raw: Record<string, unknown>, fallbackId: string, fallbackType: Profile360EntityType): Profile360Payload | null {
  const entityRaw = asRecord(raw.entity);
  if (!entityRaw.id && !raw.sections && !raw.graph && !raw.timeline) return null;
  const entity = normalizeEntity(entityRaw.id ? entityRaw : raw, fallbackId, fallbackType);
  const graphRaw = asRecord(raw.graph);
  const timelineRaw = Array.isArray(raw.timeline) ? raw.timeline : [];
  const audit = asRecord(raw.alignment_audit ?? raw.alignmentAudit);
  const tenantId = raw.tenant_id ? String(raw.tenant_id) : raw.tenantId ? String(raw.tenantId) : undefined;
  const surface = raw.surface === 'kyber_internal' || raw.surface === 'end_user' ? raw.surface : undefined;
  const visibility = raw.visibility === 'internal_full' || raw.visibility === 'redacted' ? raw.visibility : undefined;
  return {
    entity,
    ...(tenantId ? { tenantId } : {}),
    ...(surface ? { surface } : {}),
    ...(visibility ? { visibility } : {}),
    sections: asRecord(raw.sections) as Profile360Payload['sections'],
    timeline: timelineRaw.map((event, index) => toTimelineEvent(event, `evt-${index}`)),
    graph: {
      nodes: (Array.isArray(graphRaw.nodes) ? graphRaw.nodes : []).map(normalizeNode),
      edges: (Array.isArray(graphRaw.edges) ? graphRaw.edges : []).map(normalizeEdge),
      alignmentAudit: asRecord(graphRaw.alignment_audit ?? graphRaw.alignmentAudit),
    },
    alignmentAudit: audit,
    raw,
  };
}

function buildSections(entity: Entity, raw: Record<string, unknown>): Profile360Payload['sections'] {
  const intelligence = asRecord(raw.intelligence ?? entity.metadata.intelligence);
  const behavioral = asRecord(raw.behavioral ?? entity.metadata.behavioral);
  const financial = asRecord(raw.financial ?? raw.wallet ?? entity.metadata.wallet);
  const system = asRecord(raw.system ?? raw.runtime ?? raw.device);
  const analytics = asRecord(raw.analytics ?? raw.attribution ?? raw.summary);

  const references = (values: unknown[], fallbackType: Profile360EntityType): readonly Profile360Reference[] => values.slice(0, 12).map((item, i) => {
    const value = asRecord(item);
    const refId = String(value.id ?? value.entity_id ?? value.wallet_address ?? `${fallbackType}-${i}`);
    return { id: refId, type: (value.type ?? value.entity_type ?? fallbackType) as Profile360EntityType, label: String(value.label ?? value.name ?? refId), metadata: value };
  });

  return {
    identity: [
      {
        id: 'identity-attribution',
        title: 'Attribution intelligence',
        summary: 'Identifiers, owners, devices, browsers, platforms, regions, and confidence signals unified around this entity.',
        metrics: [
          { id: 'trust', label: 'Trust', value: Math.round(entity.trustScore * 100), unit: '%', tone: entity.trustScore > 0.75 ? 'good' : 'warning' },
          { id: 'risk', label: 'Risk', value: Math.round(entity.riskScore * 100), unit: '%', tone: entity.riskScore > 0.55 ? 'danger' : 'default' },
          { id: 'anomaly', label: 'Anomaly', value: Math.round(entity.anomalyScore * 100), unit: '%', tone: entity.anomalyScore > 0.55 ? 'warning' : 'default' },
        ],
        references: references([...(Array.isArray(raw.identifiers) ? raw.identifiers : []), ...(Array.isArray(raw.connections) ? raw.connections : [])], 'human'),
        data: intelligence,
      },
    ],
    system: [
      { id: 'system-runtime', title: 'System footprint', summary: 'Device/browser/platform attribution, sessions, uptime, active hours, and automation context.', data: system, references: references(Array.isArray(raw.sessions) ? raw.sessions : [], 'session') },
      { id: 'automation', title: 'Automation behavior', summary: 'Agent ownership, permissions, delegations, protocol usage, and active execution windows.', data: behavioral, references: references(Array.isArray(raw.agents) ? raw.agents : [], 'agent') },
    ],
    financial: [
      { id: 'wallet-flows', title: 'Wallet flows', summary: 'Balances, rewards, spending behavior, treasury movements, and protocol interactions.', data: financial, references: references(Array.isArray(raw.wallets) ? raw.wallets : [], 'wallet') },
      { id: 'rewards', title: 'Rewards and incentives', summary: 'Reward accruals, claims, attribution, and linked journeys.', data: asRecord(raw.rewards), references: references(Array.isArray(raw.transactions) ? raw.transactions : [], 'transaction') },
    ],
    analytics: [
      { id: 'behavioral-intelligence', title: 'Behavioral intelligence', summary: 'Active hours, regions, cohort behavior, platform usage, automation ratio, and trust/risk drivers.', data: analytics, references: references(Array.isArray(raw.journeys) ? raw.journeys : [], 'journey') },
    ],
    debug: [
      { id: 'raw-payload', title: 'Raw normalized payload', summary: 'Backend payload, drill references, causality IDs, execution traces, and diagnostics for wiring.', data: raw, references: references(Array.isArray(raw.traces) ? raw.traces : [], 'execution_trace') },
    ],
  };
}

async function fetchProfile360(type: Profile360EntityType, id: string): Promise<Profile360Payload> {
  if (isLocalMocked()) {
    const mock = getMockEntity(id) ?? getMockEntity('cust-acme-001')!;
    const neighborhood = getMockEntityNeighborhood(mock.id);
    return {
      entity: { ...mock, type: type === 'human' ? 'human' : mock.type },
      sections: buildSections(mock, mock.metadata),
      timeline: [...(getMockTimeline(mock.id)?.events ?? [])],
      graph: { nodes: [...neighborhood.nodes], edges: [...neighborhood.edges] },
      raw: mock.metadata,
    };
  }

  const [profile, timelineResponse, graphResponse, behavioral] = await Promise.all([
    api.profile360.full(type, id).catch(() => api.profile.full(id)),
    api.profile360.timeline(type, id, { limit: 250 }).catch(() => api.profile.timeline(id, 250)).catch(() => ({ events: [] })),
    api.profile360.graph(type, id, { limit: 750 }).catch(() => api.profile.graph(id)).catch(() => ({ nodes: [], edges: [] })),
    api.behavioral.entity(id).catch(() => ({})),
  ]);

  const normalized = normalizeProfile360Payload(asRecord(profile), id, type);
  if (normalized) {
    return normalized;
  }

  const raw: Record<string, unknown> = { ...asRecord(profile), behavioral };
  const graphRaw = asRecord(graphResponse);
  const rawNodes = (Array.isArray(graphRaw.nodes) ? graphRaw.nodes : Array.isArray(graphRaw.connections) ? graphRaw.connections : []) as unknown[];
  const rawEdges = (Array.isArray(graphRaw.edges) ? graphRaw.edges : []) as unknown[];
  const events = (asRecord(timelineResponse).events ?? raw.timeline ?? raw.events ?? []) as unknown[];
  const entity = normalizeEntity(raw, id, type);

  return {
    entity,
    sections: buildSections(entity, raw),
    timeline: events.map((event, index) => toTimelineEvent(event, `evt-${index}`)),
    graph: {
      nodes: rawNodes.map(normalizeNode),
      edges: rawEdges.map(normalizeEdge),
      alignmentAudit: asRecord(graphRaw.alignment_audit ?? graphRaw.alignmentAudit),
    },
    raw,
  };
}

export function useProfile360(type: Profile360EntityType, id: string) {
  const payload = useProfile360Store((state) => state.payloads[id]);
  const timeline = useProfile360Store((state) => state.timelines[id]);
  const graph = useProfile360Store((state) => state.graphs[id]);
  const highlightedNodeIds = useProfile360Store((state) => state.highlightedNodeIds);
  const activeTimelineFilters = useProfile360Store((state) => state.activeTimelineFilters);
  const [isLoading, setIsLoading] = useState(!payload);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(!profile360Store.getState().payloads[id]);
    setError(null);
    fetchProfile360(type, id)
      .then((nextPayload) => {
        if (!cancelled) profile360Actions.upsertPayload(nextPayload);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load Profile360');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => { cancelled = true; };
  }, [type, id]);

  const ws = useWebSocket({
    path: `/v1/profile/${id}/stream`,
    enabled: Boolean(id),
    onMessage: (message) => profile360Actions.applyLiveMessage(message as Profile360LiveMessage),
  });

  useEffect(() => {
    profile360Actions.setWebsocketStatus(ws.status);
  }, [ws.status]);

  const filteredTimeline = useMemo(() => {
    const source = timeline ?? payload?.timeline ?? [];
    if (activeTimelineFilters.length === 0) return source;
    return source.filter((event) => activeTimelineFilters.includes(event.type));
  }, [activeTimelineFilters, payload?.timeline, timeline]);

  return {
    payload,
    entity: payload?.entity,
    sections: payload?.sections ?? {},
    timeline: filteredTimeline,
    graph: graph ?? payload?.graph ?? { nodes: [], edges: [] },
    highlightedNodeIds,
    isLoading,
    error,
    websocketStatus: ws.status,
    actions: profile360Actions,
  };
}
