/**
 * Delivery receipt / attempt contract (v1).
 *
 * TS twin of the Python-authoritative delivery models
 * (`services/delivery/models.py`). Preserves the honest delivery vocabulary:
 * provider-accepted ≠ delivered ≠ opened ≠ clicked. A ProviderReceipt is proof of
 * delivery only with a real `external_id` — the backend rejects an empty or
 * `sim-`-prefixed id, so a simulated receipt can never be recorded as delivered.
 *
 * Parity-tested by `tests/contracts/test_delivery_receipt_parity.py` (fields are
 * snake_case; the enum vocabularies are compared against `{e.value for e in Enum}`).
 */

/** Channels a delivery job can target. */
export const deliveryChannels = [
  'slack',
  'webhook',
  'linear',
  'jira',
  'email',
  'crm',
  'marketing',
  'ticketing',
  'agent_assist',
  'notification',
  'push',
] as const;

export type DeliveryChannel = typeof deliveryChannels[number];

/** Durable delivery-job lifecycle states. */
export const deliveryJobStates = [
  'queued',
  'leased',
  'delivered',
  'failed',
  'dead_letter',
  'cancelled',
] as const;

export type DeliveryJobState = typeof deliveryJobStates[number];

/** Per-attempt outcome (drives retry/backoff/dead-letter). */
export const deliveryAttemptOutcomes = [
  'success',
  'failure',
  'retryable',
] as const;

export type DeliveryAttemptOutcome = typeof deliveryAttemptOutcomes[number];

/** Inbound provider outcomes reconciled from callbacks — post-delivery signals. */
export const externalOutcomeTypes = [
  'delivered',
  'opened',
  'clicked',
  'replied',
  'bounced',
  'failed',
  'resolved',
] as const;

export type ExternalOutcomeType = typeof externalOutcomeTypes[number];

/** Proof of delivery from a provider — must carry a real, non-simulated external_id. */
export interface ProviderReceipt {
  id: string;
  job_id: string;
  intent_id: string;
  tenant_id: string;
  provider_adapter: string;
  external_id: string;
  channel: DeliveryChannel;
  delivered_at: string;
  raw_response: Record<string, unknown>;
  created_at: string;
}

// Named to avoid a collision with the (unrelated) interop DeliveryAttempt; this is
// the notification-delivery attempt. Parity is by field set, not by type name.
export interface NotificationDeliveryAttempt {
  id: string;
  job_id: string;
  intent_id: string;
  tenant_id: string;
  attempt_number: number;
  outcome: DeliveryAttemptOutcome;
  provider_adapter: string;
  http_status?: number | null;
  error_message?: string | null;
  external_id?: string | null;
  duration_ms?: number | null;
  raw_response?: Record<string, unknown> | null;
  created_at: string;
}
