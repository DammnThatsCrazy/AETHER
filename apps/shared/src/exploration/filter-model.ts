/**
 * Pure, registry-driven models for the exploration filter UI. Kept free of JSX
 * so the field/operator/value logic is unit-testable without a DOM: the
 * components (FilterBuilder, FilterBar) are thin renderers over these.
 */

import type {
  FilterDisposition,
  ApplicabilityReport,
} from '@aether/shared/exploration-contract';
import type {
  FilterExpression,
  FilterGroup,
  FilterOperator,
} from '@aether/shared/graph-contract';
import type { FilterFieldDataType } from '@aether/shared/filter-fields';
import {
  getFilterField,
  isKnownField,
  isOperatorValidForField,
  isValuelessOperator,
  isMultiValueOperator,
  isRangeOperator,
} from './registry';

/** Human-readable operator glyphs for chip/summary rendering. */
const OPERATOR_LABELS: Record<FilterOperator, string> = {
  eq: '=',
  neq: '≠',
  gt: '>',
  gte: '≥',
  lt: '<',
  lte: '≤',
  in: 'in',
  not_in: 'not in',
  exists: 'exists',
  not_exists: 'not set',
  contains: 'contains',
  starts_with: 'starts with',
  between: 'between',
  relative_time: 'within',
  threshold: '≥',
};

export function operatorLabel(op: FilterOperator): string {
  return OPERATOR_LABELS[op] ?? op;
}

/** Coerce a raw string input to the field's declared value type. */
export function coerceScalar(dataType: FilterFieldDataType, raw: string): unknown {
  const trimmed = raw.trim();
  switch (dataType) {
    case 'number': {
      const n = Number(trimmed);
      return Number.isFinite(n) ? n : null;
    }
    case 'boolean':
      return trimmed === 'true' || trimmed === '1';
    default:
      // string, enum, entity_ref, geography, datetime — opaque tokens / ISO.
      return trimmed;
  }
}

/**
 * Build a registry-VALID FilterExpression from a field id, operator, and raw
 * input, or null if the field/op pair is not registered or the value is empty.
 * The value is shaped per the operator's arity (valueless / list / range /
 * scalar) and coerced to the field's data type.
 */
export function buildFilterExpression(
  field: string,
  op: FilterOperator,
  raw: string,
): FilterExpression | null {
  if (!isKnownField(field) || !isOperatorValidForField(field, op)) return null;
  const def = getFilterField(field);
  if (!def) return null;

  if (isValuelessOperator(op)) {
    return { field, op, value: null };
  }
  if (isMultiValueOperator(op)) {
    const items = raw
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
      .map((v) => coerceScalar(def.dataType, v))
      .filter((v) => v !== null && v !== '');
    return items.length ? { field, op, value: items } : null;
  }
  if (isRangeOperator(op)) {
    const parts = raw.split('..').map((s) => s.trim());
    if (parts.length !== 2 || parts[0] === '' || parts[1] === '') return null;
    const from = coerceScalar(def.dataType, parts[0]!);
    const to = coerceScalar(def.dataType, parts[1]!);
    if (from === null || to === null) return null;
    return { field, op, value: { from, to } };
  }
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const value = coerceScalar(def.dataType, trimmed);
  if (value === null) return null;
  return { field, op, value };
}

/** Render a filter value to a compact display string. */
export function formatFilterValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.map((v) => String(v)).join(', ');
  if (typeof value === 'object') {
    const range = value as { from?: unknown; to?: unknown };
    if ('from' in range || 'to' in range) return `${String(range.from)}–${String(range.to)}`;
  }
  return String(value);
}

export interface FilterChipModel {
  /** Index within the top-level population group (for removal). */
  index: number;
  field: string;
  label: string;
  op: FilterOperator;
  valueText: string;
  isGroup: boolean;
  disposition?: FilterDisposition | undefined;
  reason?: string | null | undefined;
}

function isGroup(node: FilterExpression | FilterGroup): node is FilterGroup {
  return (node as FilterGroup).logic !== undefined;
}

function dispositionFor(
  field: string,
  applicability: ApplicabilityReport | null | undefined,
): { disposition?: FilterDisposition | undefined; reason?: string | null | undefined } {
  const entry = applicability?.entries.find((e) => e.field === field);
  return entry ? { disposition: entry.disposition, reason: entry.reason } : {};
}

/**
 * Top-level chips for the FilterBar: one per predicate in the population's
 * top-level group, each annotated with its applicability disposition (so a
 * silently-dropped filter is impossible to render). Nested groups become one
 * "group" chip.
 */
export function chipsFromContext(
  population: FilterGroup | null | undefined,
  applicability?: ApplicabilityReport | null,
): FilterChipModel[] {
  if (!population) return [];
  return population.expressions.map((node, index) => {
    if (isGroup(node)) {
      return {
        index,
        field: `(${node.logic.toLowerCase()} group)`,
        label: `${node.logic} group`,
        op: 'eq' as FilterOperator,
        valueText: `${node.expressions.length} conditions`,
        isGroup: true,
      };
    }
    const def = getFilterField(node.field);
    return {
      index,
      field: node.field,
      label: def?.label ?? node.field,
      op: node.op,
      valueText: formatFilterValue(node.value),
      isGroup: false,
      ...dispositionFor(node.field, applicability),
    };
  });
}
