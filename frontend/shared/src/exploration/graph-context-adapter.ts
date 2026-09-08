import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import {
  toUniversalGraphQueryRequest,
  type CanonicalGraphQuery,
  type GraphContext,
  type GraphObjectRef,
  type GraphScope,
  validateCanonicalGraphQuery,
} from '@aether/shared/graph-context-contract';
import type { UniversalGraphQueryRequest } from '@aether/shared/graph-contract';
import type { ProjectionId } from '@aether/shared/intelligence-projection';

type GraphQueryLossField =
  | 'scope'
  | 'root_metadata'
  | 'direction'
  | 'shortest_path'
  | 'temporal'
  | 'confidence'
  | 'rights'
  | 'ordering'
  | 'aggregation'
  | 'projection'
  | 'compare'
  | 'diff';

export interface GraphQueryLossReport {
  readonly lost_fields: readonly GraphQueryLossField[];
  readonly reasons: Readonly<Record<string, string>>;
}

export interface GraphContextAdapterOptions {
  readonly projection_id?: ProjectionId | null;
  readonly rights_policy?: CanonicalGraphQuery['rights_policy'];
  readonly aggregation?: CanonicalGraphQuery['aggregation'];
  readonly ordering?: CanonicalGraphQuery['ordering'];
}

const EMPTY_SELECTION = { selected: [], focused: null, pinned: [], compared: [], snapshot_bound: [] } as const;
const DEFAULT_GRAPH_DEPTH = 2;
const MAX_GRAPH_DEPTH = 6;

function hasText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function assertScope(scope: GraphScope): void {
  if (scope === null || typeof scope !== 'object') throw new Error('host scope is required');
  for (const key of ['tenant_id', 'workspace_id', 'environment_id'] as const) {
    if (!hasText(scope[key])) throw new Error(`host scope ${key} is required`);
  }
}

function refFor(scope: GraphScope, anchor: { kind: string; id: string }): GraphObjectRef {
  if (anchor === null || typeof anchor !== 'object' || !hasText(anchor.kind) || !hasText(anchor.id)) {
    throw new Error('graph anchor kind and id are required');
  }
  const candidate = anchor as { kind: string; id: string; tenant_id?: string; environment_id?: string };
  if ((candidate.tenant_id !== undefined && candidate.tenant_id !== scope.tenant_id)
    || (candidate.environment_id !== undefined && candidate.environment_id !== scope.environment_id)) {
    throw new Error('graph root is out of host scope');
  }
  return { tenant_id: scope.tenant_id, environment_id: scope.environment_id, kind: anchor.kind, id: anchor.id };
}

function validatedDepth(depth: unknown): number {
  if (depth === undefined) return DEFAULT_GRAPH_DEPTH;
  if (!Number.isInteger(depth) || Number(depth) < 1 || Number(depth) > MAX_GRAPH_DEPTH) {
    throw new Error(`graph depth must be an integer between 1 and ${MAX_GRAPH_DEPTH}`);
  }
  return Number(depth);
}

function assertExplorationContextAuthority(context: ExplorationContextV1, hostScope: GraphScope): void {
  const contextTenant = context?.scope?.tenant_id;
  if (!hasText(contextTenant)) throw new Error('exploration context tenant_id is required');
  if (contextTenant !== hostScope.tenant_id) throw new Error('exploration context tenant does not match host scope');
  validatedDepth(context.graph?.depth);
}

function assertCanonicalQuery(query: CanonicalGraphQuery): void {
  if (query === null || typeof query !== 'object') throw new Error('canonical graph query is required');
  assertScope(query.scope);
  const validation = validateCanonicalGraphQuery(query);
  if (!validation.valid) throw new Error(`Invalid CanonicalGraphQuery: ${validation.errors.join('; ')}`);
}

/** A stable key for the host's scope authority. URL/state values are never authority inputs. */
export function graphScopeAuthorityKey(scope: GraphScope): string {
  assertScope(scope);
  return JSON.stringify([scope.tenant_id, scope.workspace_id, scope.environment_id]);
}

/** Any tenant, workspace, or environment transition starts a fresh graph context. */
export function graphScopeChangeRequiresReset(previous: GraphScope, next: GraphScope): boolean {
  assertScope(previous); assertScope(next);
  return previous.tenant_id !== next.tenant_id
    || previous.workspace_id !== next.workspace_id
    || previous.environment_id !== next.environment_id;
}

export function explorationContextToGraphContext(
  context: ExplorationContextV1,
  hostScope: GraphScope,
  options: GraphContextAdapterOptions = {},
): GraphContext {
  assertScope(hostScope);
  assertExplorationContextAuthority(context, hostScope);
  const anchors = (context.anchors ?? []).map(anchor => refFor(hostScope, anchor));
  const selected = (context.selection?.selected ?? []).map(anchor => refFor(hostScope, anchor));
  const focused = context.selection?.focused ? refFor(hostScope, context.selection.focused) : null;
  return {
    ...context,
    scope: { ...context.scope, ...hostScope },
    anchors,
    selection: { ...EMPTY_SELECTION, selected, focused },
    evidence: [],
    exploration_trail: [],
    projection: options.projection_id ? { projection_id: options.projection_id, state: 'requested', digest: null } : null,
    rights: null,
    confidence: context.truth?.minimum_confidence === null || context.truth?.minimum_confidence === undefined
      ? null : { score: context.truth.minimum_confidence },
    query: null,
  };
}

