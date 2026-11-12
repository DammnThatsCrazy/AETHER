import { useMutation, useQuery } from '@aether/ui';
import { useMeProfile } from '@aether-app/features/account/use-me-profile';
import { api } from '@aether-app/lib/api/endpoints';

/**
 * Syndicates read model. A syndicate is one of two real things:
 *
 * - a rule-defined population group (`/v1/population/groups`), which this
 *   page opens in place, or
 * - a discovered graph cluster vertex (identity, household, behavioural …),
 *   read through `/v1/graph/query` with the cluster vertex types, which opens
 *   in Cluster 360 (`/clusters/:id`).
 *
 * Nothing here invents a value: fields the backend did not return stay null.
 */

const STALE = 60_000;

/** Cluster vertex types (mirrors services/api/graph/cluster/routes.py CLUSTER_VERTEX_TYPES). */
export const CLUSTER_VERTEX_TYPES = [
  'IdentityCluster', 'HouseholdCluster', 'OrgCluster', 'DeviceCluster',
  'WalletCluster', 'BehavioralCluster', 'GeographicCluster', 'EconomicSegment',
  'EconomicCluster', 'CampaignCohort', 'JourneyCluster', 'FraudNetworkCluster',
  'RiskCluster', 'DormantCohort', 'ReactivatedCohort', 'UnresolvedCluster',
] as const;

const CLUSTER_LABELS: Record<string, string> = Object.fromEntries(
  CLUSTER_VERTEX_TYPES.map(t => [t.toLowerCase(), t.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase().replace(/^./, c => c.toUpperCase())]),
);

type Row = Record<string, unknown>;

