import type { GraphEdge, GraphNode } from '@aether-app/components/graph/graph-canvas';
import type { GraphCluster } from '@aether-app/features/graph/use-graph-data';

/**
 * Pure derivations behind the Graph (Explore) design: the left-to-right flow,
 * the lenses, the places on the globe and the replay timeline. Everything here
 * is computed from the graph read GraphPage already performs
 * (`/v1/explore/query`, surface `graph`). A lens or view whose inputs are not
 * present in that read reports itself unavailable — nothing is estimated.
 */

export type GraphReadStatus = 'loading' | 'ready' | 'error';

export interface GraphSnapshot {
  readonly status: GraphReadStatus;
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
  readonly clusters: readonly GraphCluster[];
}

export const LOADING_SNAPSHOT: GraphSnapshot = { status: 'loading', nodes: [], edges: [], clusters: [] };

// ── Flow columns ────────────────────────────────────────────────────────────

export type FlowColumnId = 'sources' | 'people' | 'agents' | 'destinations';

export const FLOW_COLUMNS: ReadonlyArray<{ readonly id: FlowColumnId; readonly label: string }> = [
  { id: 'sources', label: 'Sources' },
  { id: 'people', label: 'People & devices' },
  { id: 'agents', label: 'Agents & wallets' },
  { id: 'destinations', label: 'Organizations' },
];

/** Left-to-right lane for a node kind: where it came from → who acted → what acted for them → where it ended. */
export function flowColumn(kind: string): FlowColumnId {
  const k = kind.toLowerCase();
  if (/agent|wallet|bot/.test(k)) return 'agents';
  if (/org|company|merchant|store|business|vendor|supplier|account|product|order|venue/.test(k)) return 'destinations';
  if (/person|user|human|customer|profile|identity|entity|contact|member|household|device/.test(k)) return 'people';
  return 'sources';
}

// ── Field readers (only fields the read actually carries) ──────────────────

