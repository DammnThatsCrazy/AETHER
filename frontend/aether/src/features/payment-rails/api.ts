import { z } from 'zod';
import { restClient, RestClientError } from '@aether-app/lib/api/rest/client';
import {
  paymentRailProviders,
  fundingFlowTypes,
  paymentRails,
  fundingSessionStatuses,
  reconciliationStates,
  fundingActorKinds,
} from '@aether/shared';
import type { PaymentRailProvider } from '@aether/shared';

const unknownSchema = z.unknown();
const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });

const buildQS = (params: Record<string, string | number | boolean | undefined>): string => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
};

const BASE = '/v1/integrations/providers/payment-rails';

// ── Wire schemas (snake_case per backend; mirrors @aether/shared payment-rails) ──

export const fundingSessionSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  provider: z.enum(paymentRailProviders),
  provider_detail: z.string().nullish(),
  flow_type: z.enum(fundingFlowTypes),
  rail: z.enum(paymentRails),
  status: z.enum(fundingSessionStatuses),
  provider_status: z.string().nullish(),
  status_reason: z.string().nullish(),
  reconciliation_state: z.enum(reconciliationStates),
  actor_kind: z.enum(fundingActorKinds),
  user_id: z.string().nullish(),
  agent_id: z.string().nullish(),
  org_id: z.string().nullish(),
  session_id: z.string().nullish(),
  device_id: z.string().nullish(),
  journey_id: z.string().nullish(),
  campaign_id: z.string().nullish(),
  source_asset: z.string().nullish(),
  source_chain: z.string().nullish(),
  source_amount: z.string().nullish(),
  fiat_currency: z.string().nullish(),
  destination_asset: z.string().nullish(),
  destination_chain: z.string().nullish(),
  destination_amount: z.string().nullish(),
  destination_address: z.string().nullish(),
  fee_amount: z.string().nullish(),
  fee_currency: z.string().nullish(),
  provider_session_id: z.string().nullish(),
  provider_transaction_id: z.string().nullish(),
  provider_customer_ref: z.string().nullish(),
  deposit_address_id: z.string().nullish(),
  virtual_account_id: z.string().nullish(),
  tx_hash: z.string().nullish(),
  idempotency_key: z.string(),
  occurred_at: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  metadata: z.record(z.unknown()).nullish(),
}).passthrough();

export type FundingSessionRecord = z.infer<typeof fundingSessionSchema>;

// Tolerant list shape: bare array or { sessions: [...] }.
const sessionListSchema = z.union([
  z.array(fundingSessionSchema),
  z.object({ sessions: z.array(fundingSessionSchema) }).passthrough(),
]);

export const reconciliationRecordSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  funding_session_id: z.string(),
  provider: z.enum(paymentRailProviders),
  state: z.enum(reconciliationStates),
  last_source: z.string(),
  sdk_event_id: z.string().nullish(),
  provider_event_id: z.string().nullish(),
  discrepancies: z.array(z.object({
    field: z.string(),
    sdk_value: z.string().nullish(),
    provider_value: z.string().nullish(),
  }).passthrough()).nullish(),
  first_observed_at: z.string(),
  last_checked_at: z.string(),
  resolved_at: z.string().nullish(),
  created_at: z.string(),
  updated_at: z.string(),
}).passthrough();

export type ReconciliationRecordEntry = z.infer<typeof reconciliationRecordSchema>;

// Tolerant list shape: bare array or { records: [...] } / { reconciliation: [...] }.
const reconciliationListSchema = z.union([
  z.array(reconciliationRecordSchema),
  z.object({ records: z.array(reconciliationRecordSchema) }).passthrough(),
  z.object({ reconciliation: z.array(reconciliationRecordSchema) }).passthrough(),
]);

export const paymentRailHealthSchema = z.object({
  tenant_id: z.string().nullish(),
  provider: z.enum(paymentRailProviders),
  configured: z.boolean(),
  enabled: z.boolean(),
  webhook_verified_24h: z.number(),
  webhook_rejected_24h: z.number(),
  sessions_observed_24h: z.number(),
  sessions_completed_24h: z.number(),
  sessions_failed_24h: z.number(),
  sessions_unresolved: z.number(),
  reconciliation_matched_rate: z.number().nullish(),
  reconciliation_conflicts: z.number(),
  last_event_at: z.string().nullish(),
  last_poll_at: z.string().nullish(),
  status: z.enum(['healthy', 'degraded', 'not_configured', 'error']),
  computed_at: z.string(),
}).passthrough();

export type PaymentRailHealthRecord = z.infer<typeof paymentRailHealthSchema>;

// Tolerant list shape: bare array or { providers: [...] } / { health: [...] }.
const healthListSchema = z.union([
  z.array(paymentRailHealthSchema),
  z.object({ providers: z.array(paymentRailHealthSchema) }).passthrough(),
  z.object({ health: z.array(paymentRailHealthSchema) }).passthrough(),
]);

// Adapter status/config state — secrets never appear here, only booleans.
export const providerAdapterStatusSchema = z.object({
  provider: z.enum(paymentRailProviders),
  status: z.enum(['configured', 'not_configured', 'error', 'disabled']),
  display_name: z.string().nullish(),
  provider_account_ref: z.string().nullish(),
  environment: z.string().nullish(),
  webhook_configured: z.boolean().nullish(),
  polling_configured: z.boolean().nullish(),
  last_synced_at: z.string().nullish(),
}).passthrough();

