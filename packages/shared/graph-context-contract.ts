/**
 * Graph-first product operating context.
 *
 * This is an additive composition over the existing exploration, graph,
 * temporal, comparison, and projection contracts. References are always
 * tenant and environment scoped; a scope change must never retain references
 * from the previous scope.
 */

import type { ExplorationContextV1 } from './exploration-contract';
import type { FilterGroup, RelationshipLayer, UniversalGraphQueryRequest } from './graph-contract';
import type { TemporalRange } from './temporal';
import type { ComparisonDefinition, ComparisonRun } from './comparison-contract';
import type { ProjectionId } from './intelligence-projection';
import type { EvidenceRef } from './operational-intelligence';

export const graphContextContractVersion = '1' as const;

/** An opaque graph object reference that cannot be interpreted outside scope. */
export interface GraphObjectRef {
  readonly tenant_id: string;
  readonly environment_id: string;
  readonly kind: string;
  readonly id: string;
}

export interface GraphRightsState {
  readonly decision_id?: string | null;
  readonly allowed: boolean;
  readonly evaluated_at?: string | null;
  readonly policy_version?: string | null;
}

export interface GraphConfidenceState {
  readonly score?: number | null;
  readonly label?: 'low' | 'medium' | 'high' | 'critical' | null;
  readonly as_of?: string | null;
}

export interface ExplorationTrailEntry {
  readonly object: GraphObjectRef;
  readonly action: 'open' | 'pivot' | 'expand' | 'collapse' | 'select' | 'compare' | 'snapshot' | 'diff';
  readonly occurred_at: string;
}

export interface GraphSelectionState {
  readonly selected: readonly GraphObjectRef[];
  readonly focused: GraphObjectRef | null;
  readonly pinned: readonly GraphObjectRef[];
  readonly compared: readonly GraphObjectRef[];
  readonly snapshot_bound: readonly GraphSnapshotRef[];
}

export interface GraphProjectionState {
  readonly projection_id: ProjectionId;
  readonly state: 'requested' | 'available' | 'degraded' | 'suppressed' | 'unavailable';
  readonly digest?: string | null;
}

/** One selection authority; inherited ExplorationContextV1.selection is omitted. */
export interface GraphContext extends Omit<ExplorationContextV1, 'selection' | 'anchors'> {
  readonly scope: ExplorationContextV1['scope'] & {
    readonly workspace_id: string;
    readonly environment_id: string;
    readonly account_id?: string;
    readonly organization_id?: string;
  };
  readonly anchors: readonly GraphObjectRef[];
  readonly selection: GraphSelectionState;
  readonly projection?: GraphProjectionState | null;
  readonly rights?: GraphRightsState | null;
  readonly evidence: readonly EvidenceRef[];
  readonly confidence?: GraphConfidenceState | null;
  readonly saved_context_id?: string | null;
  readonly snapshot_id?: string | null;
  readonly diff_id?: string | null;
  readonly exploration_trail: readonly ExplorationTrailEntry[];
  readonly query?: CanonicalGraphQuery | null;
}

/** Adapter over UniversalGraphQueryRequest; FilterGroup remains the sole predicate authority. */
export interface CanonicalGraphQuery extends Omit<UniversalGraphQueryRequest, 'tenant_id' | 'anchors' | 'node_types' | 'edge_types' | 'layers' | 'filter' | 'depth' | 'limit' | 'as_of' | 'include_evidence' | 'include_provenance'> {
  readonly kind: 'graph_query';
  readonly version: '1';
  readonly scope: { readonly tenant_id: string; readonly environment_id: string };
  readonly roots: readonly GraphObjectRef[];
  readonly entity_types?: readonly string[];
  readonly relationship_types?: readonly string[];
  readonly layers?: readonly RelationshipLayer[];
  readonly predicates?: FilterGroup | null;
  readonly traversal: Readonly<{ direction: 'in' | 'out' | 'both'; max_depth: number; shortest_path?: boolean }>;
  readonly temporal?: Readonly<{ mode: 'live' | 'point' | 'range' | 'compare' | 'diff'; range?: TemporalRange | null; as_of?: string | null; known_then?: string | null; known_now?: string | null }>;
  readonly evidence_policy?: 'omit' | 'include' | 'required';
  readonly confidence_policy?: 'any' | 'minimum';
  readonly rights_policy?: 'enforce' | 'explain';
  readonly minimum_confidence?: number | null;
  readonly aggregation?: Readonly<{ group_by: readonly string[]; measures: readonly string[] }> | null;
  readonly ordering?: readonly Readonly<{ field: string; direction: 'asc' | 'desc' }>[];
  readonly limit?: number;
  readonly projection?: string | null;
}

