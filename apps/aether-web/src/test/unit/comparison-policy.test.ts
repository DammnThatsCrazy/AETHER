import { describe, expect, it } from 'vitest';
import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import {
  definitionRequestFromContext,
  preflightComparisonDraft,
  type ComparisonDraft,
} from '@aether-app/features/comparison';

const context: ExplorationContextV1 = {
  version: '1',
  scope: { tenant_id: 'tenant-7', surface: 'graph' },
  temporal: {
    mode: 'as_of',
    field: 'observed_at',
    as_of: '2026-07-01T00:00:00.000Z',
    timezone: 'UTC',
  },
};

const entityDraft: ComparisonDraft = {
  mode: 'entity_vs_entity',
  subjectId: 'subject-1',
  baselineEntityId: 'baseline-2',
  historyStart: '',
  historyEnd: '',
  dimension: 'behavior',
};

describe('comparison workbench policy', () => {
  it('preserves the canonical tenant and temporal authority for entity comparisons', () => {
    const request = definitionRequestFromContext(context, entityDraft);

    expect(request.subject).toEqual({
      subject_type: 'entity',
      subject_id: 'subject-1',
      tenant_id: 'tenant-7',
      as_of: '2026-07-01T00:00:00.000Z',
    });
    expect(request.baseline).toEqual({
      baseline_type: 'entity',
      subject: {
        subject_type: 'entity',
        subject_id: 'baseline-2',
        tenant_id: 'tenant-7',
      },
    });
    expect(request.temporal_mode).toBe('as_of');
  });

  it('blocks invalid historical windows before creating a definition', () => {
    const issues = preflightComparisonDraft({
      ...entityDraft,
      mode: 'entity_vs_history',
      historyStart: '2026-07-20',
      historyEnd: '2026-07-10',
    });

    expect(issues).toContain('Historical end must be after the start.');
  });

  it('refuses dimensions without a backend collector', () => {
    const issues = preflightComparisonDraft({
      ...entityDraft,
      dimension: 'identity' as ComparisonDraft['dimension'],
    });

    expect(issues).toContain('Dimension "identity" has no mounted observation source.');
  });
});
