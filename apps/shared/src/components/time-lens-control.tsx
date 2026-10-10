/**
 * Compact time-lens switcher for app headers.
 *
 * Renders the four canonical lenses (viewer/tenant/event/utc) and the IANA
 * zone + offset the active lens resolves to, so the user always knows WHICH
 * clock the UI is rendering in. Surfaces with per-event zones feed them via
 * `useTimeContext(eventTimeZone)`; without one the event lens honestly falls
 * back to UTC (the provider's documented behavior).
 */

import { describeZone } from '../time/format';
import { useTime } from '../time/time-provider';
import { TIME_LENSES, type TimeLens } from '../time/types';
import { useNow } from '../time/use-now';
import { cn } from '../utils/cn';

const LENS_LABELS: Record<TimeLens, string> = {
  viewer: 'viewer',
  tenant: 'tenant',
  event: 'event',
  utc: 'utc',
};

const LENS_TITLES: Record<TimeLens, string> = {
  viewer: 'Render times in your resolved viewer zone',
  tenant: 'Render times in the tenant business zone',
  event: 'Render times in each event’s own zone (UTC when the surface has none)',
  utc: 'Render times in UTC',
};

const RESOLUTION_LABELS: Record<string, string> = {
  manual_preference: 'manual preference',
  device_automatic: 'device (automatic)',
  tenant_display_default: 'tenant default',
  utc_fallback: 'UTC fallback',
};

interface TimeLensControlProps {
  className?: string;
}

export function TimeLensControl({ className }: TimeLensControlProps) {
  const { resolved, lens, setLens, contextFor } = useTime();
  const now = useNow();
  const active = contextFor(lens);

  return (
    <div
      className={cn('flex items-center gap-2 font-mono text-xs', className)}
      role="group"
      aria-label="Time lens"
    >
      <span className="flex items-center rounded-md border border-border-default overflow-hidden">
        {TIME_LENSES.map((candidate) => (
          <button
            key={candidate}
            type="button"
            onClick={() => setLens(candidate)}
            title={LENS_TITLES[candidate]}
            aria-pressed={candidate === lens}
            className={cn(
              'px-1.5 py-0.5 transition-colors',
              candidate === lens
                ? 'bg-accent/10 text-accent'
                : 'text-text-muted hover:text-text-primary hover:bg-surface-overlay',
            )}
          >
            {LENS_LABELS[candidate]}
          </button>
        ))}
      </span>
      <span
        className="text-text-muted truncate max-w-[16rem]"
        title={`Zone resolved via ${RESOLUTION_LABELS[resolved.resolution] ?? resolved.resolution}`}
      >
        {describeZone(active, now)}
      </span>
    </div>
  );
}
