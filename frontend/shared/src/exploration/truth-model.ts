/**
 * Pure models for the TruthBanner — the honest-state helpers, kept out of JSX
 * so the state/notice logic is unit-testable.
 */

import type { DimensionState } from '@aether/shared/dimension-state';
import type {
  ApplicabilityReport,
  ExplorationCompleteness,
} from '@aether/shared/exploration-contract';

type BadgeVariant = 'success' | 'info' | 'warning' | 'danger' | 'default';

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
