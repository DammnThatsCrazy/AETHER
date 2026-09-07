import { useMutation, useQuery, queryCache, type CapabilityState } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@aether-app/lib/api/rest/client';

// Self-serve activation lifecycle client. Mirrors the onboarding envelope
// contract exactly (see features/onboarding/use-onboarding.ts): every response
// is wrapped in { data, status, timestamp } and the typed data payload is a
// pass-through of the backend truth — no local defaults, no synthetic records.
const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });
const unknown = z.unknown();

const STATUS_KEY = 'activation:status';
const FIRST_VALUE_KEY = 'activation:first-value';

/**
 * Backend self-serve activation state machine (services/activation/models.py).
 * Rendered honestly by the UI — a non-live state is never dressed as complete.
 */
export type ActivationState =
  | 'not_started'
  | 'account_verified'
  | 'plan_selected'
  | 'billing_pending'
  | 'billing_active'
  | 'sdk_selected'
  | 'keys_created'
  | 'waiting_for_event'
  | 'event_received'
  | 'first_value_ready'
  | 'complete'
  | 'manual_pending'
  | 'blocked'
  | 'externally_blocked';

export interface ActivationStatus {
  readonly state: ActivationState;
  readonly selected_plan_tier: string | null;
  readonly sdk_selection: readonly string[];
  readonly created_key_ids: readonly string[];
  readonly billing_state: string;
  readonly first_value_evidence: Record<string, unknown>;
  readonly waiting_reason: string | null;
  // WS-3 (intent-driven activation): the tenant's durable ActivationIntent tokens
  // + save timestamp. Additive — absent for status reads cached before WS-3.
  readonly intents?: readonly string[];
  readonly intents_updated_at?: string | null;
  readonly history: ReadonlyArray<Record<string, unknown>>;
}

/** Raw SDK API key material — returned by the backend exactly ONCE at creation. */
export interface CreatedSdkKey {
  readonly id: string;
  readonly key: string;
  readonly label: string;
}

export interface CreateSdkKeysResult {
  readonly keys: readonly CreatedSdkKey[];
  readonly state: ActivationState;
}

export interface TestEventResult {
  readonly results: ReadonlyArray<{ readonly status: string; readonly reason?: string }>;
  readonly state: ActivationState;
}

export interface FirstValueResult {
  readonly state: ActivationState;
  readonly ready: boolean;
  readonly evidence: Record<string, unknown>;
}

// Plan tiers accepted by the backend (SelectPlanRequest pattern ^(P1|P2|P3|P4)$).
export const ACTIVATION_PLAN_TIERS = ['P1', 'P2', 'P3', 'P4'] as const;
export type ActivationPlanTier = (typeof ACTIVATION_PLAN_TIERS)[number];

/**
 * Map a backend activation state onto the shared capability-state vocabulary so
 * the same honest badge palette is used everywhere. This never upgrades a state
 * to "live": only `complete` reads as live.
 */
export function activationCapabilityState(state: ActivationState): CapabilityState {
  switch (state) {
    case 'not_started':
      return 'not_configured';
    case 'account_verified':
      return 'credential_required';
    case 'plan_selected':
    case 'billing_active':
    case 'sdk_selected':
      return 'provisioning';
    case 'billing_pending':
    case 'keys_created':
    case 'waiting_for_event':
    case 'manual_pending':
      return 'credential_waiting';
    case 'event_received':
      return 'connection_testing';
    case 'first_value_ready':
      return 'sandbox_validated';
    case 'complete':
      return 'live';
    case 'externally_blocked':
      return 'externally_blocked';
    case 'blocked':
      return 'error';
    default:
      return 'unavailable';
  }
}

const ACTIVATION_STATE_LABELS: Record<ActivationState, string> = {
  not_started: 'Not started',
  account_verified: 'Account verified',
  plan_selected: 'Plan selected',
  billing_pending: 'Billing pending',
  billing_active: 'Billing active',
  sdk_selected: 'SDKs selected',
  keys_created: 'Keys created',
  waiting_for_event: 'Waiting for first event',
  event_received: 'Event received',
  first_value_ready: 'First value ready',
  complete: 'Activated',
  manual_pending: 'Manual review pending',
  blocked: 'Blocked',
  externally_blocked: 'Externally blocked',
};

export function activationStateLabel(state: ActivationState): string {
  return ACTIVATION_STATE_LABELS[state] ?? state;
}

// ── Reads ────────────────────────────────────────────────────────────────────

export function useActivationStatus() {
  return useQuery({
    key: STATUS_KEY,
    fetcher: () =>
      restClient
        .get('/v1/activation/status', wrap(unknown))
        .then(r => r.data as ActivationStatus),
    staleTime: 15_000,
  });
}

export function useFirstValue() {
  return useQuery({
    key: FIRST_VALUE_KEY,
    fetcher: () =>
      restClient
        .get('/v1/activation/first-value', wrap(unknown))
        .then(r => r.data as FirstValueResult),
    staleTime: 10_000,
  });
}

// ── Writes (each invalidates the derived reads, mirroring onboarding) ─────────

function invalidateActivation(): void {
  queryCache.invalidate(STATUS_KEY);
  queryCache.invalidate(FIRST_VALUE_KEY);
}

export function useSelectPlan() {
  return useMutation({
    mutationFn: (input: { plan_tier: ActivationPlanTier }) =>
      restClient
        .post('/v1/activation/select-plan', wrap(unknown), input)
        .then(r => r.data as ActivationStatus),
    onSuccess: invalidateActivation,
  });
}

export function useSelectSdks() {
  return useMutation({
    mutationFn: (input: { platforms: readonly string[] }) =>
      restClient
        .post('/v1/activation/sdk-selection', wrap(unknown), input)
        .then(r => r.data as ActivationStatus),
    onSuccess: invalidateActivation,
  });
}

export function useCreateSdkKeys() {
  return useMutation({
    mutationFn: (input: { count: number; label: string }) =>
      restClient
        .post('/v1/activation/create-sdk-keys', wrap(unknown), input)
        .then(r => r.data as CreateSdkKeysResult),
    onSuccess: invalidateActivation,
  });
}

export function useSendTestEvent() {
  return useMutation({
    mutationFn: (input: {
      event_type: string;
      properties?: Record<string, unknown>;
      anonymous_id?: string;
      session_id?: string;
    }) =>
      restClient
        .post('/v1/activation/test-event', wrap(unknown), input)
        .then(r => r.data as TestEventResult),
    onSuccess: invalidateActivation,
  });
}

export function useCompleteActivation() {
  return useMutation({
    mutationFn: () =>
      restClient
        .post('/v1/activation/complete', wrap(unknown), {})
        .then(r => r.data as ActivationStatus),
    onSuccess: () => {
      invalidateActivation();
      // The tenant landing derives completion from onboarding status.
      queryCache.invalidate('onboarding:status');
    },
  });
}
