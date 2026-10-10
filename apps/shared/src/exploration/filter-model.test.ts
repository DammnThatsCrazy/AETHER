import { describe, it, expect } from 'vitest';
import type { ApplicabilityReport } from '@aether/shared/exploration-contract';
import type { FilterGroup } from '@aether/shared/graph-contract';
import {
  buildFilterExpression,
  chipsFromContext,
  formatFilterValue,
  operatorLabel,
} from './filter-model';

describe('buildFilterExpression produces registry-valid predicates', () => {
  it('builds a scalar numeric predicate', () => {
    expect(buildFilterExpression('risk.score', 'gte', '0.8')).toEqual({
      field: 'risk.score',
      op: 'gte',
      value: 0.8,
    });
  });

  it('builds a multi-value (in) predicate as an array', () => {
    expect(buildFilterExpression('entity.type', 'in', 'human, agent')).toEqual({
      field: 'entity.type',
      op: 'in',
      value: ['human', 'agent'],
    });
  });

  it('builds a between predicate as a {from,to} range', () => {
    expect(buildFilterExpression('economic.ltv_usd', 'between', '10..100')).toEqual({
      field: 'economic.ltv_usd',
      op: 'between',
      value: { from: 10, to: 100 },
    });
  });

  it('builds a valueless (exists) predicate', () => {
    expect(buildFilterExpression('entity.cluster_id', 'exists', '')).toEqual({
      field: 'entity.cluster_id',
      op: 'exists',
      value: null,
    });
  });

  it('rejects an operator the field did not register', () => {
    expect(buildFilterExpression('risk.score', 'contains', '5')).toBeNull();
  });

  it('rejects an unknown (non-registry) field', () => {
    expect(buildFilterExpression('user.email', 'eq', 'a@b.c')).toBeNull();
  });

  it('rejects an empty scalar value (no accidental 0)', () => {
    expect(buildFilterExpression('risk.score', 'gte', '   ')).toBeNull();
  });
});

describe('chipsFromContext', () => {
  const population: FilterGroup = {
    logic: 'AND',
    expressions: [
      { field: 'risk.score', op: 'gte', value: 0.8 },
      { field: 'entity.type', op: 'in', value: ['human'] },
    ],
  };

  it('produces one chip per top-level predicate with the registry label', () => {
    const chips = chipsFromContext(population, null);
    expect(chips).toHaveLength(2);
    expect(chips[0]).toMatchObject({ field: 'risk.score', label: 'Risk score', valueText: '0.8', index: 0 });
    expect(chips[1]).toMatchObject({ field: 'entity.type', valueText: 'human', index: 1 });
  });

  it('annotates each chip with its applicability disposition', () => {
    const applicability: ApplicabilityReport = {
      entries: [{ field: 'risk.score', disposition: 'suppressed', reason: 'cohort below minimum' }],
    };
    const chips = chipsFromContext(population, applicability);
    expect(chips[0]!.disposition).toBe('suppressed');
    expect(chips[0]!.reason).toBe('cohort below minimum');
    expect(chips[1]!.disposition).toBeUndefined();
  });

  it('returns no chips for an empty population', () => {
    expect(chipsFromContext(null)).toEqual([]);
  });
});

describe('formatFilterValue / operatorLabel', () => {
  it('formats arrays and ranges compactly', () => {
    expect(formatFilterValue(['a', 'b'])).toBe('a, b');
    expect(formatFilterValue({ from: 1, to: 2 })).toBe('1–2');
    expect(formatFilterValue(null)).toBe('');
  });

  it('maps operators to glyphs', () => {
    expect(operatorLabel('gte')).toBe('≥');
    expect(operatorLabel('in')).toBe('in');
    expect(operatorLabel('between')).toBe('between');
  });
});
