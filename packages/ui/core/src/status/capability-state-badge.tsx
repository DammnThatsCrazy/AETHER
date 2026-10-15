import type { ReactNode } from 'react';
import { cn } from '../utils/cn';
import { Badge } from '../components/badge';
import { Button } from '../components/button';
import {
  capabilityStateStyle,
  type CapabilityState,
} from './capability-state';

/**
 * Compact, honest capability-state pill. Each of the 15 matrix states renders a
 * distinct label + glyph + badge variant, and always carries a machine-readable
 * `data-capability-state` marker so a not-live capability can never be mistaken
 * for a live one (and so tests can assert distinctness).
 */
export interface CapabilityStateBadgeProps {
  readonly state: CapabilityState;
  /** Override the default human label (e.g. to include the provider name). */
  readonly label?: string | undefined;
  /** Extra non-secret detail surfaced as a tooltip; defaults to the state description. */
  readonly reason?: string | null | undefined;
  /** Hide the leading glyph (label-only). */
  readonly hideGlyph?: boolean | undefined;
  readonly size?: 'sm' | 'md' | undefined;
  readonly className?: string | undefined;
}

export function CapabilityStateBadge({
  state,
  label,
  reason,
  hideGlyph,
  size = 'sm',
  className,
}: CapabilityStateBadgeProps) {
  const s = capabilityStateStyle(state);
  return (
    <span
      data-capability-state={state}
      data-capability-tone={s.tone}
      title={reason ?? s.description}
    >
      <Badge variant={s.variant} size={size} className={cn('gap-1', className)}>
        {!hideGlyph && <span aria-hidden className="font-mono leading-none">{s.glyph}</span>}
        <span>{label ?? s.label}</span>
      </Badge>
    </span>
  );
}

/**
 * Full-surface treatment for when an ENTIRE capability surface is in a non-live
 * state (disabled, not entitled, not configured, awaiting credentials, kill
 * switch, …). Distinguishes these honestly instead of collapsing them all into a
 * generic "not enabled" empty state — mirrors EmptyState/ErrorState styling.
 */
export interface CapabilityStatePanelProps {
  readonly state: CapabilityState;
  readonly title?: string | undefined;
  /** Override the default explanation. */
  readonly description?: ReactNode;
  /** Primary action (e.g. "Add credentials", "Retry"). */
  readonly action?: ReactNode;
  readonly onRetry?: (() => void) | undefined;
  readonly retryLabel?: string | undefined;
  readonly className?: string | undefined;
}

const TONE_ACCENT: Record<string, string> = {
  neutral: 'text-text-muted',
  action: 'text-warning',
  progress: 'text-info',
  validating: 'text-accent',
  live: 'text-success',
  caution: 'text-warning',
  critical: 'text-danger',
};

export function CapabilityStatePanel({
  state,
  title,
  description,
  action,
  onRetry,
  retryLabel = 'Retry',
  className,
}: CapabilityStatePanelProps) {
  const s = capabilityStateStyle(state);
  const accent = TONE_ACCENT[s.tone] ?? 'text-text-muted';
  return (
    <div
      data-capability-state={state}
      data-capability-tone={s.tone}
      className={cn('flex flex-col items-center justify-center py-12 text-center', className)}
    >
      <div className={cn('text-3xl mb-3 font-mono', accent)} aria-hidden>
        {s.glyph}
      </div>
      <div className={cn('text-sm font-medium', accent)}>{title ?? s.label}</div>
      <div className="text-xs text-text-secondary mt-1 max-w-md">
        {description ?? s.description}
      </div>
      {(action || onRetry) && (
        <div className="mt-4 flex items-center gap-2">
          {action}
          {onRetry && (
            <Button variant="secondary" size="sm" onClick={onRetry}>
              {retryLabel}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
