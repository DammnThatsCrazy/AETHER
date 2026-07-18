import type {
  ApplicabilityReport,
  ExplorationCompleteness,
  ExplorationTruth,
} from '@aether/shared/exploration-contract';
import { Badge } from '../../components/badge';
import { EmptyState } from '../../components/empty-state';
import { ErrorState } from '../../components/error-state';
import { FreshnessIndicator } from '../../components/freshness-indicator';
import type { ExplorationStatus } from '../store';
import { completenessNotices, dimensionStateStyle, suppressedFilterCount } from '../truth-model';

export interface TruthBannerProps {
  readonly status: ExplorationStatus;
  readonly surfaceLabel?: string | undefined;
  readonly truth?: ExplorationTruth | null | undefined;
  readonly completeness?: ExplorationCompleteness | null | undefined;
  readonly applicability?: ApplicabilityReport | null | undefined;
  readonly error?: string | null | undefined;
  readonly onRetry?: (() => void) | undefined;
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
        {truth?.freshness_watermark && (
          <FreshnessIndicator
            computedAt={truth.freshness_watermark}
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
      {suppressed > 0 && (
        <p className="text-[11px] text-text-muted">
          Some requested filters were withheld by consent or cohort-minimum policy.
        </p>
      )}
    </div>
  );
}
