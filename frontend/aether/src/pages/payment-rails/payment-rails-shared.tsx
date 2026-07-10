import { Badge } from '@aether/ui';
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

export type ProviderHealthStatus = 'healthy' | 'degraded' | 'not_configured' | 'error';

const HEALTH_STATUS_VARIANTS: Record<ProviderHealthStatus, 'success' | 'warning' | 'danger' | 'default'> = {
  healthy: 'success',
  degraded: 'warning',
  not_configured: 'default',
  error: 'danger',
};

const HEALTH_STATUS_LABELS: Record<ProviderHealthStatus, string> = {
  healthy: 'healthy',
  degraded: 'degraded',
  not_configured: 'not configured',
  error: 'error',
};

export function ProviderHealthBadge({ status }: { readonly status: ProviderHealthStatus }) {
  return <Badge variant={HEALTH_STATUS_VARIANTS[status] ?? 'default'}>{HEALTH_STATUS_LABELS[status] ?? status}</Badge>;
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

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
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
