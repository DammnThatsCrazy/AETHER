/**
 * Pure models for the TruthBanner — the honest-state helpers, kept out of JSX
 * so the state/notice logic is unit-testable.
 */

import type { DimensionState } from '@aether/shared/dimension-state';
import type { DimensionFreshness } from '@aether/shared/dimension-state';
import type { ObservationClass } from '@aether/shared/graph-contract';
import type {
  ApplicabilityReport,
  ExplorationCompleteness,
} from '@aether/shared/exploration-contract';

type BadgeVariant = 'success' | 'info' | 'warning' | 'danger' | 'default';

export type MeasurementCausality =
  | 'attribution'
  | 'causal'
  | 'descriptive_association'
  | 'not_applicable';

/**
 * Presentation contract for a reported measurement. These fields prevent a
 * scalar from appearing without the evidence and interpretation needed to use
 * it safely. It extends ExplorationTruth rather than creating another
 * availability-state vocabulary: `value_state` is the canonical DimensionState.
 */
export interface MeasurementTruth {
  readonly value_state: DimensionState;
  readonly context: string;
  readonly unit: string | null;
  readonly confidence: number | null;
  readonly uncertainty: string | null;
  readonly evidence_basis: readonly string[];
  readonly freshness: DimensionFreshness | null;
  readonly restatement: {
    readonly restated: boolean;
    readonly supersedes_measurement_id?: string | null;
  };
  readonly attribution_vs_causal: MeasurementCausality;
  readonly materiality_basis: string | null;
}

const OBSERVATION_LABELS: Record<ObservationClass, string> = {
  observed: 'Observed',
  deterministic: 'Deterministic',
  derived: 'Derived',
  probabilistic: 'Inferred / probabilistic',
  predicted: 'Predicted',
  simulated: 'Simulated',
  manually_asserted: 'Manually asserted',
  externally_enriched: 'Externally enriched',
};

export function observationClassLabel(observationClass: ObservationClass): string {
  return OBSERVATION_LABELS[observationClass];
}

export function measurementTruthNotices(measurement: MeasurementTruth): string[] {
  const notes: string[] = [];
  if (measurement.confidence != null) notes.push(`Confidence ${Math.round(measurement.confidence * 100)}%.`);
  if (measurement.uncertainty) notes.push(`Uncertainty: ${measurement.uncertainty}.`);
  if (measurement.evidence_basis.length === 0) notes.push('No evidence basis was reported.');
  if (measurement.restatement.restated) {
    notes.push(
      measurement.restatement.supersedes_measurement_id
        ? `Restates ${measurement.restatement.supersedes_measurement_id}.`
        : 'This measurement is a restatement.',
    );
  }
  if (measurement.attribution_vs_causal !== 'causal') {
    notes.push(
      measurement.attribution_vs_causal === 'attribution'
        ? 'Attribution result — not a causal claim.'
        : measurement.attribution_vs_causal === 'descriptive_association'
          ? 'Descriptive association — not a causal claim.'
          : 'No causal interpretation applies.',
    );
  }
  if (!measurement.materiality_basis) notes.push('No materiality basis was reported.');
  return notes;
}

const DIMENSION_STATE_STYLES: Record<DimensionState, { variant: BadgeVariant; label: string }> = {
  ready: { variant: 'success', label: 'Ready' },
  empty: { variant: 'default', label: 'Empty' },
  partial: { variant: 'warning', label: 'Partial' },
  stale: { variant: 'warning', label: 'Stale' },
  insufficient_data: { variant: 'warning', label: 'Insufficient data' },
  degraded: { variant: 'danger', label: 'Degraded' },
  suppressed: { variant: 'danger', label: 'Suppressed' },
  not_applicable: { variant: 'default', label: 'N/A' },
  pending: { variant: 'info', label: 'Pending' },
  error: { variant: 'danger', label: 'Error' },
};

export function dimensionStateStyle(state: DimensionState): { variant: BadgeVariant; label: string } {
  return DIMENSION_STATE_STYLES[state];
}

/** How many requested filters the surface withheld (consent / cohort minimum). */
export function suppressedFilterCount(applicability?: ApplicabilityReport | null): number {
  return applicability?.entries.filter((e) => e.disposition === 'suppressed').length ?? 0;
}

/** Human-readable completeness caveats — an incomplete result must say so. */
export function completenessNotices(completeness?: ExplorationCompleteness | null): string[] {
  if (!completeness) return [];
  const notes: string[] = [];
  if (completeness.sampled) notes.push('Sampled — not the full population.');
  if (completeness.truncated) {
    notes.push(`Truncated${completeness.truncation_reason ? ` (${completeness.truncation_reason})` : ''}.`);
  }
  if (completeness.coverage_percent != null && completeness.coverage_percent < 100) {
    notes.push(`Coverage ${completeness.coverage_percent}%.`);
  }
  return notes;
}