function numberField(meta: Record<string, unknown>, keys: readonly string[]): number | null {
  for (const key of keys) {
    const raw = meta[key];
    const n = typeof raw === 'number' ? raw : typeof raw === 'string' && raw.trim() !== '' ? Number(raw) : NaN;
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function stringField(meta: Record<string, unknown>, keys: readonly string[]): string | null {
  for (const key of keys) {
    const raw = meta[key];
    if (typeof raw === 'string' && raw.trim() !== '') return raw.trim();
  }
  return null;
}

function timeField(meta: Record<string, unknown>, keys: readonly string[]): number | null {
  for (const key of keys) {
    const raw = meta[key];
    if (typeof raw !== 'string' && typeof raw !== 'number') continue;
    const t = typeof raw === 'number' ? raw : Date.parse(raw);
    if (Number.isFinite(t)) return t;
  }
  return null;
}

const VALUE_KEYS = ['value', 'total_value', 'lifetime_value', 'ltv', 'revenue', 'value_usd', 'amount', 'amount_usd'] as const;
const TIME_KEYS = ['valid_from', 'first_seen', 'first_seen_at', 'first_observed_at', 'observed_at', 'occurred_at', 'created_at'] as const;
const LAT_KEYS = ['latitude', 'lat', 'geo_lat'] as const;
const LNG_KEYS = ['longitude', 'lng', 'lon', 'geo_lng', 'geo_lon'] as const;
const PLACE_KEYS = ['city', 'geo_city', 'region', 'geo_region', 'country', 'geo_country', 'country_code'] as const;

export function nodeValue(node: GraphNode): number | null {
  return numberField(node.metadata, VALUE_KEYS);
}

export function edgeValue(edge: GraphEdge): number | null {
  return numberField(edge.metadata, VALUE_KEYS);
}

export function edgeTime(edge: GraphEdge): number | null {
  return timeField(edge.metadata, TIME_KEYS);
}

export function nodeTime(node: GraphNode): number | null {
  return timeField(node.metadata, TIME_KEYS);
}

const AUTHORITY_EDGE = /DELEGAT|AUTHORI|ACTED_FOR|LAUNCHED_BY|GOVERNED_BY|APPROVE|OVERRIDES|REVOKES|SETS_RISK_POLICY|HIRED|DEPLOYED|FUNDS_AGENT/;

export function isAuthorityEdge(edge: GraphEdge): boolean {
  return AUTHORITY_EDGE.test(edge.relationType.toUpperCase());
}

export interface NodePlace {
  readonly label: string | null;
  readonly lat: number | null;
  readonly lng: number | null;
}

export function nodePlace(node: GraphNode): NodePlace {
  const lat = numberField(node.metadata, LAT_KEYS);
  const lng = numberField(node.metadata, LNG_KEYS);
  const valid = lat !== null && lng !== null && Math.abs(lat) <= 90 && Math.abs(lng) <= 180;
  const parts: string[] = [];
  const city = stringField(node.metadata, ['city', 'geo_city']);
  const country = stringField(node.metadata, ['country', 'geo_country', 'country_code']);
  if (city) parts.push(city);
  if (country) parts.push(country);
  const label = parts.length ? parts.join(', ') : stringField(node.metadata, PLACE_KEYS);
  return { label, lat: valid ? lat : null, lng: valid ? lng : null };
}

// ── Lenses ──────────────────────────────────────────────────────────────────

export type LensId = 'value' | 'activity' | 'authority' | 'risk' | 'time';

export const LENSES: ReadonlyArray<{ readonly id: LensId; readonly label: string; readonly note: string; readonly color: string }> = [
  { id: 'value', label: 'Value', note: 'Marker size follows value carried on the object or its links.', color: 'var(--ae-sage)' },
  { id: 'activity', label: 'Activity', note: 'Marker size follows how many relationships each object has.', color: 'var(--ae-blue)' },
  { id: 'authority', label: 'Authority', note: 'Delegation, approval and deployment links are highlighted.', color: 'var(--ae-violet)' },
  { id: 'risk', label: 'Risk', note: 'Marker colour follows the risk score the graph reports.', color: 'var(--ae-ember)' },
  { id: 'time', label: 'Time', note: 'Colour runs from early to late. Use the replay to step through.', color: 'var(--ae-teal)' },
];

export interface LensAvailability {
  readonly available: boolean;
  /** Why the lens cannot apply to this read (only set when unavailable). */
  readonly reason: string | null;
}

export interface GraphIndex {
  readonly byId: ReadonlyMap<string, GraphNode>;
  readonly degree: ReadonlyMap<string, number>;
  readonly authority: ReadonlyMap<string, number>;
  readonly value: ReadonlyMap<string, number>;
  readonly time: ReadonlyMap<string, number>;
  readonly lenses: Readonly<Record<LensId, LensAvailability>>;
  readonly timeRange: readonly [number, number] | null;
}

function bump(map: Map<string, number>, key: string, by: number) {
  map.set(key, (map.get(key) ?? 0) + by);
}

export function indexGraph(snapshot: Pick<GraphSnapshot, 'nodes' | 'edges'>): GraphIndex {
  const byId = new Map(snapshot.nodes.map(n => [n.id, n] as const));
  const degree = new Map<string, number>();
  const authority = new Map<string, number>();
  const value = new Map<string, number>();
  const time = new Map<string, number>();

  for (const node of snapshot.nodes) {
    const v = nodeValue(node);
    if (v !== null) value.set(node.id, v);
    const t = nodeTime(node);
    if (t !== null) time.set(node.id, t);
  }
  const nodeHasOwnValue = new Set(value.keys());
  for (const edge of snapshot.edges) {
    bump(degree, edge.source, 1);
    bump(degree, edge.target, 1);
    if (isAuthorityEdge(edge)) {
      bump(authority, edge.source, 1);
      bump(authority, edge.target, 1);
    }
    const v = edgeValue(edge);
    if (v !== null) {
      for (const end of [edge.source, edge.target]) if (!nodeHasOwnValue.has(end)) bump(value, end, v);
    }
    const t = edgeTime(edge);
    if (t !== null) {
      for (const end of [edge.source, edge.target]) {
        const prev = time.get(end);
        if (prev === undefined || t < prev) time.set(end, t);
      }
    }
  }

  const times = [...snapshot.edges.map(edgeTime), ...snapshot.nodes.map(nodeTime)].filter((t): t is number => t !== null);
  const timeRange: readonly [number, number] | null = times.length ? [Math.min(...times), Math.max(...times)] : null;
  const anyRisk = snapshot.nodes.some(n => typeof n.riskScore === 'number');
  const empty = snapshot.nodes.length === 0;

  const lenses: Record<LensId, LensAvailability> = {
    value: value.size > 0 ? { available: true, reason: null } : { available: false, reason: empty ? 'No objects in this read.' : 'This graph read reports no value on objects or links.' },
    activity: snapshot.edges.length > 0 ? { available: true, reason: null } : { available: false, reason: 'No relationships in this read yet.' },
    authority: authority.size > 0 ? { available: true, reason: null } : { available: false, reason: 'No delegation or approval links in this read.' },
    risk: anyRisk ? { available: true, reason: null } : { available: false, reason: empty ? 'No objects in this read.' : 'No risk scores are reported for these objects.' },
    time: timeRange ? { available: true, reason: null } : { available: false, reason: 'Objects and links in this read carry no timestamps.' },
  };

  return { byId, degree, authority, value, time, lenses, timeRange };
}

/** Raw lens measure for a node (null = the lens has nothing to say about it). */
export function lensMeasure(lens: LensId, node: GraphNode, index: GraphIndex): number | null {
  switch (lens) {
    case 'value': return index.value.get(node.id) ?? null;
    case 'activity': return index.degree.get(node.id) ?? 0;
    case 'authority': return index.authority.get(node.id) ?? 0;
    case 'risk': return typeof node.riskScore === 'number' ? node.riskScore : null;
    case 'time': return index.time.get(node.id) ?? null;
  }
}

/** Default lens: the first one the read supports, Activity when nothing does. */
export function defaultLens(index: GraphIndex): LensId {
  return LENSES.find(l => index.lenses[l.id].available)?.id ?? 'activity';
}

// ── Flow layout ─────────────────────────────────────────────────────────────

export interface FlowNode {
  readonly node: GraphNode;
  readonly column: FlowColumnId;
  /** 0–100 positions in the flow's coordinate space. */
  readonly x: number;
  readonly y: number;
  /** 0–1 lens weight relative to the strongest shown object. */
  readonly weight: number;
  readonly measure: number | null;
  /** Time-lens / replay: object appears after the replay cutoff. */
  readonly pending: boolean;
}

export interface FlowLink {
  readonly id: string;
  readonly edges: readonly GraphEdge[];
  readonly source: string;
  readonly target: string;
  readonly path: string;
  /** Curve midpoint, for a label when one end is selected. */
  readonly mid: { readonly x: number; readonly y: number };
  readonly authority: boolean;
  readonly pending: boolean;
}

export interface FlowLayout {
  readonly columns: ReadonlyArray<{ readonly id: FlowColumnId; readonly label: string; readonly x: number; readonly total: number; readonly hidden: number }>;
  readonly nodes: readonly FlowNode[];
  readonly links: readonly FlowLink[];
  readonly rows: number;
}

const COLUMN_X: Record<FlowColumnId, number> = { sources: 12, people: 37, agents: 63, destinations: 88 };

export function buildFlow(
  snapshot: Pick<GraphSnapshot, 'nodes' | 'edges'>,
  index: GraphIndex,
  lens: LensId,
  options: { readonly perColumn?: number; readonly cutoff?: number | null } = {},
): FlowLayout {
  const perColumn = options.perColumn ?? 7;
  const cutoff = options.cutoff ?? null;
  const groups: Record<FlowColumnId, GraphNode[]> = { sources: [], people: [], agents: [], destinations: [] };
  for (const node of snapshot.nodes) groups[flowColumn(node.kind)].push(node);

  // Rank inside each lane by the lens (falling back to connectedness), so the
  // lane shows its most relevant objects and says how many it left out.
  const rank = (node: GraphNode) => {
    const m = lensMeasure(lens, node, index);
    if (lens === 'time') return m === null ? Number.NEGATIVE_INFINITY : -m; // earliest first
    return m ?? -1;
  };
  const shown = new Map<string, FlowColumnId>();
  const columns = FLOW_COLUMNS.map(col => {
    const sorted = [...groups[col.id]].sort((a, b) => rank(b) - rank(a) || (index.degree.get(b.id) ?? 0) - (index.degree.get(a.id) ?? 0) || a.label.localeCompare(b.label));
    const visible = sorted.slice(0, perColumn);
    for (const n of visible) shown.set(n.id, col.id);
    return { ...col, x: COLUMN_X[col.id], total: sorted.length, hidden: Math.max(0, sorted.length - visible.length), visible };
  });
  const rows = Math.max(1, ...columns.map(c => c.visible.length));

  const measures = columns.flatMap(c => c.visible.map(n => lensMeasure(lens, n, index))).filter((m): m is number => m !== null);
  const lo = measures.length ? Math.min(...measures) : 0;
  const hi = measures.length ? Math.max(...measures) : 0;
  const norm = (m: number | null) => (m === null ? 0 : hi === lo ? (hi > 0 ? 1 : 0) : (m - lo) / (hi - lo));

  const nodes: FlowNode[] = [];
  const pos = new Map<string, { x: number; y: number }>();
  for (const col of columns) {
    col.visible.forEach((node, i) => {
      const y = ((i + 1) / (col.visible.length + 1)) * 100;
      pos.set(node.id, { x: col.x, y });
      const measure = lensMeasure(lens, node, index);
      const t = index.time.get(node.id);
      nodes.push({ node, column: col.id, x: col.x, y, weight: norm(measure), measure, pending: cutoff !== null && t !== undefined && t > cutoff });
    });
  }

  const pairs = new Map<string, GraphEdge[]>();
  for (const edge of snapshot.edges) {
    if (!shown.has(edge.source) || !shown.has(edge.target) || edge.source === edge.target) continue;
    const key = [edge.source, edge.target].sort().join('|');
    const list = pairs.get(key);
    if (list) list.push(edge);
    else pairs.set(key, [edge]);
  }
  const links: FlowLink[] = [];
  for (const [key, edges] of pairs) {
    const first = edges[0]!;
    const a = pos.get(first.source)!;
    const b = pos.get(first.target)!;
    const mid = (a.x + b.x) / 2;
    const swing = a.x === b.x ? 10 : 0;
    const path = `M${a.x} ${a.y} C${mid + swing} ${a.y},${mid + swing} ${b.y},${b.x} ${b.y}`;
    const times = edges.map(edgeTime).filter((t): t is number => t !== null);
    links.push({
      id: key,
      edges,
      source: first.source,
      target: first.target,
      path,
      mid: { x: (a.x + 6 * (mid + swing) + b.x) / 8, y: (a.y + 3 * a.y + 3 * b.y + b.y) / 8 },
      authority: edges.some(isAuthorityEdge),
      pending: cutoff !== null && times.length > 0 && Math.min(...times) > cutoff,
    });
  }

  return {
    columns: columns.map(({ visible: _visible, ...rest }) => rest),
    nodes,
    links,
    rows,
  };
}

// ── Lens summary rows ───────────────────────────────────────────────────────

export interface LensRow {
  readonly id: string;
  readonly label: string;
  readonly kind: string;
  readonly value: string;
  /** 0–100 bar width. */
  readonly share: number;
}

export function formatMeasure(lens: LensId, measure: number | null): string {
  if (measure === null) return '—';
  switch (lens) {
    case 'value': return measure >= 1000 ? `${(measure / 1000).toFixed(measure >= 10_000 ? 0 : 1)}k` : measure.toLocaleString('en-US', { maximumFractionDigits: 2 });
    case 'activity': return `${measure} link${measure === 1 ? '' : 's'}`;
    case 'authority': return `${measure} authority link${measure === 1 ? '' : 's'}`;
    case 'risk': return measure.toFixed(2);
    case 'time': return new Date(measure).toISOString().slice(0, 10);
  }
}

export function lensRows(snapshot: Pick<GraphSnapshot, 'nodes'>, index: GraphIndex, lens: LensId, limit = 6): LensRow[] {
  const scored = snapshot.nodes
    .map(node => ({ node, m: lensMeasure(lens, node, index) }))
    .filter((r): r is { node: GraphNode; m: number } => r.m !== null && (lens === 'time' || r.m > 0));
  scored.sort((a, b) => (lens === 'time' ? a.m - b.m : b.m - a.m));
  const top = scored.slice(0, limit);
  const values = top.map(r => r.m);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  return top.map(({ node, m }) => ({
    id: node.id,
    label: node.label,
    kind: node.kind,
    value: formatMeasure(lens, m),
    share: lens === 'time'
      ? (hi === lo ? 100 : Math.round(((m - lo) / (hi - lo)) * 100))
      : (hi > 0 ? Math.max(4, Math.round((m / hi) * 100)) : 0),
  }));
}

// ── Places (globe + per-place panel) ────────────────────────────────────────

export interface Place {
  readonly key: string;
  readonly label: string;
  readonly lat: number | null;
  readonly lng: number | null;
  readonly nodeIds: readonly string[];
}

export interface PlacesSummary {
  readonly places: readonly Place[];
  /** Objects whose read carries no location at all. */
  readonly unknown: number;
}

export function buildPlaces(nodes: readonly GraphNode[]): PlacesSummary {
  const map = new Map<string, { label: string; lat: number | null; lng: number | null; ids: string[] }>();
  let unknown = 0;
  for (const node of nodes) {
    const place = nodePlace(node);
    if (!place.label && place.lat === null) {
      unknown += 1;
      continue;
    }
    const key = place.label ?? `${place.lat!.toFixed(1)},${place.lng!.toFixed(1)}`;
    const entry = map.get(key);
    if (entry) {
      entry.ids.push(node.id);
      if (entry.lat === null && place.lat !== null) {
        entry.lat = place.lat;
        entry.lng = place.lng;
      }
    } else {
      map.set(key, { label: place.label ?? `${place.lat!.toFixed(2)}, ${place.lng!.toFixed(2)}`, lat: place.lat, lng: place.lng, ids: [node.id] });
    }
  }
  const places = [...map.entries()]
    .map(([key, e]) => ({ key, label: e.label, lat: e.lat, lng: e.lng, nodeIds: e.ids }))
    .sort((a, b) => b.nodeIds.length - a.nodeIds.length || a.label.localeCompare(b.label));
  return { places, unknown };
}

// ── Destinations for a selected object ─────────────────────────────────────

export interface ObjectLink {
  readonly label: string;
  readonly to: string;
}

/** Existing routes an object can open, following GraphPage's inspector rules. */
export function objectLinks(node: GraphNode, clusters: readonly GraphCluster[]): ObjectLink[] {
  const out: ObjectLink[] = [];
  const kind = node.kind.toLowerCase();
  if (kind === 'entity') out.push({ label: 'Open profile', to: `/users/${encodeURIComponent(node.id)}` });
  if (kind === 'agent') out.push({ label: 'Open agent', to: `/agents/${encodeURIComponent(node.id)}` });
  if (clusters.some(c => c.id === node.id)) out.push({ label: 'Open cluster', to: `/clusters/${encodeURIComponent(node.id)}` });
  const campaign = node.metadata['attributed_campaign_id'] ?? node.metadata['campaign_id'];
  if (typeof campaign === 'string' && campaign) out.push({ label: 'Open campaign', to: `/campaigns/${encodeURIComponent(campaign)}` });
  return out;
}
