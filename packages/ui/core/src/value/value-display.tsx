import type { ReactNode } from 'react';
import { cn } from '../utils/cn';
import { Badge } from '../components/badge';
import {
  formatUSD,
  formatNativeValue,
  formatAetherValue,
  type AetherValueLike,
} from './format';

// =============================================================================
// USD-first value presentation. `ValueDisplay` renders the canonical
// value envelope: a prominent USD primary, a muted native drilldown, and an
// optional warning badge for stale / unpriced values. Absent USD prices render
// as "Value unavailable" — never "$0.00".
// =============================================================================

interface USDValueProps {
  readonly usd: string | number | null | undefined;
  readonly compact?: boolean | undefined;
  readonly fallback?: string | undefined;
  readonly className?: string | undefined;
}

/** A single, prominent USD figure (or the "Value unavailable" fallback). */
export function USDValue({ usd, compact, fallback, className }: USDValueProps) {
  return (
    <span className={cn('font-mono font-semibold text-text-primary', className)}>
      {formatUSD(usd, { compact, fallback })}
    </span>
  );
}

interface NativeValueBreakdownProps {
  readonly amount: string | number | null | undefined;
  readonly currency: string;
  readonly className?: string | undefined;
}

/** A muted native-denomination line, e.g. "1.84 ETH". Renders nothing when absent. */
export function NativeValueBreakdown({ amount, currency, className }: NativeValueBreakdownProps) {
  const text = formatNativeValue(amount, currency);
  if (!text) return null;
  return <span className={cn('font-mono text-[10px] text-text-muted', className)}>{text}</span>;
}

interface ValuationWarningProps {
  readonly warning: string | null | undefined;
  readonly className?: string | undefined;
}

/** A small warning badge surfacing stale / unpriced / conflicted valuations. */
export function ValuationWarning({ warning, className }: ValuationWarningProps) {
  if (!warning) return null;
  return (
    <Badge variant="warning" size="sm" className={className}>
      {warning}
    </Badge>
  );
}

interface ValueDisplayProps {
  /** Canonical (or canonical-shaped) value envelope. */
  readonly value: AetherValueLike | null | undefined;
  /** Compact USD notation (e.g. "$1.2K"). Defaults to false. */
  readonly compact?: boolean | undefined;
  /** Override the "Value unavailable" primary fallback. */
  readonly fallback?: string | undefined;
  /** Right-align the stack (useful for table cells / row-end amounts). */
  readonly align?: 'left' | 'right' | undefined;
  /** Hide the native drilldown line. */
  readonly hideNative?: boolean | undefined;
  /** Hide the valuation warning badge. */
  readonly hideWarning?: boolean | undefined;
  readonly className?: string | undefined;
  /** Optional trailing content (e.g. a freshness indicator). */
  readonly children?: ReactNode | undefined;
}

/**
 * USD-first value with native drilldown. Primary = USD (or "Value unavailable"),
 * secondary = native breakdown (muted), plus an optional warning badge.
 */
export function ValueDisplay({
  value,
  compact,
  fallback,
  align,
  hideNative,
  hideWarning,
  className,
  children,
}: ValueDisplayProps) {
  const { primary, secondary, warning } = formatAetherValue(value, { compact, fallback });

  return (
    <div className={cn('flex flex-col gap-0.5', align === 'right' && 'items-end', className)}>
      <span className="font-mono text-sm font-semibold text-text-primary">{primary}</span>
      {!hideNative && secondary && (
        <span className="font-mono text-[10px] text-text-muted">{secondary}</span>
      )}
      {!hideWarning && warning && <ValuationWarning warning={warning} />}
      {children}
    </div>
  );
}
