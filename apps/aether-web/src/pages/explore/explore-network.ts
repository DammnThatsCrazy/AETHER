import type { GraphEdge, GraphNode } from '@aether-app/components/graph/graph-canvas';
import type { GraphSnapshot } from './explore-model';

/**
 * Pure derivations behind the Graph network view (Claude Design handoff:
 * Aether Explore → Graph): principal cards with the agents, wallets,
 * applications and handles they own or use, the labelled links between
 * principals, the type counts in the toolbar, hop reach from a scoped object
 * and the path strip. Everything is read from the same graph read the rest of
 * the page uses; a money label appears only where an edge carries an amount.
 */

// ── Categories ──────────────────────────────────────────────────────────────

export type NodeCategory =
  | 'people'
  | 'organizations'
  | 'agents'
  | 'wallets'
  | 'applications'
  | 'syndicates'
  | 'devices'
  | 'handles'
  | 'other';

export const CATEGORIES: ReadonlyArray<{
  readonly id: NodeCategory;
  readonly label: string;
  readonly singular: string;
  readonly icon: string;
  readonly color: string;
}> = [
  { id: 'people', label: 'People', singular: 'Person', icon: 'user-round', color: 'var(--ae-blue)' },
  { id: 'organizations', label: 'Organizations', singular: 'Organization', icon: 'building-2', color: 'var(--ae-amber)' },
  { id: 'agents', label: 'Agents', singular: 'Agent', icon: 'bot', color: 'var(--ae-sage)' },
  { id: 'syndicates', label: 'Syndicates', singular: 'Syndicate', icon: 'users-round', color: 'var(--ae-ember)' },
  { id: 'applications', label: 'Applications', singular: 'Application', icon: 'app-window', color: 'var(--ae-ink)' },
  { id: 'wallets', label: 'Wallets', singular: 'Wallet', icon: 'wallet-cards', color: 'var(--ae-violet)' },
  { id: 'devices', label: 'Devices', singular: 'Device', icon: 'smartphone', color: 'var(--ae-mute)' },
  { id: 'handles', label: 'Handles', singular: 'Handle', icon: 'contact-round', color: 'var(--ae-teal)' },
  { id: 'other', label: 'Other', singular: 'Object', icon: 'circle-help', color: 'var(--ae-faint)' },
];

export function categoryMeta(id: NodeCategory) {
  return CATEGORIES.find(c => c.id === id)!;
}

export function nodeCategory(kind: string): NodeCategory {
  const k = kind.toLowerCase();
  if (/wallet/.test(k)) return 'wallets';
  if (/agent|bot/.test(k)) return 'agents';
  if (/syndicate|cluster|cohort|segment|group|community/.test(k)) return 'syndicates';
  if (/device|browser|session/.test(k)) return 'devices';
  if (/handle|social|email|phone|username|identifier/.test(k)) return 'handles';
  if (/org|company|merchant|store|business|vendor|supplier|venue|brand|exchange/.test(k)) return 'organizations';
  if (/person|user|human|customer|profile|identity|entity|contact|member|household|creator/.test(k)) return 'people';
  if (/source|app|platform|integration|tool|channel|campaign|service|protocol|dapp/.test(k)) return 'applications';
  return 'other';
}

export type Perspective = 'all' | 'human' | 'agent';

const HUMAN_PRINCIPALS: ReadonlySet<NodeCategory> = new Set(['people', 'organizations']);
const AGENT_PRINCIPALS: ReadonlySet<NodeCategory> = new Set(['agents']);

// ── Edge reading ────────────────────────────────────────────────────────────

const AMOUNT_KEYS = ['amount', 'amount_usd', 'value', 'value_usd', 'volume_usd', 'total', 'total_usd', 'price', 'spend_usd'] as const;

export interface EdgeAmount {
  readonly amount: number;
  /** ISO currency when the edge says so (key suffix `_usd` or a `currency` field). */
  readonly currency: string | null;
}

