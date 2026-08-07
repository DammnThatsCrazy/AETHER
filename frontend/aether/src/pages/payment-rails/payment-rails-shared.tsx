import { Badge, CapabilityStateBadge, formatInstant, resolveCapabilityState, type TimeContext } from '@aether/ui';
import type {
  FundingFlowType,
  FundingSessionStatus,
  PaymentRailProvider,
  ReconciliationState,
} from '@aether/shared';

export const OBSERVABILITY_COPY =
  'Aether observes payment rails — it does not execute or settle payments, or custody funds.';

const PROVIDER_LABELS: Record<PaymentRailProvider, string> = {
  privy: 'Privy',
  stripe: 'Stripe',
  coinbase: 'Coinbase',
  moonpay: 'MoonPay',
  bridge: 'Bridge',
};

export function providerLabel(provider: PaymentRailProvider): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

export function ProviderBadge({ provider }: { readonly provider: PaymentRailProvider }) {
  return <Badge variant="info">{providerLabel(provider)}</Badge>;
}

const SESSION_STATUS_VARIANTS: Record<FundingSessionStatus, 'success' | 'warning' | 'danger' | 'info' | 'default'> = {
  initiated: 'default',
  submitted: 'info',
  pending: 'info',
  completed: 'success',
  failed: 'danger',
  refunded: 'warning',
  cancelled: 'default',
  unresolved: 'warning',
};

export function SessionStatusBadge({ status }: { readonly status: FundingSessionStatus }) {
  return <Badge variant={SESSION_STATUS_VARIANTS[status] ?? 'default'}>{status}</Badge>;
}

const RECONCILIATION_VARIANTS: Record<ReconciliationState, 'success' | 'warning' | 'danger' | 'default'> = {
  sdk_only: 'warning',
  provider_only: 'warning',
  matched: 'success',
  stale: 'default',
  conflict: 'danger',
  ignored_duplicate: 'default',
};

export function ReconciliationStateBadge({ state }: { readonly state: ReconciliationState }) {
  return <Badge variant={RECONCILIATION_VARIANTS[state] ?? 'default'}>{state}</Badge>;
}

export type ProviderHealthStatus =
  | 'healthy'
  | 'degraded'
  | 'not_configured'
  | 'error'
  | 'disabled'
  | 'unknown';

const HEALTH_STATUS_LABELS: Record<ProviderHealthStatus, string> = {
  healthy: 'healthy',
  degraded: 'degraded',
  not_configured: 'not configured',
  error: 'error',
  disabled: 'disabled',
  unknown: 'unknown',
};

/**
 * Provider integration health is a capability credential-lifecycle signal, so it
 * renders on the canonical matrix (healthy → partner_live, not_configured, …).
 * The raw server status stays as the label so operators still see the exact term.
 */
export function ProviderHealthBadge({ status }: { readonly status: ProviderHealthStatus }) {
  const state = resolveCapabilityState(status) ?? 'not_configured';
  return <CapabilityStateBadge state={state} label={HEALTH_STATUS_LABELS[status] ?? status} reason={`provider health: ${status}`} />;
}

const FLOW_TYPE_LABELS: Record<FundingFlowType, string> = {
  fiat_onramp: 'Fiat onramp',
  crypto_onramp: 'Crypto onramp',
  bank_deposit: 'Bank deposit',
  crypto_deposit: 'Crypto deposit',
  offramp: 'Offramp',
  settlement: 'Settlement',
  refund: 'Refund',
};

export function flowTypeLabel(flowType: FundingFlowType): string {
  return FLOW_TYPE_LABELS[flowType] ?? flowType;
}

export function formatDateTime(iso: string | null | undefined, timeCtx: TimeContext): string {
  if (!iso) return '—';
  try {
    return formatInstant(iso, timeCtx);
  } catch {
    return iso;
  }
}

/**
 * Native amount display only — amounts stay in their own currency/asset and
 * are never converted, summed, or otherwise combined across units.
 */
export function formatNativeAmount(amount: string | null | undefined, unit: string | null | undefined): string {
  if (!amount) return '—';
  return unit ? `${amount} ${unit}` : amount;
}

export function formatMatchedRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return '—';
  return `${(rate * 100).toFixed(1)}%`;
}

/**
 * Humanize an age in seconds ("42s", "5m 03s", "2h 14m", "3d 4h"). A null/
 * undefined age means the server could not compute it yet and renders as "—" —
 * never as a confident 0. A real 0 renders as "0s" so operators can tell the
 * two apart.
 */
export function humanizeSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${String(s).padStart(2, '0')}s`;
  }
  if (seconds < 86_400) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h}h ${String(m).padStart(2, '0')}m`;
  }
  const d = Math.floor(seconds / 86_400);
  const h = Math.floor((seconds % 86_400) / 3600);
  return `${d}d ${h}h`;
}
