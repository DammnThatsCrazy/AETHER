import type {
  ApplicabilityReport,
  ExplorationCompleteness,
  ExplorationTruth,
} from '@aether/shared/exploration-contract';
import type { ObservationClass } from '@aether/shared/graph-contract';
import { Badge } from '../../components/badge';
import { EmptyState } from '../../components/empty-state';
import { ErrorState } from '../../components/error-state';
import { FreshnessIndicator } from '../../components/freshness-indicator';
import { CapabilityStateBadge } from '../../status/capability-state-badge';
import type { CapabilityState } from '../../status/capability-state';
import type { ExplorationStatus } from '../store';
import {
  completenessNotices,
  dimensionStateStyle,
  measurementTruthNotices,
  observationClassLabel,
  suppressedFilterCount,
  type MeasurementTruth,
} from '../truth-model';

export interface TruthBannerProps {
  readonly status: ExplorationStatus;
  readonly surfaceLabel?: string | undefined;
  readonly truth?: ExplorationTruth | null | undefined;
  readonly completeness?: ExplorationCompleteness | null | undefined;
  readonly applicability?: ApplicabilityReport | null | undefined;
  readonly error?: string | null | undefined;
  readonly onRetry?: (() => void) | undefined;
  /** Runtime readiness; uses the existing capability-state vocabulary. */
  readonly readinessState?: CapabilityState | null | undefined;
  readonly observationClass?: ObservationClass | null | undefined;
  readonly measurement?: MeasurementTruth | null | undefined;
}

/**
 * One honest-state banner. Consolidates the NotEnabledOrError pattern
 * (feature-flag-off vs. error), the truth/value state badge, the freshness
 * watermark, completeness caveats, and consent/cohort suppression notices — so
 * a surface never renders a blank that reads as "no activity".
 */
export function TruthBanner({
  status,
  surfaceLabel = 'This surface',
  truth,
  completeness,
  applicability,
  error,
  onRetry,
  readinessState,
  observationClass,
  measurement,
}: TruthBannerProps) {
  if (status === 'not_enabled') {
    return (
      <EmptyState
        title={`${surfaceLabel} is not enabled`}
        description="This exploration surface is feature-flagged off for your deployment. Contact your operator to enable it."
        icon="◌"
      />
    );
  }
  if (status === 'error') {
    return <ErrorState message={error ?? 'Exploration request failed.'} {...(onRetry ? { onRetry } : {})} />;
  }
  if (status === 'idle') {
    return <p className="text-xs text-text-muted">Configure filters, then run the exploration.</p>;
  }
  if (status === 'loading') {
    return <p className="text-xs text-text-muted">Loading…</p>;
  }

  const overall = truth?.overall_state;
  const suppressed = suppressedFilterCount(applicability);
  const notices = completenessNotices(completeness);
  const measurementNotices = measurement ? measurementTruthNotices(measurement) : [];
  const freshnessWatermark =
    truth?.freshness_watermark ?? measurement?.freshness?.watermark;

  return (
    <div
      className="flex flex-col gap-2 rounded border border-border-default bg-surface-raised px-3 py-2"
      data-testid="truth-banner"
    >
      <div className="flex flex-wrap items-center gap-2">
        {overall && (
          <Badge variant={dimensionStateStyle(overall).variant} size="sm">
            {dimensionStateStyle(overall).label}
          </Badge>
        )}
        {readinessState && <CapabilityStateBadge state={readinessState} />}
        {observationClass && (
          <Badge variant="info" size="sm">
            <span data-observation-class={observationClass}>
              {observationClassLabel(observationClass)}
            </span>
          </Badge>
        )}
        {freshnessWatermark && (
          <FreshnessIndicator
            computedAt={freshnessWatermark}
            {...(onRetry ? { onRefresh: onRetry } : {})}
          />
        )}
        {suppressed > 0 && (
          <Badge variant="danger" size="sm">
            {suppressed} suppressed
          </Badge>
        )}
      </div>
      {notices.length > 0 && (
        <ul className="text-[11px] text-warning">
          {notices.map((note) => (
            <li key={note}>· {note}</li>
          ))}
        </ul>
      )}
      {measurement && (
        <div data-testid="measurement-truth" className="text-[11px] text-text-secondary">
          <dl className="grid grid-cols-[auto_1fr] gap-x-2">
            <dt>Value state</dt>
            <dd>{dimensionStateStyle(measurement.value_state).label}</dd>
            <dt>Context</dt>
            <dd>{measurement.context}</dd>
            <dt>Unit</dt>
            <dd>{measurement.unit ?? 'Not reported'}</dd>
            <dt>Evidence</dt>
            <dd>{measurement.evidence_basis.length > 0 ? measurement.evidence_basis.join(', ') : 'Not reported'}</dd>
            <dt>Interpretation</dt>
            <dd>{measurement.attribution_vs_causal.replace(/_/g, ' ')}</dd>
            <dt>Materiality</dt>
            <dd>{measurement.materiality_basis ?? 'Not reported'}</dd>
          </dl>
          {measurementNotices.length > 0 && (
            <ul className="mt-1 text-warning">
              {measurementNotices.map((note) => <li key={note}>· {note}</li>)}
            </ul>
          )}
        </div>
      )}
      {suppressed > 0 && (
        <p className="text-[11px] text-text-muted">
          Some requested filters were withheld by consent or cohort-minimum policy.
        </p>
      )}
    </div>
  );
}