export type GraphQueryAst = CanonicalGraphQuery;

export interface GraphSnapshot {
  readonly kind: 'graph_snapshot';
  readonly id: string;
  readonly tenant_id: string;
  readonly environment_id: string;
  readonly captured_at: string;
  readonly workspace_id: string;
  readonly as_of: string;
  readonly query: GraphQueryAst;
  readonly objects: readonly GraphObjectRef[];
  readonly graph_state_ref: string;
  readonly evidence_state_ref: string;
  readonly source_state_ref: string;
  readonly policy_version: string;
  readonly ontology_version: string;
  readonly model_versions: Readonly<Record<string, string>>;
  readonly metadata: Readonly<Record<string, string | number | boolean | null>>;
}

export interface GraphSnapshotRef {
  readonly tenant_id: string;
  readonly environment_id: string;
  readonly snapshot_id: string;
}

export interface GraphDiff {
  readonly kind: 'graph_diff';
  readonly id: string;
  readonly tenant_id: string;
  readonly environment_id: string;
  readonly workspace_id: string;
  readonly from_state_ref: string;
  readonly to_state_ref: string;
  readonly created_at: string;
  readonly changes: readonly Readonly<{ kind: 'added' | 'removed' | 'changed'; object: GraphObjectRef; fields?: readonly string[] }>[];
  readonly summary: Readonly<{ added: number; removed: number; changed: number }>;
  readonly metadata: Readonly<Record<string, string | number | boolean | null>>;
}

export interface GraphDiffRef {
  readonly tenant_id: string;
  readonly environment_id: string;
  readonly diff_id: string;
}

/** Descriptive alias for callers that use the shorter query vocabulary. */
export type GraphQuery = GraphQueryAst;

export interface GraphContextValidation {
  readonly valid: boolean;
  readonly errors: readonly string[];
}

export function validateCanonicalGraphQuery(query: unknown): GraphContextValidation {
  const errors: string[] = [];
  if (!isRecord(query) || query.kind !== 'graph_query' || query.version !== '1') errors.push('query kind/version is invalid');
  if (!isRecord(query) || !isRecord(query.scope) || typeof query.scope.tenant_id !== 'string' || typeof query.scope.environment_id !== 'string') errors.push('query scope is required');
  if (isRecord(query) && (!Array.isArray(query.roots))) errors.push('query roots must be an array');
  if (isRecord(query) && Array.isArray(query.roots) && isRecord(query.scope)) { const queryScope = query.scope; query.roots.forEach((root, i) => { if (!validRef(root, String(queryScope.tenant_id), String(queryScope.environment_id))) errors.push(`query roots[${i}] is out of scope`); }); }
  if (isRecord(query) && (!isRecord(query.traversal) || !['in', 'out', 'both'].includes(String(query.traversal.direction)) || !Number.isInteger(query.traversal.max_depth) || Number(query.traversal.max_depth) < 0 || Number(query.traversal.max_depth) > 6)) errors.push('query traversal is invalid');
  if (isRecord(query) && query.limit !== undefined && (!Number.isInteger(query.limit) || Number(query.limit) < 1 || Number(query.limit) > 500)) errors.push('query limit must be between 1 and 500');
  if (isRecord(query) && query.rights_policy !== undefined && !['enforce', 'explain'].includes(String(query.rights_policy))) errors.push('query rights_policy is invalid');
  return { valid: errors.length === 0, errors };
}

