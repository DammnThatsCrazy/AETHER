import { describe, it, expect } from 'vitest';
import {
  dimensionStateStyle,
  suppressedFilterCount,
  completenessNotices,
  measurementTruthNotices,
  observationClassLabel,
} from './truth-model';

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

  it('uses the canonical observation-class labels', () => {
    expect(observationClassLabel('observed')).toBe('Observed');
    expect(observationClassLabel('probabilistic')).toBe('Inferred / probabilistic');
  });

  it('makes non-causal, uncertain, restated measurements explicit', () => {
    expect(
      measurementTruthNotices({
        value_state: 'partial',
        context: 'Paid acquisition',
        unit: 'USD',
        confidence: 0.81,
        uncertainty: '± 4.2%',
        evidence_basis: ['touchpoints', 'conversion ledger'],
        freshness: null,
        restatement: { restated: true, supersedes_measurement_id: 'm-1' },
        attribution_vs_causal: 'attribution',
        materiality_basis: null,
      }),
    ).toEqual([
      'Confidence 81%.',
      'Uncertainty: ± 4.2%.',
      'Restates m-1.',
      'Attribution result — not a causal claim.',
      'No materiality basis was reported.',
    ]);
  });
});
