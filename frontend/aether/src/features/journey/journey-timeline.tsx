import type { FC } from 'react';
import type { JourneyStep } from './use-unified-journey';
import { JourneyStepCard } from './journey-step-card';
import { JourneyTransitionBadge } from './journey-transition-badge';

interface Props {
  steps: JourneyStep[];
  hasMore: boolean;
  loading: boolean;
  onLoadMore: () => void;
}

export const JourneyTimeline: FC<Props> = ({ steps, hasMore, loading, onLoadMore }) => {
  if (steps.length === 0 && !loading) {
    return (
      <div role="status" className="py-12 text-center text-text-muted text-sm">
        No steps found for the selected filters.
      </div>
    );
  }

  return (
    <div className="space-y-0.5" role="list" aria-label="Journey timeline">
      {steps.map((step, i) => (
        <div key={step.step_id} role="listitem">
          {i > 0 && steps[i] && (
            <JourneyTransitionBadge transitionType={steps[i]!.transition_type} />
          )}
          <JourneyStepCard step={step} position={i + 1} />
        </div>
      ))}

      {hasMore && (
        <div className="pt-4 text-center">
          <button
            onClick={onLoadMore}
            disabled={loading}
            className="text-sm px-4 py-2 border border-border rounded hover:bg-surface-secondary disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-accent"
            aria-label="Load more journey steps"
          >
            {loading ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}

      {loading && steps.length === 0 && (
        <div role="status" aria-label="Loading steps" className="space-y-2 animate-pulse">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-16 rounded bg-surface-secondary border-l-4 border-l-border" />
          ))}
        </div>
      )}
    </div>
  );
};
