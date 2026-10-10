import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import type { CreateComparisonDefinitionRequest } from './comparison-api';

export const mountedComparisonModes = ['entity_vs_entity', 'entity_vs_history'] as const;
export type MountedComparisonMode = typeof mountedComparisonModes[number];

/** Dimensions with a real collector in comparison/collection.py. */
export const mountedComparisonDimensions = [
  'behavior',
  'sessions',
  'devices',
  'campaigns',
  'economic_activity',
  'temporal_activity',
  'geography',
] as const;
export type MountedComparisonDimension = typeof mountedComparisonDimensions[number];

export interface ComparisonDraft {
  mode: MountedComparisonMode;
  subjectId: string;
  baselineEntityId: string;
  historyStart: string;
  historyEnd: string;
  dimension: MountedComparisonDimension;
}

export function preflightComparisonDraft(draft: ComparisonDraft): string[] {
  const issues: string[] = [];
  if (!draft.subjectId.trim()) issues.push('Subject entity is required.');
  if (draft.mode === 'entity_vs_entity' && !draft.baselineEntityId.trim()) {
    issues.push('Baseline entity is required for entity-vs-entity.');
  }
  if (draft.mode === 'entity_vs_history') {
    if (!draft.historyStart || !draft.historyEnd) {
      issues.push('Historical start and end are required.');
    } else if (new Date(draft.historyEnd).getTime() <= new Date(draft.historyStart).getTime()) {
      issues.push('Historical end must be after the start.');
    }
  }
  if (!mountedComparisonDimensions.includes(draft.dimension)) {
    issues.push(`Dimension "${draft.dimension}" has no mounted observation source.`);
  }
  return issues;
}

export function definitionRequestFromContext(
  context: ExplorationContextV1,
  draft: ComparisonDraft,
): CreateComparisonDefinitionRequest {
  const tenantId = context.scope.tenant_id;
  const subject = {
    subject_type: 'entity',
    subject_id: draft.subjectId.trim(),
    tenant_id: tenantId,
    ...(context.temporal.as_of ? { as_of: context.temporal.as_of } : {}),
  };
  const baseline = draft.mode === 'entity_vs_entity'
    ? {
        baseline_type: 'entity',
        subject: {
          subject_type: 'entity',
          subject_id: draft.baselineEntityId.trim(),
          tenant_id: tenantId,
        },
      }
    : {
        baseline_type: 'historical',
        window_start: new Date(draft.historyStart).toISOString(),
        window_end: new Date(draft.historyEnd).toISOString(),
      };
  return {
    name: `${draft.mode}:${draft.subjectId.trim()}`,
    mode: draft.mode,
    subject,
    baseline,
    dimensions: [draft.dimension],
    temporal_mode: context.temporal.mode,
  };
}