export type ProviderAdapterStatusRecord = z.infer<typeof providerAdapterStatusSchema>;

// ── Fetchers ───────────────────────────────────────────────────────────────────

export interface FundingSessionListParams {
  readonly provider?: string;
  readonly status?: string;
  readonly flow_type?: string;
  readonly rail?: string;
  readonly reconciliation_state?: string;
}

export interface FundingSessionListResult {
  readonly sessions: FundingSessionRecord[];
  /** True when the backend reports payment rail observability is not enabled (404/501). */
  readonly notConfigured: boolean;
}

export async function fetchFundingSessions(params?: FundingSessionListParams): Promise<FundingSessionListResult> {
  try {
    const r = await restClient.get(
      `${BASE}/sessions${buildQS({
        provider: params?.provider,
        status: params?.status,
        flow_type: params?.flow_type,
        rail: params?.rail,
        reconciliation_state: params?.reconciliation_state,
      })}`,
      wrap(sessionListSchema),
    );
    const sessions = Array.isArray(r.data) ? r.data : r.data.sessions;
    return { sessions, notConfigured: false };
  } catch (err) {
    if (err instanceof RestClientError && (err.status === 404 || err.status === 501)) {
      return { sessions: [], notConfigured: true };
    }
    throw err;
  }
}

export function fetchFundingSession(sessionId: string): Promise<FundingSessionRecord> {
  return restClient
    .get(`${BASE}/sessions/${encodeURIComponent(sessionId)}`, wrap(fundingSessionSchema))
    .then(r => r.data);
}

export function fetchReconciliationRecords(): Promise<ReconciliationRecordEntry[]> {
  return restClient
    .get(`${BASE}/reconciliation`, wrap(reconciliationListSchema))
    .then(r => {
      if (Array.isArray(r.data)) return r.data;
      if ('records' in r.data && Array.isArray(r.data.records)) return r.data.records;
      if ('reconciliation' in r.data && Array.isArray(r.data.reconciliation)) return r.data.reconciliation;
      return [];
    });
}

export interface PaymentRailHealthResult {
  readonly providers: PaymentRailHealthRecord[];
  /** True when the backend reports payment rail observability is not enabled (404/501). */
  readonly notConfigured: boolean;
}

export async function fetchPaymentRailHealth(): Promise<PaymentRailHealthResult> {
  try {
    const r = await restClient.get(`${BASE}/health`, wrap(healthListSchema));
    const providers = Array.isArray(r.data)
      ? r.data
      : 'providers' in r.data && Array.isArray(r.data.providers)
        ? r.data.providers
        : 'health' in r.data && Array.isArray(r.data.health)
          ? r.data.health
          : [];
    return { providers, notConfigured: false };
  } catch (err) {
    if (err instanceof RestClientError && (err.status === 404 || err.status === 501)) {
      return { providers: [], notConfigured: true };
    }
    throw err;
  }
}

export function fetchProviderStatus(provider: PaymentRailProvider | string): Promise<ProviderAdapterStatusRecord> {
  return restClient
    .get(`/v1/integrations/providers/${encodeURIComponent(provider)}/status`, wrap(providerAdapterStatusSchema))
    .then(r => r.data);
}

export function syncProviderStatus(provider: PaymentRailProvider | string): Promise<unknown> {
  return restClient
    .post(`/v1/integrations/providers/${encodeURIComponent(provider)}/sync`, wrap(unknownSchema), {})
    .then(r => r.data);
}

// ── Canonical delivery — repair backlog ──────────────────────────────────────────
// Admin action that re-drives Aether's OWN canonical payment_* emission for
// observed funding sessions whose canonical events are missing. Observe-only:
// it never executes, settles, signs, or writes provider state, is idempotent
// server-side, and carries no tenant id (auth context supplies it).

export const canonicalBacklogRepairSchema = z.object({
  scanned: z.number(),
  repaired: z.number(),
  events_reemitted: z.number(),
}).passthrough();

export type CanonicalBacklogRepairResult = z.infer<typeof canonicalBacklogRepairSchema>;

/** Discriminated outcome — honest UI mapping of the backend response/status. */
export type CanonicalBacklogRepairOutcome =
  | { readonly status: 'repaired'; readonly result: CanonicalBacklogRepairResult }
  | { readonly status: 'not_configured' }
  | { readonly status: 'forbidden' }
  | { readonly status: 'error'; readonly message: string };

export async function repairCanonicalBacklog(limit?: number): Promise<CanonicalBacklogRepairOutcome> {
  try {
    const r = await restClient.post(
      `${BASE}/canonical-backlog/repair${buildQS({ limit })}`,
      wrap(canonicalBacklogRepairSchema),
      {},
    );
    return { status: 'repaired', result: r.data };
  } catch (err) {
    if (err instanceof RestClientError) {
      if (err.status === 404 || err.status === 501) return { status: 'not_configured' };
      if (err.status === 403) return { status: 'forbidden' };
      return { status: 'error', message: err.message };
    }
    throw err;
  }
}