export function edgeAmount(edge: Pick<GraphEdge, 'metadata'>): EdgeAmount | null {
  const meta = edge.metadata;
  for (const key of AMOUNT_KEYS) {
    const raw = meta[key];
    const n = typeof raw === 'number' ? raw : typeof raw === 'string' && raw.trim() !== '' ? Number(raw) : NaN;
    if (!Number.isFinite(n)) continue;
    const declared = typeof meta['currency'] === 'string' && meta['currency'].trim() ? String(meta['currency']).trim().toUpperCase() : null;
    return { amount: n, currency: declared ?? (key.endsWith('_usd') ? 'USD' : null) };
  }
  return null;
}

export function formatAmount({ amount, currency }: EdgeAmount): string {
  const abs = Math.abs(amount);
  const short = abs >= 1_000_000
    ? `${(amount / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`
    : abs >= 1000
      ? `${(amount / 1000).toFixed(abs >= 10_000 ? 0 : 1)}K`
      : amount.toLocaleString('en-US', { maximumFractionDigits: 2 });
  if (currency === 'USD') return `$${short}`;
  return currency ? `${short} ${currency}` : short;
}

export function relationLabel(edge: Pick<GraphEdge, 'relationType'>): string {
  return edge.relationType.replace(/_/g, ' ').trim().toLowerCase() || 'related';
}

export type LinkKind = 'money' | 'buys' | 'risk' | 'campaign' | 'relationship';

export const LINK_KINDS: ReadonlyArray<{ readonly id: LinkKind; readonly label: string; readonly color: string; readonly dash?: string }> = [
  { id: 'money', label: 'sent money', color: 'var(--ae-amber)' },
  { id: 'buys', label: 'buys from', color: 'var(--ae-blue)' },
  { id: 'risk', label: 'flagged risk', color: 'var(--ae-ember)' },
  { id: 'campaign', label: 'campaign touch', color: 'var(--ae-violet)', dash: '5 4' },
  { id: 'relationship', label: 'relationship', color: 'var(--ae-mute)', dash: '1.5 3' },
];

export function linkKind(edge: Pick<GraphEdge, 'relationType' | 'metadata'>): LinkKind {
  const t = edge.relationType.toUpperCase();
  if (/FLAG|FRAUD|RISK|SANCTION|BLOCK/.test(t)) return 'risk';
  if (/PURCHAS|BUY|BOUGHT|ORDER|CHECKOUT/.test(t)) return 'buys';
  if (/CAMPAIGN|ATTRIBUT|TOUCH|EXPOS|NOTIF|IMPRESS|CLICK/.test(t)) return 'campaign';
  if (edgeAmount(edge) !== null || /PAY|SEND|SENT|TRANSFER|FUND|TIP|REFUND/.test(t)) return 'money';
  return 'relationship';
}

/** Label for a link: its amount when the edge carries one, otherwise its relation. */
export function linkLabel(edge: Pick<GraphEdge, 'relationType' | 'metadata'>): string {
  const amount = edgeAmount(edge);
  return amount ? formatAmount(amount) : relationLabel(edge);
}

function edgeTimestamp(edge: GraphEdge): number | null {
  for (const key of ['valid_from', 'observed_at', 'occurred_at', 'created_at', 'first_seen_at']) {
    const raw = edge.metadata[key];
    if (typeof raw !== 'string' && typeof raw !== 'number') continue;
    const t = typeof raw === 'number' ? raw : Date.parse(raw);
    if (Number.isFinite(t)) return t;
  }
  return null;
}

// ── Reach ───────────────────────────────────────────────────────────────────

type Adjacency = Map<string, Array<{ readonly other: string; readonly edge: GraphEdge }>>;

export function adjacency(edges: readonly GraphEdge[]): Adjacency {
  const adj: Adjacency = new Map();
  for (const edge of edges) {
    if (edge.source === edge.target) continue;
    if (!adj.has(edge.source)) adj.set(edge.source, []);
    if (!adj.has(edge.target)) adj.set(edge.target, []);
    adj.get(edge.source)!.push({ other: edge.target, edge });
    adj.get(edge.target)!.push({ other: edge.source, edge });
  }
  return adj;
}

