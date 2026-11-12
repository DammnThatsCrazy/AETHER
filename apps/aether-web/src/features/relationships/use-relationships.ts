import { useQuery } from '@aether/ui';
import { classifyEdgeType } from '@aether/shared';
import { api } from '@aether-app/lib/api/endpoints';

/**
 * Relationships read model. Every relationship is a real graph edge returned
 * by the GraphTraversalEngine routes:
 *
 * - `POST /v1/graph/traverse` — the anchor's neighbourhood up to N hops
 *   (nodes with kind/label/properties, edges with type/validFrom/properties);
 * - `POST /v1/graph/path` — the shortest path between two entities.
 *
 * Strength is the edge's `relationship_score` property when the graph has
 * one; nothing is estimated when it does not.
 */

const STALE = 60_000;

type Row = Record<string, unknown>;

function asRecord(value: unknown): Row {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {};
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

function num(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN;
  return Number.isFinite(n) ? n : null;
}

/** Entity kinds the graph routes accept on an EntityRef (operational_intelligence/models.py EntityKind). */
const REF_KINDS = new Set([
  'tenant', 'org', 'user', 'session', 'device', 'application', 'resource', 'approval', 'entitlement',
  'payment', 'invoice', 'subscription', 'plan', 'wallet', 'contract', 'chain', 'token', 'protocol',
  'agent', 'service', 'payment_intent', 'settlement_event', 'economic_resource', 'facilitator',
  'agent_economic_identity', 'agent_profile360',
]);

/** Kind sent on an EntityRef. The routes resolve by id; the kind must only be a valid literal. */
export function refKind(kind: string | null | undefined): string {
  const k = (kind ?? '').toLowerCase();
  if (REF_KINDS.has(k)) return k;
  if (k === 'organization') return 'org';
  if (k === 'human' || k === 'person' || k === 'profile' || k === 'entity') return 'user';
  return 'user';
}

export type EntityClass = 'human' | 'agent' | 'organization' | 'cluster' | 'other';

export function entityClass(kind: string): EntityClass {
  const k = kind.toLowerCase();
  if (k.includes('cluster') || k.includes('cohort') || k.includes('segment')) return 'cluster';
  if (k.includes('agent')) return 'agent';
  if (k === 'org' || k.includes('organization') || k === 'tenant') return 'organization';
  if (k === 'user' || k === 'human' || k === 'person' || k === 'profile' || k === 'entity' || k === 'identity') return 'human';
  return 'other';
}

/** Where an entity opens in the app: Profile 360, Agent 360, Cluster 360, or the graph workspace. */
export function entityHref(kind: string, id: string): { readonly to: string; readonly label: string } {
  const enc = encodeURIComponent(id);
  switch (entityClass(kind)) {
    case 'human': return { to: `/users/${enc}`, label: 'Open Profile 360' };
    case 'agent': return { to: `/agents/${enc}`, label: 'Open Agent 360' };
    case 'cluster': return { to: `/clusters/${enc}`, label: 'Open Cluster 360' };
    default: return { to: `/explore?entity=${enc}`, label: 'Open in Graph' };
  }
}

export interface RelNode {
  readonly id: string;
  readonly kind: string;
  readonly label: string;
  readonly properties: Row;
}

export interface EvidenceItem {
  readonly text: string;
  readonly basis: string | null;
}

export interface RelEdge {
  readonly id: string;
  readonly type: string;
  readonly from: string;
  readonly to: string;
  readonly validFrom: string | null;
  readonly validTo: string | null;
  /** 0–1 relationship_score from the edge, when the graph recorded one. */
  readonly score: number | null;
  readonly confidence: number | null;
  readonly layer: 'H2H' | 'H2A' | 'A2H' | 'A2A' | null;
  readonly evidence: readonly EvidenceItem[];
  readonly properties: Row;
}

export interface EgoNetwork {
  readonly nodes: readonly RelNode[];
  readonly edges: readonly RelEdge[];
  readonly summary: string | null;
}

function toNode(raw: unknown): RelNode | null {
  const r = asRecord(raw);
  const id = str(r.id);
  if (!id) return null;
  const p = asRecord(r.properties);
  return {
    id,
    kind: str(r.kind) ?? str(p.entity_type) ?? 'entity',
    label: str(r.label) ?? str(p.display_name) ?? str(p.name) ?? str(p.label) ?? id,
    properties: p,
  };
}

function evidenceFrom(r: Row, props: Row): EvidenceItem[] {
  const out: EvidenceItem[] = [];
  const push = (value: unknown, basis: string | null) => {
    if (typeof value === 'string' && value.trim()) out.push({ text: value, basis });
    else if (value && typeof value === 'object') {
      const e = asRecord(value);
      const text = str(e.description) ?? str(e.summary) ?? str(e.label) ?? str(e.ref) ?? str(e.id) ?? str(e.source);
      if (text) out.push({ text, basis: str(e.basis) ?? str(e.kind) ?? str(e.type) ?? str(e.status) ?? basis });
    }
  };
  if (Array.isArray(r.evidence)) r.evidence.forEach(e => push(e, null));
  for (const key of ['evidence', 'evidence_refs', 'evidenceRefs']) {
    const v = props[key];
    if (Array.isArray(v)) v.forEach(e => push(e, null));
    else push(v, null);
  }
  const method = str(props.match_type) ?? str(props.method) ?? str(props.basis) ?? str(props.link_type);
  const source = str(props.source) ?? str(props.source_tag) ?? str(props.provider);
  if (method) out.push({ text: `Matched by ${method.replace(/_/g, ' ')}`, basis: str(props.inferred) === 'true' || props.inferred === true ? 'inferred' : null });
  if (source) out.push({ text: `Reported by ${source.replace(/_/g, ' ')}`, basis: 'source' });
  return out;
}

function toEdge(raw: unknown): RelEdge | null {
  const r = asRecord(raw);
  const from = str(r.from) ?? str(r.source) ?? str(r.from_vertex_id);
  const to = str(r.to) ?? str(r.target) ?? str(r.to_vertex_id);
  const type = str(r.type) ?? str(r.edge_type) ?? 'RELATED_TO';
  if (!from || !to) return null;
  const p = asRecord(r.properties);
  return {
    id: str(r.id) ?? `${from}:${type}:${to}`,
    type,
    from,
    to,
    validFrom: str(r.validFrom) ?? str(p.valid_from) ?? str(p.created_at),
    validTo: str(r.validTo) ?? str(p.valid_to),
    score: num(p.relationship_score),
    confidence: num(p.confidence),
    layer: classifyEdgeType(type),
    evidence: evidenceFrom(r, p),
    properties: p,
  };
}

export function toNetwork(raw: unknown): EgoNetwork {
  const r = asRecord(raw);
  const nodes = (Array.isArray(r.nodes) ? r.nodes : []).map(toNode).filter((n): n is RelNode => n !== null);
  const seen = new Set<string>();
  const edges = (Array.isArray(r.edges) ? r.edges : [])
    .map(toEdge)
    .filter((e): e is RelEdge => e !== null && !seen.has(e.id) && (seen.add(e.id), true));
  const summary = str(asRecord(r.explainability).summary);
  return { nodes, edges, summary };
}

/** Anchor's neighbourhood from the graph traversal engine (1–3 hops). */
export function useEgoNetwork(tenantId: string, anchor: { readonly id: string; readonly kind: string } | null, depth: number) {
  return useQuery({
    key: `relationships:${tenantId}:traverse:${anchor?.id ?? ''}:${depth}`,
    fetcher: async () => toNetwork(await api.graphIntelligence.traverse({
      tenantId,
      start: { kind: refKind(anchor!.kind), id: anchor!.id },
      depth,
      direction: 'both',
      limit: 200,
    })),
    staleTime: STALE,
    enabled: !!tenantId && !!anchor?.id,
  });
}

export interface PathResult {
  readonly found: boolean;
  /** Ordered hops from the source to the target. */
  readonly steps: ReadonlyArray<{ readonly node: RelNode; readonly via: RelEdge | null }>;
}

/** Orders a path GraphResult into hops from `fromId` to `toId` by walking its edges. */
export function orderPath(network: EgoNetwork, fromId: string, toId: string): PathResult {
  if (network.edges.length === 0) return { found: false, steps: [] };
  const byId = new Map(network.nodes.map(n => [n.id, n]));
  const nodeFor = (id: string): RelNode => byId.get(id) ?? { id, kind: 'entity', label: id, properties: {} };
  const steps: Array<{ node: RelNode; via: RelEdge | null }> = [{ node: nodeFor(fromId), via: null }];
  const used = new Set<string>();
  let current = fromId;
  for (let guard = 0; guard < network.edges.length && current !== toId; guard += 1) {
    const next = network.edges.find(e => !used.has(e.id) && (e.from === current || e.to === current));
    if (!next) break;
    used.add(next.id);
    current = next.from === current ? next.to : next.from;
    steps.push({ node: nodeFor(current), via: next });
  }
  return { found: current === toId, steps };
}

export function usePath(
  tenantId: string,
  from: { readonly id: string; readonly kind: string } | null,
  to: { readonly id: string; readonly kind: string } | null,
  maxDepth: number,
) {
  return useQuery({
    key: `relationships:${tenantId}:path:${from?.id ?? ''}:${to?.id ?? ''}:${maxDepth}`,
    fetcher: async () => orderPath(
      toNetwork(await api.graphIntelligence.path({
        tenantId,
        from: { kind: refKind(from!.kind), id: from!.id },
        to: { kind: refKind(to!.kind), id: to!.id },
        maxDepth,
      })),
      from!.id,
      to!.id,
    ),
    staleTime: STALE,
    enabled: !!tenantId && !!from?.id && !!to?.id && from.id !== to.id,
  });
}

/** Hop distance of every node from the anchor over the returned edges (BFS). */
export function hopDistances(anchorId: string, edges: readonly RelEdge[]): Map<string, number> {
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    adj.set(e.from, [...(adj.get(e.from) ?? []), e.to]);
    adj.set(e.to, [...(adj.get(e.to) ?? []), e.from]);
  }
  const dist = new Map<string, number>([[anchorId, 0]]);
  const queue = [anchorId];
  while (queue.length) {
    const u = queue.shift()!;
    for (const v of adj.get(u) ?? []) {
      if (!dist.has(v)) {
        dist.set(v, dist.get(u)! + 1);
        queue.push(v);
      }
    }
  }
  return dist;
}
