import { useRef, type FC } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
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
  const parentRef = useRef<HTMLDivElement>(null);

  // Interleave steps with transition badges: [step0, transition1, step1, transition2, ...]
  const rowCount = steps.length === 0 ? 0 : steps.length * 2 - 1;

  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => (index % 2 === 0 ? 80 : 20),
    overscan: 8,
  });

  if (steps.length === 0 && !loading) {
    return (
      <div role="status" className="py-12 text-center text-text-muted text-sm">
        No steps found for the selected filters.
      </div>
    );
  }

  if (loading && steps.length === 0) {
    return (
      <div role="status" aria-label="Loading steps" className="space-y-2 animate-pulse">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-16 rounded bg-surface-secondary border-l-4 border-l-border" />
        ))}
      </div>
    );
  }

  const items = virtualizer.getVirtualItems();

  return (
    <div>
      <div
        ref={parentRef}
        className="overflow-auto"
        style={{ maxHeight: '70vh' }}
        role="list"
        aria-label="Journey timeline"
      >
        <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {items.map((virtualItem) => {
            const isTransition = virtualItem.index % 2 === 1;
            const stepIndex = isTransition
              ? (virtualItem.index + 1) / 2
              : virtualItem.index / 2;
            const step = steps[stepIndex];
            if (!step) return null;

            return (
              <div
                key={virtualItem.key}
                data-index={virtualItem.index}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualItem.start}px)`,
                }}
                role={isTransition ? undefined : 'listitem'}
              >
                {isTransition ? (
                  <JourneyTransitionBadge transitionType={step.transition_type} />
                ) : (
                  <JourneyStepCard step={step} position={stepIndex + 1} />
                )}
              </div>
            );
          })}
        </div>
      </div>

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
    </div>
  );
};