/** Undirected hop distance from `startId` (unbounded when `maxHops` is null). */
export function hopDistances(startId: string, adj: Adjacency, maxHops: number | null): Map<string, number> {
  const dist = new Map<string, number>([[startId, 0]]);
  const queue = [startId];
  while (queue.length) {
    const id = queue.shift()!;
    const d = dist.get(id)!;
    if (maxHops !== null && d >= maxHops) continue;
    for (const { other } of adj.get(id) ?? []) {
      if (dist.has(other)) continue;
      dist.set(other, d + 1);
      queue.push(other);
    }
  }
  return dist;
}

// ── Network (cards) ─────────────────────────────────────────────────────────

export interface CardRow {
  readonly node: GraphNode;
  readonly category: NodeCategory;
  readonly edge: GraphEdge;
  /** Relation, or the amount when the edge carries one. */
  readonly label: string;
}

export interface PrincipalCard {
  readonly node: GraphNode;
  readonly category: NodeCategory;
  readonly rows: readonly CardRow[];
  readonly hidden: number;
  readonly distance: number | null;
}

export interface CardLink {
  readonly id: string;
  readonly source: string;
  readonly target: string;
  readonly kind: LinkKind;
  readonly label: string;
  readonly edges: readonly GraphEdge[];
}

export interface NetworkOptions {
  readonly scopeId: string | null;
  /** Hop limit from the scope (null = unlimited). Ignored without a scope. */
  readonly hops: number | null;
  readonly perspective: Perspective;
  readonly hiddenCategories: ReadonlySet<NodeCategory>;
  readonly search: string;
  readonly rowsPerCard?: number;
}

export interface NetworkLayout {
  readonly cards: readonly PrincipalCard[];
  readonly links: readonly CardLink[];
  /** Objects per category inside the current reach (before category toggles). */
  readonly counts: ReadonlyMap<NodeCategory, number>;
  /** The scoped object, when the scope id is in this read. */
  readonly scope: GraphNode | null;
}