export function explorationContextToCanonicalGraphQuery(
  context: ExplorationContextV1,
  hostScope: GraphScope,
  options: GraphContextAdapterOptions = {},
): CanonicalGraphQuery {
  assertScope(hostScope);
  assertExplorationContextAuthority(context, hostScope);
  const graph = context.graph ?? {};
  const temporal = context.temporal;
  const roots = (context.anchors ?? []).map(anchor => refFor(hostScope, anchor));
  const ordering = options.ordering ?? context.presentation?.sort;
  const minimumConfidence = context.truth?.minimum_confidence;
  const limit = context.presentation?.page_size;
  const query: CanonicalGraphQuery = {
    kind: 'graph_query', version: '1', scope: hostScope, roots,
    ...(context.dimensions === undefined ? {} : { entity_types: context.dimensions }),
    ...(graph.edge_types === undefined ? {} : { relationship_types: graph.edge_types }),
    ...(graph.layers === undefined ? {} : { layers: graph.layers }),
    predicates: context.population ?? null,
    traversal: { direction: graph.direction ?? 'both', max_depth: validatedDepth(graph.depth) },
    temporal: temporal.mode === 'as_of' ? { mode: 'point', as_of: temporal.as_of ?? null }
      : temporal.mode === 'window' ? { mode: 'range', range: temporal.range ?? null }
        : temporal.mode === 'compare' ? { mode: 'compare', known_then: temporal.compare_to ?? null, known_now: temporal.as_of ?? null }
          : { mode: 'live' },
    evidence_policy: context.truth?.include_provenance ? 'required' : context.truth?.include_evidence ? 'include' : 'omit',
    confidence_policy: minimumConfidence === undefined || minimumConfidence === null ? 'any' : 'minimum',
    ...(minimumConfidence === undefined ? {} : { minimum_confidence: minimumConfidence }),
    rights_policy: options.rights_policy ?? 'enforce', aggregation: options.aggregation ?? null,
    ...(ordering === undefined ? {} : { ordering }),
    ...(limit === undefined ? {} : { limit }),
    projection: options.projection_id ?? null,
  };
  return query;
}

export function canonicalGraphQueryToUniversalRequest(query: CanonicalGraphQuery): { request: UniversalGraphQueryRequest; loss_report: GraphQueryLossReport } {
  assertCanonicalQuery(query);
  const lost_fields: GraphQueryLossField[] = [];
  const reasons: Record<string, string> = {};
  const reportLoss = (field: GraphQueryLossField, reason: string): void => {
    if (!lost_fields.includes(field)) lost_fields.push(field);
    reasons[field] = reason;
  };

  reportLoss('scope', 'UniversalGraphQueryRequest carries tenant_id only; workspace_id and environment_id are not expressible.');
  if (query.roots.length > 0) {
    reportLoss('root_metadata', 'UniversalGraphQueryRequest carries anchor IDs only; root kind and environment metadata are not expressible.');
  }
  if (query.traversal.direction !== 'both') {
    reportLoss('direction', 'UniversalGraphQueryRequest has no traversal direction field.');
  }
  if (query.traversal.shortest_path === true) {
    reportLoss('shortest_path', 'UniversalGraphQueryRequest has no shortest-path traversal field.');
  }
  if (query.temporal?.mode === 'compare') {
    reportLoss('compare', 'UniversalGraphQueryRequest supports only a single as_of timestamp; compare intervals are not expressible.');
  } else if (query.temporal?.mode === 'diff') {
    reportLoss('diff', 'UniversalGraphQueryRequest has no diff interval.');
  } else if (query.temporal?.mode !== undefined && !['live', 'point'].includes(query.temporal.mode)) {
    reportLoss('temporal', `UniversalGraphQueryRequest supports only live or point temporal queries; ${query.temporal.mode} is not expressible.`);
  }
  if ((query.minimum_confidence !== undefined && query.minimum_confidence !== null)
    || (query.confidence_policy !== undefined && query.confidence_policy !== 'any')) {
    reportLoss('confidence', 'UniversalGraphQueryRequest has no confidence policy or minimum confidence field.');
  }
  if (query.rights_policy !== undefined && query.rights_policy !== null) {
    reportLoss('rights', 'UniversalGraphQueryRequest has no rights policy field.');
  }
  if (query.ordering !== undefined && query.ordering !== null && query.ordering.length > 0) {
    reportLoss('ordering', 'UniversalGraphQueryRequest has no ordering field.');
  }
  if (query.aggregation !== undefined && query.aggregation !== null) {
    reportLoss('aggregation', 'UniversalGraphQueryRequest has no aggregation field.');
  }
  if (query.projection !== undefined && query.projection !== null) {
    reportLoss('projection', 'UniversalGraphQueryRequest has no projection field.');
  }

  const converted = toUniversalGraphQueryRequest(query);
  const request: UniversalGraphQueryRequest = {
    ...converted,
    ...(query.cursor === undefined ? {} : { cursor: query.cursor }),
    ...(query.include_overlays === undefined ? {} : { include_overlays: [...query.include_overlays] }),
    ...(query.include_clusters === undefined ? {} : { include_clusters: query.include_clusters }),
    ...(query.explain === undefined ? {} : { explain: query.explain }),
  };
  return { request, loss_report: { lost_fields, reasons } };
}

export function explorationContextToUniversalRequest(context: ExplorationContextV1, hostScope: GraphScope, options?: GraphContextAdapterOptions) {
  return canonicalGraphQueryToUniversalRequest(explorationContextToCanonicalGraphQuery(context, hostScope, options));
}

// Descriptive aliases for callers using the adapter vocabulary.
export const adaptExplorationContextToGraphContext = explorationContextToGraphContext;
export const adaptExplorationContextToCanonicalGraphQuery = explorationContextToCanonicalGraphQuery;
export const adaptCanonicalGraphQueryToUniversalRequest = canonicalGraphQueryToUniversalRequest;
export const scopeAuthorityKey = graphScopeAuthorityKey;
export const shouldResetForScopeChange = graphScopeChangeRequiresReset;
