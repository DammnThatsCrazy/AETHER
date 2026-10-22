/**
 * Pure read-model helpers for Profile 360 (design: Aether Profile 360 v2).
 *
 * Every value here is derived from a response the page already fetches
 * (profile summary, entity graph, identifiers, timeline). Nothing is
 * synthesised: a field the backend did not return stays `null` so the view
 * can say "not reported" instead of inventing a number.
 */

export type Row = Record<string, unknown>;

export function asRecord(v: unknown): Row {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Row) : {};
}

export function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

export function str(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  return s === '' ? null : s;
}

export function num(v: unknown): number | null {
  const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
}

export function humanize(v: string): string {
  return v.replace(/[_-]+/g, ' ');
}

/** Two-letter monogram for the avatar; an opaque id gets its first two chars. */
export function initials(name: string): string {
  const words = name.split(/[\s._@-]+/).filter(Boolean);
  if (words.length >= 2) return `${words[0]![0]}${words[1]![0]}`.toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

/** "12m ago" style recency; `null` for an absent or unparseable timestamp. */
export function ago(iso: unknown): string | null {
  const s = str(iso);
  if (!s) return null;
  const t = Date.parse(s);
  if (Number.isNaN(t)) return null;
  const mins = Math.round((Date.now() - t) / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 60) return `${days}d ago`;
  const months = Math.round(days / 30);
  if (months < 24) return `${months}mo ago`;
  return `${Math.round(months / 12)}y ago`;
}

// ── Header identity ─────────────────────────────────────────────────────────

export interface ProfileIdentity {
  readonly name: string;
  /** True when the name is just the opaque profile id (render it mono). */
  readonly nameIsId: boolean;
  readonly kind: string | null;
  /** Entity registry state: true known, false no record, null not reported. */
  readonly known: boolean | null;
  readonly lastSeenAt: string | null;
  readonly firstSeenAt: string | null;
  readonly counts: {
    readonly agents: number | null;
    readonly wallets: number | null;
    readonly journeys: number | null;
  };
}

/**
 * Reads the profile summary. The canonical `/v1/profile/{id}/summary` returns
 * `{ snapshot: { entity, counts, ... } }`; older read models put flat fields
 * (`display_name`, `last_seen_at`) at the top level. Both are honoured.
 */
export function profileIdentity(summary: unknown, profileId: string): ProfileIdentity {
  const s = asRecord(summary);
  const snapshot = asRecord(s.snapshot);
  const entity = asRecord(snapshot.entity);
  const counts = asRecord(snapshot.counts);
  const name = str(entity.displayLabel) ?? str(s.display_name) ?? str(s.name) ?? profileId;
  const type = str(entity.type) ?? str(s.entity_type);
  return {
    name,
    nameIsId: name === profileId,
    kind: type && type !== 'unknown' ? humanize(type) : null,
    known: typeof entity.known === 'boolean' ? entity.known : null,
    lastSeenAt: str(s.last_seen_at),
    firstSeenAt: str(s.first_seen_at) ?? str(asRecord(entity.timestamps).createdAt),
    counts: {
      agents: num(counts.agents),
      wallets: num(counts.wallets),
      journeys: num(counts.journey_chains),
    },
  };
}

// ── Graph ───────────────────────────────────────────────────────────────────

export type NetworkGroup = 'people' | 'agents' | 'assets' | 'other';

export const NETWORK_GROUPS: ReadonlyArray<{ readonly key: NetworkGroup; readonly label: string; readonly color: string }> = [
  { key: 'people', label: 'People and organizations', color: 'var(--ae-blue)' },
  { key: 'agents', label: 'Agents', color: 'var(--ae-solar)' },
  { key: 'assets', label: 'Wallets and devices', color: 'var(--ae-teal)' },
  { key: 'other', label: 'Other', color: 'var(--ae-mute)' },
];

export interface NetworkNode {
  readonly id: string;
  readonly label: string;
  readonly kind: string | null;
  readonly actorClass: string | null;
  readonly group: NetworkGroup;
  readonly trust: number | null;
}

export interface NetworkLink {
  readonly id: string;
  readonly other: string;
  readonly relation: string | null;
  readonly interactionClass: string | null;
  readonly weight: number | null;
  readonly confidence: number | null;
  readonly inferred: boolean;
  readonly volumeUsd: number | null;
}

export interface ProfileNetwork {
  readonly nodes: NetworkNode[];
  readonly links: NetworkLink[];
  /** Neighbour count per interaction class (H2H, H2A, ...). */
  readonly byClass: ReadonlyArray<{ readonly cls: string; readonly count: number }>;
}

const AGENT_KINDS = new Set(['agent', 'bot']);
const ASSET_KINDS = new Set(['wallet', 'device', 'session', 'contract']);
const PEOPLE_KINDS = new Set(['human', 'user', 'person', 'profile', 'organization', 'brand', 'governance_org', 'merchant']);

export function networkGroup(kind: string | null, actorClass: string | null): NetworkGroup {
  const k = (kind ?? '').toLowerCase();
  if (actorClass === 'A' || AGENT_KINDS.has(k)) return 'agents';
  if (ASSET_KINDS.has(k)) return 'assets';
  if (actorClass === 'H' || PEOPLE_KINDS.has(k)) return 'people';
  return 'other';
}

/**
 * Normalises the entity-graph response around `rootId`: the root is removed
 * from the neighbour list and every edge is expressed as a link to "the other"
 * entity. Nodes that only appear on an edge still get a (kind-only) node.
 */
export function profileNetwork(graph: unknown, rootId: string): ProfileNetwork {
  const g = asRecord(graph);
  const byId = new Map<string, NetworkNode>();
  for (const raw of asList(g.nodes)) {
    const n = asRecord(raw);
    const id = str(n.entity_id) ?? str(n.id);
    if (!id || id === rootId) continue;
    const kind = str(n.kind) ?? str(n.type);
    const actorClass = str(n.actor_class);
    byId.set(id, {
      id,
      label: str(n.display_name) ?? str(n.label) ?? id,
      kind,
      actorClass,
      group: networkGroup(kind, actorClass),
      trust: num(n.trust_score),
    });
  }
  const links: NetworkLink[] = [];
  const classCount = new Map<string, number>();
  asList(g.edges).forEach((raw, index) => {
    const e = asRecord(raw);
    // Profile-graph rows use from_/to_entity_id; /v1/entities/{id}/graph uses source_/target_entity_id.
    const from = str(e.from_entity_id) ?? str(e.source_entity_id);
    const to = str(e.to_entity_id) ?? str(e.target_entity_id);
    const other = from === rootId ? to : to === rootId ? from : (to ?? from);
    if (!other || other === rootId) return;
    const otherKind = from === rootId ? str(e.to_kind) : str(e.from_kind);
    if (!byId.has(other)) {
      byId.set(other, { id: other, label: other, kind: otherKind, actorClass: null, group: networkGroup(otherKind, null), trust: null });
    }
    const cls = str(e.interaction_class);
    if (cls) classCount.set(cls, (classCount.get(cls) ?? 0) + 1);
    links.push({
      id: str(e.edge_id) ?? str(e.id) ?? `${from ?? '?'}-${to ?? '?'}-${index}`,
      other,
      relation: str(e.relation_type) ?? str(e.edge_type),
      interactionClass: cls,
      weight: num(e.weight),
      confidence: num(e.confidence),
      inferred: e.is_inferred === true,
      volumeUsd: num(e.volume_usd),
    });
  });
  return {
    nodes: [...byId.values()],
    links,
    byClass: [...classCount.entries()].map(([cls, count]) => ({ cls, count })).sort((a, b) => b.count - a.count),
  };
}

// ── Identifiers ─────────────────────────────────────────────────────────────

// Kinds as returned by /v1/profile/{id}/identifiers (ProfileResolver.get_all_identifiers).
export const IDENTIFIER_KINDS = ['emails', 'phones', 'devices', 'wallets', 'social', 'sessions'] as const;

export function identifierGroups(ids: unknown): Array<{ readonly kind: string; readonly values: string[] }> {
  // The route wraps the record: { user_id, identifiers: { wallets: [...], ... } }.
  const outer = asRecord(ids);
  const r = outer.identifiers && typeof outer.identifiers === 'object' ? asRecord(outer.identifiers) : outer;
  return IDENTIFIER_KINDS
    .map(kind => ({ kind, values: asList(r[kind]).map(v => str(typeof v === 'object' ? (asRecord(v).value ?? asRecord(v).id) : v)).filter((v): v is string => v !== null) }))
    .filter(g => g.values.length > 0);
}

// ── Timeline ────────────────────────────────────────────────────────────────

export interface TimelineEvent {
  readonly key: string;
  readonly type: string;
  readonly at: string | null;
  readonly source: string | null;
  readonly detail: string | null;
}

export function timelineEvents(data: unknown): TimelineEvent[] {
  const d = asRecord(data);
  const raw = asList(d.events ?? d.items ?? data);
  return raw
    .map((item, index) => {
      const e = asRecord(item);
      const props = asRecord(e.properties);
      const type = str(e.event_type) ?? str(e.type) ?? str(e.name) ?? 'event';
      return {
        key: str(e.event_id) ?? str(e.id) ?? `${type}-${index}`,
        type,
        at: str(e.timestamp) ?? str(e.occurred_at) ?? str(e.created_at),
        source: str(e.source) ?? str(e.platform) ?? str(e.channel),
        detail: str(props.page_title) ?? str(props.url) ?? str(e.url) ?? str(props.name) ?? null,
      };
    })
    .sort((a, b) => (b.at ? Date.parse(b.at) : 0) - (a.at ? Date.parse(a.at) : 0));
}