export function validateGraphSnapshot(snapshot: unknown): GraphContextValidation {
  const errors: string[] = [];
  if (!isRecord(snapshot) || snapshot.kind !== 'graph_snapshot') errors.push('snapshot kind is invalid');
  if (isRecord(snapshot)) {
    if (typeof snapshot.tenant_id !== 'string' || typeof snapshot.environment_id !== 'string' || typeof snapshot.workspace_id !== 'string' || typeof snapshot.graph_state_ref !== 'string' || typeof snapshot.evidence_state_ref !== 'string' || typeof snapshot.source_state_ref !== 'string' || typeof snapshot.policy_version !== 'string' || typeof snapshot.ontology_version !== 'string' || !isRecord(snapshot.model_versions)) errors.push('snapshot scope, workspace, state refs, and versions are required');
    const query = validateCanonicalGraphQuery(snapshot.query);
    if (!query.valid) errors.push(...query.errors.map(error => `query: ${error}`));
    else if (isRecord(snapshot.query) && isRecord(snapshot.query.scope) && (snapshot.query.scope.tenant_id !== snapshot.tenant_id || snapshot.query.scope.environment_id !== snapshot.environment_id)) errors.push('snapshot query scope does not match snapshot scope');
  }
  return { valid: errors.length === 0, errors };
}

export function validateGraphDiff(diff: unknown): GraphContextValidation {
  const errors: string[] = [];
  if (!isRecord(diff) || diff.kind !== 'graph_diff') errors.push('diff kind is invalid');
  if (isRecord(diff) && (typeof diff.tenant_id !== 'string' || typeof diff.environment_id !== 'string' || typeof diff.workspace_id !== 'string' || typeof diff.from_state_ref !== 'string' || typeof diff.to_state_ref !== 'string' || !isRecord(diff.summary) || !Array.isArray(diff.changes))) errors.push('diff scope, workspace, state refs, summary, and changes are required');
  if (isRecord(diff) && Array.isArray(diff.changes) && isRecord(diff.summary)) {
    const counts = { added: 0, removed: 0, changed: 0 };
    diff.changes.forEach((change, i) => { if (!isRecord(change) || !['added', 'removed', 'changed'].includes(String(change.kind)) || !validRef(change.object, String(diff.tenant_id), String(diff.environment_id))) errors.push(`diff changes[${i}] is invalid or out of scope`); else counts[change.kind as keyof typeof counts]++; });
    for (const key of Object.keys(counts) as Array<keyof typeof counts>) if (diff.summary[key] !== counts[key]) errors.push(`diff summary.${key} does not match changes`);
  }
  return { valid: errors.length === 0, errors };
}

function deepFreeze<T>(value: T): T {
  if (isRecord(value) || Array.isArray(value)) {
    Object.freeze(value);
    Object.values(value as object).forEach(child => deepFreeze(child));
  }
  return value;
}

export function createImmutableGraphSnapshot(snapshot: GraphSnapshot): Readonly<GraphSnapshot> {
  const copy = JSON.parse(JSON.stringify(snapshot)) as GraphSnapshot;
  const result = validateGraphSnapshot(copy);
  if (!result.valid) throw new Error(`Invalid GraphSnapshot: ${result.errors.join('; ')}`);
  return deepFreeze(copy);
}

