import type { GraphContext } from '@aether/shared/graph-context-contract';

import { Badge } from '../../components/badge';
import { Button } from '../../components/button';
import { cn } from '../../utils/cn';

type CanonicalTemporal = NonNullable<GraphContext['query']>['temporal'];
type GraphTemporal = GraphContext['temporal'] | CanonicalTemporal;
type TemporalMode = 'live' | 'point' | 'range' | 'compare' | 'diff';

const TEMPORAL_MODES: readonly TemporalMode[] = ['live', 'point', 'range', 'compare', 'diff'];
const TEMPORAL_LABELS: Record<TemporalMode, string> = {
  live: 'Live',
  point: 'Point',
  range: 'Range',
  compare: 'Compare',
  diff: 'Diff',
};

export interface GraphTimeRailProps {
  /** A full GraphContext or its temporal/query projection. */
  readonly context?: Pick<GraphContext, 'temporal' | 'query'> | null | undefined;
  /** Direct temporal data is useful when the host already selected the canonical field. */
  readonly temporal?: GraphTemporal | null | undefined;
  /** History positions are one-based and supplied by the owning controller. */
  readonly historyPosition?: number | undefined;
  readonly historyCount?: number | undefined;
  readonly onPrevious?: (() => void) | undefined;
  readonly onNext?: (() => void) | undefined;
  readonly onLive?: (() => void) | undefined;
  readonly className?: string | undefined;
}

function modeFromTemporal(temporal: GraphTemporal | null | undefined): TemporalMode | null {
  if (!temporal) return null;
  switch (temporal.mode) {
    case 'live':
    case 'point':
    case 'range':
    case 'compare':
    case 'diff':
      return temporal.mode;
    case 'window':
      return 'range';
    case 'as_of':
      return 'point';
    case 'relative':
      return null;
    default:
      return null;
  }
}

function temporalDetail(temporal: GraphTemporal | null | undefined): string | null {
  if (!temporal) return null;
  if (temporal.mode === 'point' && temporal.as_of) return `As of ${temporal.as_of}`;
  if (temporal.mode === 'as_of' && temporal.as_of) return `As of ${temporal.as_of}`;
  if (temporal.mode === 'compare') {
    const then = 'known_then' in temporal
      ? (typeof temporal.known_then === 'string' ? temporal.known_then : null)
      : ('compare_to' in temporal && typeof temporal.compare_to === 'string' ? temporal.compare_to : null);
    const now = 'known_now' in temporal
      ? (typeof temporal.known_now === 'string' ? temporal.known_now : null)
      : ('as_of' in temporal && typeof temporal.as_of === 'string' ? temporal.as_of : null);
    if (then && now) return `${then} → ${now}`;
  }
  if (temporal.mode === 'range' || temporal.mode === 'window') {
    const range = temporal.range;
    if (range?.kind === 'instant') return `${range.start} → ${range.endExclusive}`;
    if (range?.kind === 'local_date') return `${range.startDate} → ${range.endDateExclusive}`;
  }
  return null;
}

function temporalSource(
  context: Pick<GraphContext, 'temporal' | 'query'> | null | undefined,
  temporal: GraphTemporal | null | undefined,
): GraphTemporal | null {
  if (temporal !== undefined) return temporal;
  return context?.query?.temporal ?? context?.temporal ?? null;
}

/** A controlled temporal/history rail; it does not own navigation state. */
export function GraphTimeRail({
  context,
  temporal,
  historyPosition = 0,
  historyCount = 0,
  onPrevious,
  onNext,
  onLive,
  className,
}: GraphTimeRailProps) {
  const source = temporalSource(context, temporal);
  const activeMode = modeFromTemporal(source);
  const detail = temporalDetail(source);
  const historyAvailable = Number.isFinite(historyPosition)
    && Number.isFinite(historyCount)
    && historyPosition >= 1
    && historyCount >= 1;

  return (
    <nav
      className={cn('graph-time-rail flex min-w-0 flex-wrap items-center gap-3 border-t border-border-default bg-surface-raised px-3 py-2', className)}
      data-testid="graph-time-rail"
      aria-label="Graph time navigation"
    >
      <div className="flex items-center gap-1" role="group" aria-label="Temporal modes">
        {TEMPORAL_MODES.map((mode) => (
          <Badge key={mode} variant={activeMode === mode ? 'accent' : 'default'} size="sm">
            <span aria-current={activeMode === mode ? 'true' : undefined}>{TEMPORAL_LABELS[mode]}</span>
          </Badge>
        ))}
      </div>
      <span className="min-w-0 flex-1 truncate text-[11px] text-text-secondary" data-temporal-detail>
        {detail ?? (activeMode === null ? 'Temporal context unavailable' : `Temporal mode: ${TEMPORAL_LABELS[activeMode]}`)}
      </span>
      <span className="text-[11px] text-text-muted" data-history-state={historyAvailable ? 'available' : 'unavailable'}>
        {historyAvailable ? `History ${historyPosition} of ${historyCount}` : 'History unavailable'}
      </span>
      {(onPrevious || onNext) && (
        <span className="flex items-center gap-1" role="group" aria-label="History navigation">
          {onPrevious && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onPrevious}
              disabled={!historyAvailable || historyPosition <= 1}
              aria-label="Previous history point"
            >
              Previous
            </Button>
          )}
          {onNext && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onNext}
              disabled={!historyAvailable || historyPosition >= historyCount}
              aria-label="Next history point"
            >
              Next
            </Button>
          )}
        </span>
      )}
      {onLive && (
        <Button
          type="button"
          variant={activeMode === 'live' ? 'primary' : 'secondary'}
          size="sm"
          onClick={onLive}
          aria-label="Return to live graph"
          aria-pressed={activeMode === 'live'}
        >
          Live
        </Button>
      )}
    </nav>
  );
}
