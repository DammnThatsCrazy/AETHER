/**
 * Graph-first product operating context.
 *
 * This is an additive composition over the existing exploration, graph,
 * temporal, comparison, and projection contracts. References are always
 * tenant and environment scoped; a scope change must never retain references
 * from the previous scope.
 */

import type { ExplorationContextV1 } from './exploration-contract';
import type { FilterGroup, RelationshipLayer } from './graph-contract';
import type { TemporalRange } from './temporal';
import type { ComparisonDefinition, ComparisonRun } from './comparison-contract';
import type { ProjectionContext, ProjectionResult } from './intelligence-projection';
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

/** Graph context keeps interaction roles separate: selected is not focused. */
export interface GraphContext extends ExplorationContextV1 {
  readonly scope: ExplorationContextV1['scope'] & {
    readonly environment_id: string;
  };
  readonly selected: readonly GraphObjectRef[];
  readonly focused: GraphObjectRef | null;
  readonly pinned: readonly GraphObjectRef[];
  readonly compared: readonly GraphObjectRef[];
  readonly projection?: ProjectionContext | ProjectionResult | null;
  readonly rights?: GraphRightsState | null;
  readonly evidence: readonly EvidenceRef[];
  readonly confidence?: GraphConfidenceState | null;
  readonly saved_context_id?: string | null;
  readonly snapshot_id?: string | null;
  readonly diff_id?: string | null;
  readonly exploration_trail: readonly ExplorationTrailEntry[];
}

export interface GraphQueryAst {
  readonly kind: 'graph_query';
  readonly version: '1';
  readonly scope: { readonly tenant_id: string; readonly environment_id: string };
  readonly anchors?: readonly GraphObjectRef[];
  readonly node_kinds?: readonly string[];
  readonly edge_types?: readonly string[];
  readonly layers?: readonly RelationshipLayer[];
  readonly filter?: FilterGroup | null;
  readonly temporal?: TemporalRange | null;
  readonly as_of?: string | null;
  readonly depth?: number;
  readonly limit?: number;
  readonly include_evidence?: boolean;
  readonly include_provenance?: boolean;
}

export interface GraphSnapshot {
  readonly kind: 'graph_snapshot';
  readonly id: string;
  readonly tenant_id: string;
  readonly environment_id: string;
  readonly captured_at: string;
  readonly as_of: string;
  readonly query: GraphQueryAst;
  readonly objects: readonly GraphObjectRef[];
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
  readonly from_snapshot_id: string;
  readonly to_snapshot_id: string;
  readonly created_at: string;
  readonly added: readonly GraphObjectRef[];
  readonly removed: readonly GraphObjectRef[];
  readonly unchanged: readonly GraphObjectRef[];
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
  for (const field of ['selected', 'pinned', 'compared'] as const) {
    const refs = context[field];
    if (!Array.isArray(refs)) errors.push(`${field} must be an array`);
    else refs.forEach((ref, i) => { if (!validRef(ref, tenant, environment)) errors.push(`${field}[${i}] is out of scope or invalid`); });
  }
  if (context.focused !== null && !validRef(context.focused, tenant, environment)) errors.push('focused is out of scope or invalid');
  if (!Array.isArray(context.exploration_trail)) errors.push('exploration_trail must be an array');
  else context.exploration_trail.forEach((entry, i) => { if (!isRecord(entry) || !validRef(entry.object, tenant, environment)) errors.push(`exploration_trail[${i}] is out of scope or invalid`); });
  return { valid: errors.length === 0, errors };
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (isRecord(value)) return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonicalize(value[key])]));
  return value;
}

/** Stable JSON representation suitable for URLs, persistence, and hashing. */
export function serializeGraphContext(context: GraphContext): string {
  const result = validateGraphContext(context);
  if (!result.valid) throw new Error(`Invalid GraphContext: ${result.errors.join('; ')}`);
  return JSON.stringify(canonicalize(context));
}

export function restoreGraphContext(serialized: string): GraphContext {
  let parsed: unknown;
  try { parsed = JSON.parse(serialized); } catch { throw new Error('Invalid serialized GraphContext JSON'); }
  const result = validateGraphContext(parsed);
  if (!result.valid) throw new Error(`Invalid GraphContext: ${result.errors.join('; ')}`);
  return parsed as GraphContext;
}

/** Switch scope while retaining only references that are valid in the target scope. */
export function switchGraphContextScope(context: GraphContext, tenant_id: string, environment_id: string): GraphContext {
  const keep = (ref: GraphObjectRef) => ref.tenant_id === tenant_id && ref.environment_id === environment_id;
  return {
    ...context,
    scope: { ...context.scope, tenant_id, environment_id },
    selected: context.selected.filter(keep),
    focused: context.focused && keep(context.focused) ? context.focused : null,
    pinned: context.pinned.filter(keep),
    compared: context.compared.filter(keep),
    evidence: [],
    rights: null,
    confidence: null,
    saved_context_id: null,
    snapshot_id: null,
    diff_id: null,
    exploration_trail: context.exploration_trail.filter(entry => keep(entry.object)),
  };
}

export type { ComparisonDefinition, ComparisonRun };
