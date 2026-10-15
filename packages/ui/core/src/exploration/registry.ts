/**
 * Registry-driven vocabulary helpers for the exploration UI.
 *
 * Every exploration component derives its field/operator vocabulary from the
 * canonical contract registries (`filterFields`, `surfaceCapabilities`) — never
 * a hardcoded list. Centralising the lookups here keeps that guarantee in one
 * place and gives the UI a single, typed source of truth.
 */

// Import registry VALUES from their leaf modules (not the '@aether/shared'
// barrel): the barrel's built dist re-exports via CJS __exportStar, which the
// app bundler (rollup) cannot statically analyse for named value exports.
import { filterFields, type FilterFieldDefinition } from '@aether/shared/filter-fields';
import {
  surfaceCapabilities,
  type ExplorationSurfaceId,
  type SurfaceCapability,
} from '@aether/shared/surface-capabilities';
import type { FilterOperator } from '@aether/shared/graph-contract';

const FIELD_BY_ID: ReadonlyMap<string, FilterFieldDefinition> = new Map(
  filterFields.map((f) => [f.id, f]),
);

/** The full registry, sorted by id (as generated). */
export function allFilterFields(): readonly FilterFieldDefinition[] {
  return filterFields;
}

/** Resolve a field definition by its registry id, or `undefined` if unknown. */
export function getFilterField(id: string): FilterFieldDefinition | undefined {
  return FIELD_BY_ID.get(id);
}

/** True iff `id` is a known registry field. */
export function isKnownField(id: string): boolean {
  return FIELD_BY_ID.has(id);
}

/** The operators a field registered — the ONLY operators a builder may offer. */
export function operatorsForField(id: string): readonly FilterOperator[] {
  return FIELD_BY_ID.get(id)?.operators ?? [];
}

/** Whether `op` is registered for `field` (rejects mismatched field/op pairs). */
export function isOperatorValidForField(field: string, op: FilterOperator): boolean {
  return operatorsForField(field).includes(op);
}

/** Declared capabilities for a surface. */
export function surfaceCapability(surfaceId: ExplorationSurfaceId): SurfaceCapability {
  return surfaceCapabilities[surfaceId];
}

/**
 * Fields a surface can filter on: those whose category is in the surface's
 * declared `supportedFieldCategories`. Order follows the registry (id-sorted).
 */
export function filterFieldsForSurface(
  surfaceId: ExplorationSurfaceId,
): readonly FilterFieldDefinition[] {
  const cap = surfaceCapabilities[surfaceId];
  if (!cap) return [];
  const allowed = new Set<string>(cap.supportedFieldCategories);
  return filterFields.filter((f) => allowed.has(f.category));
}

/** Whether a surface id is one the fabric knows about. */
export function isKnownSurface(surfaceId: string): surfaceId is ExplorationSurfaceId {
  return surfaceId in surfaceCapabilities;
}

/**
 * Operators that carry no value (unary predicates). A value input must be
 * suppressed for these in the builder.
 */
const VALUELESS_OPERATORS: ReadonlySet<FilterOperator> = new Set(['exists', 'not_exists']);

export function isValuelessOperator(op: FilterOperator): boolean {
  return VALUELESS_OPERATORS.has(op);
}

/** Operators whose value is a list. */
const MULTI_VALUE_OPERATORS: ReadonlySet<FilterOperator> = new Set(['in', 'not_in']);

export function isMultiValueOperator(op: FilterOperator): boolean {
  return MULTI_VALUE_OPERATORS.has(op);
}

/** Operators whose value is a `{ from, to }` range. */
const RANGE_OPERATORS: ReadonlySet<FilterOperator> = new Set(['between']);

export function isRangeOperator(op: FilterOperator): boolean {
  return RANGE_OPERATORS.has(op);
}