export function asRecord(value: unknown): Row {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {};
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

export function num(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN;
  return Number.isFinite(n) ? n : null;
}

// ── Tenant scope ─────────────────────────────────────────────────────────────

/** Tenant id from the authenticated profile (population and graph reads are tenant-addressed). */
export function useTenantScope(): { readonly tenantId: string; readonly loading: boolean; readonly error: string | null } {
  const me = useMeProfile();
  const tenantId = me.data?.tenant_id ?? '';
  return { tenantId, loading: !me.data && !me.error, error: me.error ?? (me.data && !tenantId ? 'Your profile did not include a workspace id.' : null) };
}

// ── Population groups (rule-defined syndicates) ─────────────────────────────

export interface SyndicateGroup {
  readonly id: string;
  readonly name: string;
  readonly type: string;
  readonly description: string | null;
  readonly memberCount: number | null;
  readonly rules: readonly string[];
  readonly definitionVersion: string | null;
  readonly status: string | null;
  readonly sourceTag: string | null;
  readonly createdAt: string | null;
  readonly updatedAt: string | null;
}

function ruleText(rule: unknown): string | null {
  if (typeof rule === 'string') return rule.trim() || null;
  if (typeof rule === 'number' || typeof rule === 'boolean') return String(rule);
  const r = asRecord(rule);
  const field = str(r.field) ?? str(r.attribute) ?? str(r.key) ?? str(r.name);
  if (field) {
    const op = str(r.op) ?? str(r.operator) ?? str(r.comparator) ?? '=';
    const value = r.value ?? r.values ?? r.threshold;
    const rendered = Array.isArray(value) ? value.map(String).join(', ') : value === undefined || value === null ? '' : String(value);
    return `${field.replace(/_/g, ' ')} ${op} ${rendered}`.trim();
  }
  const label = str(r.label) ?? str(r.description);
  return label;
}

/** Human-readable rules from a population definition, whatever shape it uses. */
export function describeRules(definition: unknown): string[] {
  const def = asRecord(definition);
  for (const key of ['rules', 'conditions', 'criteria', 'filters']) {
    const list = def[key];
    if (Array.isArray(list)) return list.map(ruleText).filter((r): r is string => r !== null);
    const nested = asRecord(list);
    if (Object.keys(nested).length > 0) {
      return Object.entries(nested).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${Array.isArray(v) ? v.map(String).join(', ') : typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)}`);
    }
  }
  return Object.entries(def)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object')
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${String(v)}`);
}

export function toGroup(raw: unknown): SyndicateGroup | null {
  const r = asRecord(raw);
  const id = str(r.id) ?? str(r.population_id);
  if (!id) return null;
  return {
    id,
    name: str(r.name) ?? id,
    type: str(r.population_type) ?? str(r.type) ?? 'group',
    description: str(r.description),
    memberCount: num(r.member_count),
    rules: describeRules(r.definition),
    definitionVersion: r.definition_version === undefined || r.definition_version === null ? null : String(r.definition_version),
    status: str(r.status),
    sourceTag: str(r.source_tag),
    createdAt: str(r.created_at),
    updatedAt: str(r.updated_at),
  };
}

export function populationGroupsKey(tenantId: string): string {
  return `syndicates:${tenantId}:groups`;
}

export function usePopulationGroups(tenantId: string) {
  return useQuery({
    key: populationGroupsKey(tenantId),
    fetcher: async () => {
      const data = asRecord(await api.population.groups(tenantId, 200));
      const list = Array.isArray(data.groups) ? data.groups : [];
      return list.map(toGroup).filter((g): g is SyndicateGroup => g !== null);
    },
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function usePopulationGroup(tenantId: string, groupId: string) {
  return useQuery({
    key: `syndicates:${tenantId}:group:${groupId}`,
    // Wrapped so a resolved "not a group" (null) is distinguishable from "not loaded yet".
    fetcher: async () => ({ group: toGroup(await api.population.group(groupId, tenantId)) }),
    staleTime: STALE,
    enabled: !!tenantId && !!groupId,
  });
}

// ── Create ──────────────────────────────────────────────────────────────────

/** `PopulationType` values accepted by `POST /v1/population/groups` (identity/population/models.py). */
export const SYNDICATE_TYPES = [
  'segment', 'cohort', 'cluster', 'community', 'batch', 'archetype', 'anomaly', 'lookalike', 'risk', 'lifecycle',
] as const;
export type SyndicateType = typeof SYNDICATE_TYPES[number];

export const RULE_OPERATORS = ['=', '!=', '>', '>=', '<', '<=', 'contains', 'in'] as const;
export type RuleOperator = typeof RULE_OPERATORS[number];

export interface SyndicateRuleDraft {
  readonly field: string;
  readonly op: RuleOperator;
  readonly value: string;
}

export interface SyndicateDraft {
  readonly name: string;
  readonly type: SyndicateType;
  readonly description: string;
  readonly rules: readonly SyndicateRuleDraft[];
}

export interface SyndicateRule {
  readonly field: string;
  readonly op: RuleOperator;
  readonly value: string | number | boolean | string[];
}

export interface SyndicateBody {
  readonly name: string;
  readonly population_type: SyndicateType;
  readonly description: string;
  readonly definition: { readonly rules: SyndicateRule[] };
}

export interface SyndicateDraftErrors {
  name?: string;
  rules?: string;
  /** Per-row message, by rule index. */
  ruleRows?: Record<number, string>;
}

function ruleValue(op: RuleOperator, raw: string): SyndicateRule['value'] {
  const v = raw.trim();
  if (op === 'in') return v.split(',').map(x => x.trim()).filter(Boolean);
  if (v === 'true' || v === 'false') return v === 'true';
  const n = Number(v);
  return v !== '' && Number.isFinite(n) ? n : v;
}

/**
 * The backend stores `definition` as a free-form dict; the app writes
 * `{ rules: [{ field, op, value }] }`, the shape `describeRules` reads back.
 * Fully blank rule rows are ignored; a segment (rule-based) needs one rule.
 */
export function validateSyndicateDraft(draft: SyndicateDraft): { errors: SyndicateDraftErrors; body: SyndicateBody | null } {
  const errors: SyndicateDraftErrors = {};
  const name = draft.name.trim();
  if (!name) errors.name = 'Give the syndicate a name.';
  const rules: SyndicateRule[] = [];
  const ruleRows: Record<number, string> = {};
  draft.rules.forEach((rule, index) => {
    const field = rule.field.trim();
    const value = rule.value.trim();
    if (!field && !value) return;
    if (!field) ruleRows[index] = 'Name the field this rule checks.';
    else if (!value) ruleRows[index] = 'Give the value to compare against.';
    else rules.push({ field, op: rule.op, value: ruleValue(rule.op, value) });
  });
  if (Object.keys(ruleRows).length > 0) errors.ruleRows = ruleRows;
  else if (draft.type === 'segment' && rules.length === 0) errors.rules = 'A segment needs at least one rule.';
  if (errors.name || errors.rules || errors.ruleRows) return { errors, body: null };
  return {
    errors,
    body: { name, population_type: draft.type, description: draft.description.trim(), definition: { rules } },
  };
}

export function useCreateSyndicate(tenantId: string) {
  // Wrapped so a created-but-unreadable record ({ group: null }) differs from a failed write (mutate → null).
  return useMutation<SyndicateBody, { readonly group: SyndicateGroup | null }>({
    mutationFn: async body => ({ group: toGroup(await api.population.createGroup({ ...body })) }),
    invalidateKeys: [populationGroupsKey(tenantId)],
  });
}

// ── Members ─────────────────────────────────────────────────────────────────

export interface SyndicateMember {
  readonly entityId: string;
  readonly entityType: string;
  readonly basis: string | null;
  readonly confidence: number | null;
  readonly sourceTag: string | null;
  readonly joinedAt: string | null;
  readonly reason: string | null;
}

export function toMember(raw: unknown): SyndicateMember | null {
  const r = asRecord(raw);
  const entityId = str(r.entity_id);
  if (!entityId) return null;
  return {
    entityId,
    entityType: str(r.entity_type) ?? 'unknown',
    basis: str(r.basis),
    confidence: num(r.confidence),
    sourceTag: str(r.source_tag),
    joinedAt: str(r.joined_at) ?? str(r.created_at),
    reason: str(r.reason),
  };
}

export const MEMBER_READ_LIMIT = 1000;

export async function fetchGroupMembers(tenantId: string, groupId: string): Promise<SyndicateMember[]> {
  const data = asRecord(await api.population.groupMembers(groupId, tenantId, MEMBER_READ_LIMIT));
  const list = Array.isArray(data.members) ? data.members : [];
  return list.map(toMember).filter((m): m is SyndicateMember => m !== null);
}

export function usePopulationMembers(tenantId: string, groupId: string) {
  return useQuery({
    key: `syndicates:${tenantId}:members:${groupId}`,
    fetcher: () => fetchGroupMembers(tenantId, groupId),
    staleTime: STALE,
    enabled: !!tenantId && !!groupId,
  });
}

// ── Discovered clusters (graph cluster vertices) ─────────────────────────────

export interface DiscoveredCluster {
  readonly id: string;
  readonly type: string;
  readonly label: string;
  readonly memberCount: number | null;
  readonly lifecycleState: string | null;
  readonly formationReason: string | null;
  readonly confidence: number | null;
  readonly createdAt: string | null;
  readonly updatedAt: string | null;
}

export function clusterTypeLabel(kind: string): string {
  return CLUSTER_LABELS[kind.toLowerCase()] ?? kind.replace(/_/g, ' ');
}

export function toCluster(raw: unknown): DiscoveredCluster | null {
  const r = asRecord(raw);
  const id = str(r.id);
  if (!id) return null;
  const kind = str(r.kind) ?? 'cluster';
  const p = asRecord(r.properties);
  return {
    id,
    type: clusterTypeLabel(kind),
    label: str(r.label) ?? str(p.label) ?? `${clusterTypeLabel(kind)} ${id.slice(0, 6)}`,
    memberCount: num(p.member_count),
    lifecycleState: str(p.lifecycle_state),
    formationReason: str(p.formation_reason),
    confidence: num(p.confidence),
    createdAt: str(p.createdAt) ?? str(p.created_at),
    updatedAt: str(p.updated_at),
  };
}

export function useDiscoveredClusters(tenantId: string) {
  return useQuery({
    key: `syndicates:${tenantId}:clusters`,
    fetcher: async () => {
      const data = asRecord(await api.graphIntelligence.query({
        tenant_id: tenantId,
        node_types: [...CLUSTER_VERTEX_TYPES],
        depth: 1,
        limit: 200,
      }));
      const nodes = Array.isArray(data.nodes) ? data.nodes : [];
      return nodes.map(toCluster).filter((c): c is DiscoveredCluster => c !== null);
    },
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

// ── Overlap ─────────────────────────────────────────────────────────────────

export interface OverlapResult {
  readonly onlyA: number;
  readonly both: number;
  readonly onlyB: number;
  /** True when every active member of both groups was read (counts are exact). */
  readonly exact: boolean;
}

export function computeOverlap(
  a: readonly SyndicateMember[],
  b: readonly SyndicateMember[],
  aTotal: number | null,
  bTotal: number | null,
): OverlapResult {
  const idsA = new Set(a.map(m => m.entityId));
  const idsB = new Set(b.map(m => m.entityId));
  let both = 0;
  idsA.forEach(id => { if (idsB.has(id)) both += 1; });
  const exact = (aTotal === null || idsA.size >= aTotal) && (bTotal === null || idsB.size >= bTotal)
    && idsA.size < MEMBER_READ_LIMIT && idsB.size < MEMBER_READ_LIMIT;
  return { onlyA: idsA.size - both, both, onlyB: idsB.size - both, exact };
}

export function useOverlap(tenantId: string, a: SyndicateGroup | null, b: SyndicateGroup | null) {
  return useQuery({
    key: `syndicates:${tenantId}:overlap:${a?.id ?? ''}:${b?.id ?? ''}`,
    fetcher: async () => {
      const [ma, mb] = await Promise.all([fetchGroupMembers(tenantId, a!.id), fetchGroupMembers(tenantId, b!.id)]);
      return computeOverlap(ma, mb, a!.memberCount, b!.memberCount);
    },
    staleTime: STALE,
    enabled: !!tenantId && !!a && !!b,
  });
}