export function buildNetwork(snapshot: Pick<GraphSnapshot, 'nodes' | 'edges'>, options: NetworkOptions): NetworkLayout {
  const byId = new Map(snapshot.nodes.map(n => [n.id, n] as const));
  const adj = adjacency(snapshot.edges.filter(e => byId.has(e.source) && byId.has(e.target)));
  const scope = options.scopeId ? byId.get(options.scopeId) ?? null : null;
  const distances = scope ? hopDistances(scope.id, adj, options.hops) : null;
  const inReach = (id: string) => (distances ? distances.has(id) : true);

  const category = new Map(snapshot.nodes.map(n => [n.id, nodeCategory(n.kind)] as const));
  const counts = new Map<NodeCategory, number>();
  for (const node of snapshot.nodes) {
    if (!inReach(node.id)) continue;
    const c = category.get(node.id)!;
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }

  const visible = (id: string) => inReach(id) && !options.hiddenCategories.has(category.get(id)!);
  const humanPrincipal = (id: string) => HUMAN_PRINCIPALS.has(category.get(id)!);
  const isPrincipal = (id: string): boolean => {
    const c = category.get(id)!;
    if (options.perspective === 'human') return HUMAN_PRINCIPALS.has(c);
    if (options.perspective === 'agent') return AGENT_PRINCIPALS.has(c);
    if (HUMAN_PRINCIPALS.has(c)) return true;
    // In "All", an agent gets its own card only when no person or
    // organization in this read owns or uses it.
    if (AGENT_PRINCIPALS.has(c)) return !(adj.get(id) ?? []).some(({ other }) => humanPrincipal(other));
    return false;
  };

  const perCard = options.rowsPerCard ?? 4;
  const needle = options.search.trim().toLowerCase();
  const matches = (node: GraphNode) => `${node.label} ${node.id} ${node.kind}`.toLowerCase().includes(needle);

  const principals = snapshot.nodes.filter(n => visible(n.id) && isPrincipal(n.id));
  const principalIds = new Set(principals.map(n => n.id));
  const cards: PrincipalCard[] = [];
  for (const node of principals) {
    const seen = new Set<string>();
    const rows: CardRow[] = [];
    for (const { other, edge } of adj.get(node.id) ?? []) {
      if (principalIds.has(other) || isPrincipal(other) || !visible(other) || seen.has(other)) continue;
      seen.add(other);
      rows.push({ node: byId.get(other)!, category: category.get(other)!, edge, label: linkLabel(edge) });
    }
    if (needle && !matches(node) && !rows.some(r => matches(r.node))) continue;
    const order = CATEGORIES.map(c => c.id);
    rows.sort((a, b) => order.indexOf(a.category) - order.indexOf(b.category) || a.node.label.localeCompare(b.node.label));
    cards.push({
      node,
      category: category.get(node.id)!,
      rows: rows.slice(0, perCard),
      hidden: Math.max(0, rows.length - perCard),
      distance: distances?.get(node.id) ?? null,
    });
  }

  const shown = new Set(cards.map(c => c.node.id));
  const pairs = new Map<string, GraphEdge[]>();
  for (const edge of snapshot.edges) {
    if (edge.source === edge.target || !shown.has(edge.source) || !shown.has(edge.target)) continue;
    const key = [edge.source, edge.target].sort().join('|');
    const list = pairs.get(key);
    if (list) list.push(edge);
    else pairs.set(key, [edge]);
  }
  const links: CardLink[] = [...pairs.entries()].map(([key, edges]) => {
    // Prefer the edge that carries an amount, so a money flow is labelled as one.
    const lead = edges.find(e => edgeAmount(e) !== null) ?? edges[0]!;
    return { id: key, source: lead.source, target: lead.target, kind: linkKind(lead), label: linkLabel(lead), edges };
  });

  return { cards: orderCards(cards, links, scope?.id ?? null), links, counts, scope };
}

/** Scope first, then walk linked principals so connected cards sit side by side. */
function orderCards(cards: readonly PrincipalCard[], links: readonly CardLink[], scopeId: string | null): PrincipalCard[] {
  const degree = new Map<string, number>();
  const linked = new Map<string, string[]>();
  for (const link of links) {
    for (const [a, b] of [[link.source, link.target], [link.target, link.source]] as const) {
      degree.set(a, (degree.get(a) ?? 0) + 1);
      if (!linked.has(a)) linked.set(a, []);
      linked.get(a)!.push(b);
    }
  }
  const weight = (c: PrincipalCard) => (degree.get(c.node.id) ?? 0) * 10 + c.rows.length + c.hidden;
  const rest = [...cards].sort((a, b) =>
    (a.node.id === scopeId ? -1 : b.node.id === scopeId ? 1 : 0)
    || (a.distance ?? 99) - (b.distance ?? 99)
    || weight(b) - weight(a)
    || a.node.label.localeCompare(b.node.label));
  const byId = new Map(rest.map(c => [c.node.id, c] as const));
  const out: PrincipalCard[] = [];
  const placed = new Set<string>();
  for (const seed of rest) {
    if (placed.has(seed.node.id)) continue;
    const queue = [seed.node.id];
    while (queue.length) {
      const id = queue.shift()!;
      if (placed.has(id)) continue;
      placed.add(id);
      out.push(byId.get(id)!);
      const next = (linked.get(id) ?? []).filter(n => !placed.has(n)).sort((a, b) => rest.indexOf(byId.get(a)!) - rest.indexOf(byId.get(b)!));
      queue.push(...next);
    }
  }
  return out;
}

// ── Inspector ───────────────────────────────────────────────────────────────

export interface Connection {
  readonly node: GraphNode;
  readonly category: NodeCategory;
  readonly edge: GraphEdge;
  readonly label: string;
}

