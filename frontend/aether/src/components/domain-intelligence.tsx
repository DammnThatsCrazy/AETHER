/**
 * Shared helpers for the observation-only intelligence pages
 * (stablecoins, derivatives, interoperability).
 *
 * These domains are feature-flagged off by default; the backend answers
 * 404 until a domain is enabled, which the REST client surfaces as an
 * error string. NotEnabledOrError renders that honestly as an empty
 * state instead of a scary failure.
 */
import { CapabilityStatePanel, ErrorState } from '@aether/ui';

export function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

export function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

export function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

export function isNotEnabledError(error: string | null): boolean {
  if (!error) return false;
  const low = error.toLowerCase();
  return low.includes('not enabled') || low.includes('not found') || low.includes('404');
}

export function NotEnabledOrError({
  error, domainLabel, onRetry,
}: {
  readonly error: string;
  readonly domainLabel: string;
  readonly onRetry?: () => void;
}) {
  if (isNotEnabledError(error)) {
    // Feature-flagged off is an operator-disabled capability — render the
    // canonical `disabled` state so it reads distinctly from a real error.
    return (
      <CapabilityStatePanel
        state="disabled"
        title={`${domainLabel} is not enabled`}
        description="This observation-only intelligence domain is feature-flagged off for your deployment. Contact your operator to enable it."
      />
    );
  }
  return <ErrorState message={error} {...(onRetry ? { onRetry } : {})} />;
}

export function Stat({ label, value, sub }: { readonly label: string; readonly value: React.ReactNode; readonly sub?: string }) {
  return (
    <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className="text-xl font-semibold text-text-primary mt-0.5">{value}</p>
      {sub && <p className="text-xs text-text-muted mt-0.5">{sub}</p>}
    </div>
  );
}

export function pegStatusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'on_peg') return 'success';
  if (status === 'minor_deviation' || status === 'recovering') return 'warning';
  if (status === 'depegged') return 'danger';
  return 'default';
}

export function messageStatusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'delivered' || status === 'executed' || status === 'settled' || status === 'recovered') return 'success';
  if (status.includes('failed') || status === 'timed_out' || status === 'expired' || status === 'reorged') return 'danger';
  if (status === 'cancelled' || status === 'refunded' || status === 'unknown') return 'default';
  return 'warning';
}
