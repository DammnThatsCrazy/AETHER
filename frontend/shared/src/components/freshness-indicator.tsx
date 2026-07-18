import { formatTime } from '../time/format';
import { useTimeContext } from '../time/time-provider';
import { useNow } from '../time/use-now';
import { cn } from '../utils/cn';

interface FreshnessIndicatorProps {
  computedAt: string | null | undefined;
  onRefresh?: () => void;
  className?: string;
}

function getState(computedAt: string, now: number) {
  const ageMs = now - new Date(computedAt).getTime();
  const ageMin = ageMs / 60_000;
  if (ageMin < 5) return 'live' as const;
  if (ageMin < 15) return 'recent' as const;
  return 'stale' as const;
}

export function FreshnessIndicator({ computedAt, onRefresh, className }: FreshnessIndicatorProps) {
  const context = useTimeContext();
  const now = useNow(30_000);

  if (!computedAt) return null;

  const state = getState(computedAt, now);

  const dotClass = state === 'live' ? 'bg-success' : state === 'recent' ? 'bg-warning' : 'bg-danger';
  const textClass = state === 'live' ? 'text-success' : state === 'recent' ? 'text-warning' : 'text-danger';

  const formattedTime = formatTime(computedAt, context);

  return (
    <div className={cn('flex items-center gap-1.5 font-mono text-xs', className)}>
      <span className={cn('w-1.5 h-1.5 rounded-full inline-block flex-shrink-0', dotClass)} />
      <span className={textClass}>{state}</span>
      <span className="text-text-muted">as of {formattedTime}</span>
      {state === 'stale' && onRefresh && (
        <button
          onClick={onRefresh}
          className="text-accent underline hover:no-underline ml-1"
        >
          [↻] Refresh
        </button>
      )}
    </div>
  );
}
