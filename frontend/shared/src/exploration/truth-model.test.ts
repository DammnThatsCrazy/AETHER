import { describe, it, expect } from 'vitest';
import { dimensionStateStyle, suppressedFilterCount, completenessNotices } from './truth-model';

describe('truth-model', () => {
  it('maps dimension states to honest, distinct variants', () => {
    expect(dimensionStateStyle('ready').variant).toBe('success');
    expect(dimensionStateStyle('partial').variant).toBe('warning');
    expect(dimensionStateStyle('suppressed').variant).toBe('danger');
    expect(dimensionStateStyle('error').variant).toBe('danger');
    expect(dimensionStateStyle('pending').variant).toBe('info');
  });

  it('counts suppressed filters from the applicability report', () => {
    expect(
      suppressedFilterCount({
        entries: [
          { field: 'geography.city', disposition: 'suppressed' },
          { field: 'risk.score', disposition: 'applied' },
          { field: 'entity.tags', disposition: 'suppressed' },
        ],
      }),
    ).toBe(2);
    expect(suppressedFilterCount(null)).toBe(0);
  });

  it('produces completeness caveats only when incomplete', () => {
    expect(
      completenessNotices({
        complete: false,
        sampled: true,
        truncated: true,
        truncation_reason: 'node_budget',
        coverage_percent: 60,
      }),
    ).toEqual(['Sampled — not the full population.', 'Truncated (node_budget).', 'Coverage 60%.']);
    expect(completenessNotices({ complete: true, sampled: false, truncated: false })).toEqual([]);
    expect(completenessNotices(null)).toEqual([]);
  });
});