export function createImmutableGraphDiff(diff: GraphDiff): Readonly<GraphDiff> {
  const copy = JSON.parse(JSON.stringify(diff)) as GraphDiff;
  const result = validateGraphDiff(copy);
  if (!result.valid) throw new Error(`Invalid GraphDiff: ${result.errors.join('; ')}`);
  return deepFreeze(copy);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function validRef(value: unknown, tenant: string, environment: string): value is GraphObjectRef {
  return isRecord(value) && value.tenant_id === tenant && value.environment_id === environment
    && typeof value.kind === 'string' && value.kind.length > 0
    && typeof value.id === 'string' && value.id.length > 0;
}

/** Deterministic structural validation; no I/O or current-time assumptions. */
export function validateGraphContext(context: unknown): GraphContextValidation {
  const errors: string[] = [];
  if (!isRecord(context)) return { valid: false, errors: ['context must be an object'] };
  const scope = context.scope;
  const tenant = isRecord(scope) && typeof scope.tenant_id === 'string' ? scope.tenant_id : '';
  const environment = isRecord(scope) && typeof scope.environment_id === 'string' ? scope.environment_id : '';
  if (!tenant) errors.push('scope.tenant_id is required');
  if (!environment) errors.push('scope.environment_id is required');
  if (context.version !== graphContextContractVersion) errors.push('version must be 1');
  const selection = context.selection;
  if (!isRecord(selection)) errors.push('selection is required');
  for (const field of ['selected', 'pinned', 'compared'] as const) {
    const refs = isRecord(selection) ? selection[field] : undefined;
    if (!Array.isArray(refs)) errors.push(`${field} must be an array`);
    else refs.forEach((ref, i) => { if (!validRef(ref, tenant, environment)) errors.push(`${field}[${i}] is out of scope or invalid`); });
  }
  if (isRecord(selection) && selection.focused !== null && !validRef(selection.focused, tenant, environment)) errors.push('focused is out of scope or invalid');
  if (isRecord(selection) && Array.isArray(selection.snapshot_bound)) selection.snapshot_bound.forEach((ref, i) => { if (!isRecord(ref) || ref.tenant_id !== tenant || ref.environment_id !== environment) errors.push(`snapshot_bound[${i}] is out of scope or invalid`); });
  if (!Array.isArray(context.exploration_trail)) errors.push('exploration_trail must be an array');
  else context.exploration_trail.forEach((entry, i) => { if (!isRecord(entry) || !validRef(entry.object, tenant, environment)) errors.push(`exploration_trail[${i}] is out of scope or invalid`); });
  if (Array.isArray(context.anchors)) context.anchors.forEach((ref, i) => { if (!validRef(ref, tenant, environment)) errors.push(`anchors[${i}] is out of scope or invalid`); });
  const query = context.query;
  if (query !== undefined && query !== null && (!isRecord(query) || !isRecord(query.scope) || query.scope.tenant_id !== tenant || query.scope.environment_id !== environment)) errors.push('query scope does not match context scope');
  return { valid: errors.length === 0, errors };
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (isRecord(value)) return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonicalize(value[key])]));
  return value;
}

/** Stable persistence representation. The existing registry-sanitized Exploration URL codec remains the URL authority; this includes tenant evidence/rights/trail and must not be used for URLs. */
export function serializeGraphContextForPersistence(context: GraphContext): string {
  const result = validateGraphContext(context);
  if (!result.valid) throw new Error(`Invalid GraphContext: ${result.errors.join('; ')}`);
  return JSON.stringify(canonicalize(context));
}

export function restoreGraphContextFromPersistence(serialized: string): GraphContext {
  let parsed: unknown;
  try { parsed = JSON.parse(serialized); } catch { throw new Error('Invalid serialized GraphContext JSON'); }
  const result = validateGraphContext(parsed);
  if (!result.valid) throw new Error(`Invalid GraphContext: ${result.errors.join('; ')}`);
  return parsed as GraphContext;
}

/** Switch scope while retaining only references that are valid in the target scope. */
export function switchGraphContextScope(context: GraphContext, tenant_id: string, environment_id: string): GraphContext {
  const scope = { tenant_id, environment_id };
  return {
    ...context,
    scope: { ...context.scope, ...scope }, anchors: [], population: null, graph: null, query: null,
    selection: { selected: [], focused: null, pinned: [], compared: [], snapshot_bound: [] },
    evidence: [],
    rights: null,
    confidence: null,
    saved_context_id: null,
    snapshot_id: null,
    diff_id: null,
    exploration_trail: [],
  };
}

export type { ComparisonDefinition, ComparisonRun };
