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
export interface GraphScope {
  readonly tenant_id: string;
  readonly workspace_id: string;
  readonly environment_id: string;
  readonly account_id?: string;
  readonly organization_id?: string;
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
  readonly scope: ExplorationContextV1['scope'] & GraphScope;
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
  readonly scope: GraphScope;
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
  readonly projection?: ProjectionId | null;
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

const canonicalTemporalModes = ['live', 'point', 'range', 'compare', 'diff'] as const;

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function scopeErrors(value: unknown, prefix: string): string[] {
  if (!isRecord(value)) return [`${prefix} is required`];
  const errors: string[] = [];
  for (const field of ['tenant_id', 'workspace_id', 'environment_id'] as const) {
    if (!isNonEmptyString(value[field])) errors.push(`${prefix}.${field} is required`);
  }
  for (const field of ['account_id', 'organization_id'] as const) {
    if (value[field] !== undefined && !isNonEmptyString(value[field])) errors.push(`${prefix}.${field} must be nonempty when provided`);
  }
  return errors;
}

function validateTemporalRange(value: unknown, prefix: string): string[] {
  if (!isRecord(value)) return [`${prefix} must be an object`];
  const errors: string[] = [];
  if (value.kind === 'instant') {
    if (!isNonEmptyString(value.start) || !isNonEmptyString(value.endExclusive)) errors.push(`${prefix} instant bounds are required`);
  } else if (value.kind === 'local_date') {
    if (!isNonEmptyString(value.startDate) || !isNonEmptyString(value.endDateExclusive) || !isNonEmptyString(value.timeZone)) errors.push(`${prefix} local-date bounds are required`);
  } else {
    errors.push(`${prefix}.kind is invalid`);
  }
  return errors;
}

function validateCanonicalTemporal(value: unknown, prefix: string): string[] {
  if (!isRecord(value)) return [`${prefix} must be an object`];
  const errors: string[] = [];
  const mode = value.mode;
  if (!canonicalTemporalModes.includes(mode as typeof canonicalTemporalModes[number])) {
    errors.push(`${prefix}.mode is invalid`);
    return errors;
  }
  const has = (field: string) => value[field] !== undefined && value[field] !== null;
  const nonempty = (field: string) => isNonEmptyString(value[field]);
  if (mode === 'live') {
    if (has('range') || has('as_of') || has('known_then') || has('known_now')) errors.push('live temporal mode cannot carry bounds');
  } else if (mode === 'point') {
    if (!nonempty('as_of')) errors.push('point temporal mode requires as_of');
    if (has('range') || has('known_then') || has('known_now')) errors.push('point temporal mode cannot carry range or paired bounds');
  } else if (mode === 'range') {
    if (!has('range')) errors.push('range temporal mode requires range');
    else errors.push(...validateTemporalRange(value.range, `${prefix}.range`));
    if (has('as_of') || has('known_then') || has('known_now')) errors.push('range temporal mode cannot carry point or paired bounds');
  } else {
    if (!nonempty('known_then') || !nonempty('known_now')) errors.push(`${mode} temporal mode requires known_then and known_now`);
    if (has('range') || has('as_of')) errors.push(`${mode} temporal mode cannot carry range or point bounds`);
  }
  if (has('known_then') !== has('known_now')) errors.push('known_then and known_now must be paired');
  return errors;
}

function validateFilterGroup(value: unknown, prefix: string): string[] {
  if (!isRecord(value) || !['AND', 'OR', 'NOT'].includes(String(value.logic)) || !Array.isArray(value.expressions)) return [`${prefix} is invalid`];
  const errors: string[] = [];
  value.expressions.forEach((expression, i) => {
    if (isRecord(expression) && 'logic' in expression) {
      errors.push(...validateFilterGroup(expression, `${prefix}.expressions[${i}]`));
    } else if (!isRecord(expression) || !isNonEmptyString(expression.field) || !isNonEmptyString(expression.op) || !('value' in expression)) {
      errors.push(`${prefix}.expressions[${i}] is invalid`);
    }
  });
  return errors;
}

function assertValid(name: string, result: GraphContextValidation): void {
  if (!result.valid) throw new Error(`Invalid ${name}: ${result.errors.join('; ')}`);
}

function validateUniversalGraphQueryRequest(request: unknown): GraphContextValidation {
  const errors: string[] = [];
  if (!isRecord(request)) return { valid: false, errors: ['request must be an object'] };
  if (!isNonEmptyString(request.tenant_id)) errors.push('request tenant_id is required');
  for (const field of ['anchors', 'node_types', 'edge_types', 'layers', 'include_overlays'] as const) {
    if (request[field] !== undefined && (!Array.isArray(request[field]) || request[field].some(value => !isNonEmptyString(value)))) errors.push(`request ${field} is invalid`);
  }
  if (request.filter !== undefined) errors.push(...validateFilterGroup(request.filter, 'request filter'));
  if (request.depth !== undefined && (!Number.isInteger(request.depth) || Number(request.depth) < 1 || Number(request.depth) > 6)) errors.push('request depth must be between 1 and 6');
  if (request.limit !== undefined && (!Number.isInteger(request.limit) || Number(request.limit) < 1 || Number(request.limit) > 500)) errors.push('request limit must be between 1 and 500');
  if (request.as_of !== undefined && !isNonEmptyString(request.as_of)) errors.push('request as_of must be nonempty when provided');
  for (const field of ['include_evidence', 'include_provenance', 'include_clusters', 'explain'] as const) {
    if (request[field] !== undefined && typeof request[field] !== 'boolean') errors.push(`request ${field} must be boolean`);
  }
  if (request.cursor !== undefined && !isNonEmptyString(request.cursor)) errors.push('request cursor must be nonempty when provided');
  return { valid: errors.length === 0, errors };
}

export function validateCanonicalGraphQuery(query: unknown): GraphContextValidation {
  const errors: string[] = [];
  if (!isRecord(query) || query.kind !== 'graph_query' || query.version !== '1') errors.push('query kind/version is invalid');
  if (isRecord(query)) errors.push(...scopeErrors(query.scope, 'query scope'));
  if (isRecord(query) && (!Array.isArray(query.roots))) errors.push('query roots must be an array');
  if (isRecord(query) && Array.isArray(query.roots) && isRecord(query.scope)) { const queryScope = query.scope; query.roots.forEach((root, i) => { if (!validRef(root, String(queryScope.tenant_id), String(queryScope.environment_id))) errors.push(`query roots[${i}] is out of scope`); }); }
  if (isRecord(query) && (!isRecord(query.traversal) || !['in', 'out', 'both'].includes(String(query.traversal.direction)) || !Number.isInteger(query.traversal.max_depth) || Number(query.traversal.max_depth) < 1 || Number(query.traversal.max_depth) > 6)) errors.push('query traversal is invalid');
  if (isRecord(query) && query.limit !== undefined && (!Number.isInteger(query.limit) || Number(query.limit) < 1 || Number(query.limit) > 500)) errors.push('query limit must be between 1 and 500');
  if (isRecord(query) && query.rights_policy !== undefined && !['enforce', 'explain'].includes(String(query.rights_policy))) errors.push('query rights_policy is invalid');
  if (isRecord(query) && query.minimum_confidence !== undefined && (typeof query.minimum_confidence !== 'number' || query.minimum_confidence < 0 || query.minimum_confidence > 1)) errors.push('query minimum_confidence must be between 0 and 1');
  if (isRecord(query) && query.predicates !== undefined && query.predicates !== null) errors.push(...validateFilterGroup(query.predicates, 'query predicates'));
  if (isRecord(query) && query.temporal !== undefined && query.temporal !== null) errors.push(...validateCanonicalTemporal(query.temporal, 'query temporal'));
  else if (isRecord(query) && query.temporal === null) errors.push('query temporal must be an object when provided');
  return { valid: errors.length === 0, errors };
}

export function validateGraphSnapshot(snapshot: unknown): GraphContextValidation {
  const errors: string[] = [];
  if (!isRecord(snapshot) || snapshot.kind !== 'graph_snapshot') errors.push('snapshot kind is invalid');
  if (isRecord(snapshot)) {
    if (scopeErrors({ tenant_id: snapshot.tenant_id, workspace_id: snapshot.workspace_id, environment_id: snapshot.environment_id }, 'snapshot scope').length > 0) errors.push('snapshot scope, workspace, and environment are required');
    for (const field of ['id', 'captured_at', 'as_of', 'graph_state_ref', 'evidence_state_ref', 'source_state_ref', 'policy_version', 'ontology_version'] as const) {
      if (!isNonEmptyString(snapshot[field])) errors.push(`snapshot ${field} is required`);
    }
    if (!Array.isArray(snapshot.objects)) errors.push('snapshot objects must be an array');
    else snapshot.objects.forEach((object, i) => { if (!validRef(object, String(snapshot.tenant_id), String(snapshot.environment_id))) errors.push(`snapshot objects[${i}] is out of scope`); });
    if (!isRecord(snapshot.model_versions) || Object.values(snapshot.model_versions).some(value => !isNonEmptyString(value))) errors.push('snapshot model_versions are required');
    if (!isRecord(snapshot.metadata)) errors.push('snapshot metadata is required');
    const query = validateCanonicalGraphQuery(snapshot.query);
    if (!query.valid) errors.push(...query.errors.map(error => `query: ${error}`));
    else if (isRecord(snapshot.query) && isRecord(snapshot.query.scope) && (snapshot.query.scope.tenant_id !== snapshot.tenant_id || snapshot.query.scope.workspace_id !== snapshot.workspace_id || snapshot.query.scope.environment_id !== snapshot.environment_id)) errors.push('snapshot query scope does not match snapshot scope');
  }
  return { valid: errors.length === 0, errors };
}

export function validateGraphDiff(diff: unknown): GraphContextValidation {
  const errors: string[] = [];
  if (!isRecord(diff) || diff.kind !== 'graph_diff') errors.push('diff kind is invalid');
  if (isRecord(diff)) {
    if (scopeErrors({ tenant_id: diff.tenant_id, workspace_id: diff.workspace_id, environment_id: diff.environment_id }, 'diff scope').length > 0) errors.push('diff scope, workspace, and environment are required');
    for (const field of ['id', 'from_state_ref', 'to_state_ref', 'created_at'] as const) if (!isNonEmptyString(diff[field])) errors.push(`diff ${field} is required`);
    if (!isRecord(diff.summary) || !Array.isArray(diff.changes)) errors.push('diff summary and changes are required');
    if (!isRecord(diff.metadata)) errors.push('diff metadata is required');
  }
  if (isRecord(diff) && Array.isArray(diff.changes) && isRecord(diff.summary)) {
    const counts = { added: 0, removed: 0, changed: 0 };
    diff.changes.forEach((change, i) => {
      if (!isRecord(change) || !['added', 'removed', 'changed'].includes(String(change.kind)) || !validRef(change.object, String(diff.tenant_id), String(diff.environment_id))) errors.push(`diff changes[${i}] is invalid or out of scope`);
      else {
        if (change.fields !== undefined && (!Array.isArray(change.fields) || change.fields.some(field => !isNonEmptyString(field)))) errors.push(`diff changes[${i}].fields is invalid`);
        counts[change.kind as keyof typeof counts]++;
      }
    });
    for (const key of Object.keys(counts) as Array<keyof typeof counts>) if (!Number.isInteger(diff.summary[key]) || Number(diff.summary[key]) < 0 || diff.summary[key] !== counts[key]) errors.push(`diff summary.${key} does not match changes`);
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
    && isNonEmptyString(value.kind)
    && isNonEmptyString(value.id);
}

/** Deterministic structural validation; no I/O or current-time assumptions. */
export function validateGraphContext(context: unknown): GraphContextValidation {
  const errors: string[] = [];
  if (!isRecord(context)) return { valid: false, errors: ['context must be an object'] };
  const scope = context.scope;
  const tenant = isRecord(scope) && typeof scope.tenant_id === 'string' ? scope.tenant_id : '';
  const workspace = isRecord(scope) && typeof scope.workspace_id === 'string' ? scope.workspace_id : '';
  const environment = isRecord(scope) && typeof scope.environment_id === 'string' ? scope.environment_id : '';
  errors.push(...scopeErrors(scope, 'scope'));
  if (context.version !== graphContextContractVersion) errors.push('version must be 1');
  const selection = context.selection;
  if (!isRecord(selection)) errors.push('selection is required');
  for (const field of ['selected', 'pinned', 'compared'] as const) {
    const refs = isRecord(selection) ? selection[field] : undefined;
    if (!Array.isArray(refs)) errors.push(`${field} must be an array`);
    else refs.forEach((ref, i) => { if (!validRef(ref, tenant, environment)) errors.push(`${field}[${i}] is out of scope or invalid`); });
  }
  if (isRecord(selection) && selection.focused !== null && !validRef(selection.focused, tenant, environment)) errors.push('focused is out of scope or invalid');
  const snapshotBound = isRecord(selection) ? selection.snapshot_bound : undefined;
  if (!Array.isArray(snapshotBound)) errors.push('snapshot_bound must be an array');
  else snapshotBound.forEach((snapshotRef, i) => { if (!isRecord(snapshotRef) || snapshotRef.tenant_id !== tenant || snapshotRef.environment_id !== environment || !isNonEmptyString(snapshotRef.snapshot_id)) errors.push(`snapshot_bound[${i}] is out of scope or invalid`); });
  if (!Array.isArray(context.exploration_trail)) errors.push('exploration_trail must be an array');
  else context.exploration_trail.forEach((entry, i) => { if (!isRecord(entry) || !validRef(entry.object, tenant, environment)) errors.push(`exploration_trail[${i}] is out of scope or invalid`); });
  if (!Array.isArray(context.anchors)) errors.push('anchors must be an array');
  else context.anchors.forEach((ref, i) => { if (!validRef(ref, tenant, environment)) errors.push(`anchors[${i}] is out of scope or invalid`); });
  if (!Array.isArray(context.evidence)) errors.push('evidence must be an array');
  const query = context.query;
  if (query !== undefined && query !== null) {
    const queryResult = validateCanonicalGraphQuery(query);
    if (!queryResult.valid) errors.push(...queryResult.errors.map(error => `query: ${error}`));
    if (isRecord(query) && isRecord(query.scope) && (query.scope.tenant_id !== tenant || query.scope.workspace_id !== workspace || query.scope.environment_id !== environment)) errors.push('query scope does not match context scope');
  }
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
export function switchGraphContextScope(context: GraphContext, target: GraphScope): GraphContext {
  const targetErrors = scopeErrors(target, 'target scope');
  if (targetErrors.length > 0) throw new Error(`Invalid target GraphScope: ${targetErrors.join('; ')}`);
  const nextScope: GraphContext['scope'] = {
    tenant_id: target.tenant_id,
    workspace_id: target.workspace_id,
    environment_id: target.environment_id,
    surface: context.scope.surface,
    ...(target.account_id === undefined ? {} : { account_id: target.account_id }),
    ...(target.organization_id === undefined ? {} : { organization_id: target.organization_id }),
  };
  return {
    ...context,
    scope: nextScope, anchors: [], population: null, graph: null, query: null,
    selection: { selected: [], focused: null, pinned: [], compared: [], snapshot_bound: [] },
    evidence: [],
    rights: null,
    confidence: null,
    saved_context_id: null,
    snapshot_id: null,
    diff_id: null,
    exploration_trail: [],
    projection: null,
  };
}

export function toUniversalGraphQueryRequest(query: CanonicalGraphQuery): UniversalGraphQueryRequest {
  assertValid('CanonicalGraphQuery', validateCanonicalGraphQuery(query));
  return {
    tenant_id: query.scope.tenant_id,
    anchors: query.roots.map(root => root.id),
    node_types: query.entity_types ? [...query.entity_types] : undefined,
    edge_types: query.relationship_types ? [...query.relationship_types] : undefined,
    layers: query.layers ? [...query.layers] : undefined,
    filter: query.predicates ?? undefined,
    depth: query.traversal.max_depth,
    limit: query.limit,
    cursor: query.cursor,
    include_overlays: query.include_overlays ? [...query.include_overlays] : undefined,
    as_of: query.temporal?.mode === 'point' ? query.temporal.as_of ?? undefined : undefined,
    include_evidence: query.evidence_policy !== 'omit',
    include_provenance: query.evidence_policy === 'required',
    include_clusters: query.include_clusters,
    explain: query.explain,
  };
}

export function fromUniversalGraphQueryRequest(request: UniversalGraphQueryRequest, scope: GraphScope): CanonicalGraphQuery {
  const requestResult = validateUniversalGraphQueryRequest(request);
  assertValid('UniversalGraphQueryRequest', requestResult);
  const targetErrors = scopeErrors(scope, 'scope');
  assertValid('GraphScope', { valid: targetErrors.length === 0, errors: targetErrors });
  if (request.tenant_id !== scope.tenant_id) throw new Error('UniversalGraphQueryRequest tenant_id does not match scope');
  const query: CanonicalGraphQuery = {
    kind: 'graph_query',
    version: '1',
    scope,
    roots: (request.anchors ?? []).map(id => ({ tenant_id: scope.tenant_id, environment_id: scope.environment_id, kind: 'entity', id })),
    entity_types: request.node_types,
    relationship_types: request.edge_types,
    layers: request.layers,
    predicates: request.filter,
    traversal: { direction: 'both', max_depth: request.depth ?? 2 },
    temporal: request.as_of === undefined ? { mode: 'live' } : { mode: 'point', as_of: request.as_of },
    evidence_policy: request.include_provenance ? 'required' : request.include_evidence ? 'include' : 'omit',
    rights_policy: 'enforce',
    limit: request.limit,
    cursor: request.cursor,
    include_overlays: request.include_overlays,
    include_clusters: request.include_clusters,
    explain: request.explain,
  };
  assertValid('CanonicalGraphQuery', validateCanonicalGraphQuery(query));
  return query;
}

export type { ComparisonDefinition, ComparisonRun };