export function directConnections(nodeId: string, snapshot: Pick<GraphSnapshot, 'nodes' | 'edges'>): Connection[] {
  const byId = new Map(snapshot.nodes.map(n => [n.id, n] as const));
  const out: Connection[] = [];
  const seen = new Set<string>();
  for (const edge of snapshot.edges) {
    if (edge.source !== nodeId && edge.target !== nodeId) continue;
    const otherId = edge.source === nodeId ? edge.target : edge.source;
    const other = byId.get(otherId);
    if (!other || otherId === nodeId) continue;
    const key = `${otherId}|${edge.relationType}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ node: other, category: nodeCategory(other.kind), edge, label: linkLabel(edge) });
  }
  const order = CATEGORIES.map(c => c.id);
  return out.sort((a, b) => order.indexOf(a.category) - order.indexOf(b.category) || a.node.label.localeCompare(b.node.label));
}

// ── Path strip ──────────────────────────────────────────────────────────────

export interface PathStep {
  readonly node: GraphNode;
  /** Relation to the next step (null on the last). */
  readonly relation: string | null;
}

export interface ReadPath {
  readonly steps: readonly PathStep[];
  readonly hops: number;
  readonly firstObserved: number | null;
  readonly lastObserved: number | null;
  /** Lowest edge confidence on the path, only when every edge reports one. */
  readonly confidence: number | null;
}

/** Shortest path through this read (undirected), or null when none exists. */
export function findReadPath(fromId: string, toId: string, snapshot: Pick<GraphSnapshot, 'nodes' | 'edges'>): ReadPath | null {
  const byId = new Map(snapshot.nodes.map(n => [n.id, n] as const));
  if (!byId.has(fromId) || !byId.has(toId) || fromId === toId) return null;
  const adj = adjacency(snapshot.edges);
  const prev = new Map<string, { from: string; edge: GraphEdge }>();
  const seen = new Set([fromId]);
  const queue = [fromId];
  while (queue.length && !seen.has(toId)) {
    const id = queue.shift()!;
    for (const { other, edge } of adj.get(id) ?? []) {
      if (seen.has(other)) continue;
      seen.add(other);
      prev.set(other, { from: id, edge });
      queue.push(other);
    }
  }
  if (!seen.has(toId)) return null;
  const chain: Array<{ id: string; edge: GraphEdge | null }> = [{ id: toId, edge: null }];
  let cur = toId;
  while (cur !== fromId) {
    const p = prev.get(cur)!;
    chain.unshift({ id: p.from, edge: p.edge });
    cur = p.from;
  }
  const edges = chain.map(c => c.edge).filter((e): e is GraphEdge => e !== null);
  const times = edges.map(edgeTimestamp).filter((t): t is number => t !== null);
  const confidences = edges.map(e => e.metadata['confidence']).filter((c): c is number => typeof c === 'number');
  return {
    steps: chain.map(c => ({ node: byId.get(c.id)!, relation: c.edge ? relationLabel(c.edge) : null })),
    hops: edges.length,
    firstObserved: times.length ? Math.min(...times) : null,
    lastObserved: times.length ? Math.max(...times) : null,
    confidence: confidences.length === edges.length && edges.length > 0 ? Math.min(...confidences) : null,
  };
}

/** Only the part of the read within `hops` of `centerId` (the trace's scope). */
export function scopeSnapshot<T extends Pick<GraphSnapshot, 'nodes' | 'edges'>>(snapshot: T, centerId: string | null, hops: number): T {
  if (!centerId || !snapshot.nodes.some(n => n.id === centerId)) return snapshot;
  const reach = hopDistances(centerId, adjacency(snapshot.edges), hops);
  return {
    ...snapshot,
    nodes: snapshot.nodes.filter(n => reach.has(n.id)),
    edges: snapshot.edges.filter(e => reach.has(e.source) && reach.has(e.target)),
  };
}

export function initials(label: string): string {
  const words = label.replace(/[^\p{L}\p{N}\s]/gu, ' ').trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  if (words.length === 1) return words[0]!.slice(0, 2).toUpperCase();
  return (words[0]![0]! + words[1]![0]!).toUpperCase();
}
