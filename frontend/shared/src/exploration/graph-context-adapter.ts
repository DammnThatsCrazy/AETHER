import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import {
  toUniversalGraphQueryRequest,
  type CanonicalGraphQuery,
  type GraphContext,
  type GraphObjectRef,
  type GraphScope,
} from '@aether/shared/graph-context-contract';
import type { UniversalGraphQueryRequest } from '@aether/shared/graph-contract';
import type { ProjectionId } from '@aether/shared/intelligence-projection';

export interface GraphQueryLossReport {
  readonly lost_fields: readonly ('rights' | 'ordering' | 'aggregation' | 'compare' | 'diff')[];
  readonly reasons: Readonly<Record<string, string>>;
}

export interface GraphContextAdapterOptions {
  readonly projection_id?: ProjectionId | null;
  readonly rights_policy?: CanonicalGraphQuery['rights_policy'];
  readonly aggregation?: CanonicalGraphQuery['aggregation'];
  readonly ordering?: CanonicalGraphQuery['ordering'];
}

const EMPTY_SELECTION = { selected: [], focused: null, pinned: [], compared: [], snapshot_bound: [] } as const;

function assertScope(scope: GraphScope): void {
  for (const key of ['tenant_id', 'workspace_id', 'environment_id'] as const) {
    if (typeof scope[key] !== 'string' || scope[key].length === 0) throw new Error(`host scope ${key} is required`);
  }
}

function refFor(scope: GraphScope, anchor: { kind: string; id: string }): GraphObjectRef {
  if (!anchor.kind || !anchor.id) throw new Error('graph anchor kind and id are required');
  const candidate = anchor as { kind: string; id: string; tenant_id?: string; environment_id?: string };
  if ((candidate.tenant_id !== undefined && candidate.tenant_id !== scope.tenant_id)
    || (candidate.environment_id !== undefined && candidate.environment_id !== scope.environment_id)) {
    throw new Error('graph root is out of host scope');
  }
  return { tenant_id: scope.tenant_id, environment_id: scope.environment_id, kind: anchor.kind, id: anchor.id };
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
  if (context.scope.tenant_id !== hostScope.tenant_id) throw new Error('exploration context tenant does not match host scope');
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
  const graph = context.graph ?? {};
  const temporal = context.temporal;
  const roots = (context.anchors ?? []).map(anchor => refFor(hostScope, anchor));
  const query: CanonicalGraphQuery = {
    kind: 'graph_query', version: '1', scope: hostScope, roots,
    entity_types: context.dimensions,
    relationship_types: graph.edge_types,
    layers: graph.layers,
    predicates: context.population ?? null,
    traversal: { direction: graph.direction ?? 'both', max_depth: graph.depth ?? 2 },
    temporal: temporal.mode === 'as_of' ? { mode: 'point', as_of: temporal.as_of ?? null }
      : temporal.mode === 'window' ? { mode: 'range', range: temporal.range ?? null }
        : temporal.mode === 'compare' ? { mode: 'compare', known_then: temporal.compare_to ?? undefined, known_now: temporal.as_of ?? undefined }
          : { mode: 'live' },
    evidence_policy: context.truth?.include_provenance ? 'required' : context.truth?.include_evidence ? 'include' : 'omit',
    confidence_policy: context.truth?.minimum_confidence === undefined || context.truth.minimum_confidence === null ? 'any' : 'minimum',
    minimum_confidence: context.truth?.minimum_confidence,
    rights_policy: options.rights_policy ?? 'enforce', aggregation: options.aggregation ?? null,
    ordering: options.ordering ?? context.presentation?.sort,
    limit: context.presentation?.page_size,
    projection: options.projection_id ?? null,
  };
  return query;
}

export function canonicalGraphQueryToUniversalRequest(query: CanonicalGraphQuery): { request: UniversalGraphQueryRequest; loss_report: GraphQueryLossReport } {
  const lost_fields: Array<GraphQueryLossReport['lost_fields'][number]> = [];
  const reasons: Record<string, string> = {};
  for (const field of ['rights', 'ordering', 'aggregation'] as const) { if (query[field === 'rights' ? 'rights_policy' : field] !== undefined && query[field === 'rights' ? 'rights_policy' : field] !== null) { lost_fields.push(field); reasons[field] = 'UniversalGraphQueryRequest has no corresponding field.'; } }
  if (query.temporal?.mode === 'compare') { lost_fields.push('compare'); reasons.compare = 'UniversalGraphQueryRequest supports only a single as_of timestamp.'; }
  if (query.temporal?.mode === 'diff') { lost_fields.push('diff'); reasons.diff = 'UniversalGraphQueryRequest has no diff interval.'; }
  return { request: toUniversalGraphQueryRequest(query), loss_report: { lost_fields, reasons } };
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
