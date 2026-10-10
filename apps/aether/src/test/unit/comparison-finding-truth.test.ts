import { describe, expect, it } from 'vitest';
import { assessFinding } from '@aether-app/features/comparison';
import type {
  ComparisonFindingDetail,
  ComparisonRunDetail,
} from '@aether-app/features/comparison';

const run: ComparisonRunDetail = {
  run_id: 'run-1',
  definition_id: 'definition-1',
  tenant_id: 'tenant-1',
  state: 'completed',
  alignment_decisions: [{
    dimension: 'behavior',
    outcome: 'aligned',
    pairs: [{
      name: 'conversion_rate',
      unit: 'percent',
      subject_value: 8,
      baseline_value: 5,
    }],
    subject_only_metrics: [],
    baseline_only_metrics: [],
  }],
};

const finding: ComparisonFindingDetail = {
  id: 'finding-1',
  comparison_run_id: 'run-1',
  tenant_id: 'tenant-1',
  finding_type: 'difference',
  dimension: 'behavior',
  metric: 'conversion_rate',
  observed_value: 8,
  baseline_value: 5,
  confidence: 0.93,
  materiality: 0.61,
  causal_claim: 'associational',
  evidence_basis: 'canonical_facts',
};

describe('comparison finding truth assessment', () => {
  it('exposes values only when alignment, units, and evidence are present', () => {
    expect(assessFinding(finding, run)).toEqual({
      finding,
      unit: 'percent',
      comparable: true,
      missingInputs: [],
    });
  });

  it('blocks unitless or provenance-free values', () => {
    const assessed = assessFinding(
      { ...finding, evidence_basis: null },
      {
        ...run,
        alignment_decisions: [{
          ...run.alignment_decisions![0]!,
          pairs: [{ ...run.alignment_decisions![0]!.pairs[0]!, unit: '' }],
        }],
      },
    );

    expect(assessed.comparable).toBe(false);
    expect(assessed.missingInputs).toEqual(expect.arrayContaining(['unit', 'provenance']));
  });

  it('blocks values refused by run alignment', () => {
    const assessed = assessFinding(finding, {
      ...run,
      alignment_decisions: [{
        ...run.alignment_decisions![0]!,
        outcome: 'blocked_missing_provenance',
      }],
    });

    expect(assessed.comparable).toBe(false);
    expect(assessed.missingInputs).toContain('alignment:blocked_missing_provenance');
  });
});
