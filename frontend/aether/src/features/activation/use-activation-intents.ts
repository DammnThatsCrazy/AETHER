import { useMutation, useQuery, queryCache } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@aether-app/lib/api/rest/client';

/**
 * WS-3 intent-driven activation client (services/activation/planner.py).
 *
 * The tenant UI's "what are you trying to do?" layer. Like the SDK lifecycle
 * client, every response is the backend truth passed through the standard
 * { data, status, timestamp } envelope — no local defaults, no synthetic
 * readiness. The recommended connect plan is derived server-side from the SAME
 * tenant connector rows /v1/tenant-integrations reads, so a connect action
 * taken here shows up in the very next plan read (and in Settings).
 */
const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });
const unknown = z.unknown();

const INTENTS_CATALOG_KEY = 'activation:intents-catalog';
const PLAN_KEY = 'activation:plan';

// ── Wire types (backend ActivationIntent / experience vocabulary) ─────────────

export type ActivationConnectAction =
  | 'create_tenant_integration'
  | 'configure_credential'
  | 'enable_connection'
  | 'first_sync';

/** Connection-state vocabulary mirrors the shared ConnectionState machine. */
export type ActivationConnectionState =
  | 'available'
  | 'credential_waiting'
  | 'disabled'
  | 'initial_sync_pending'
  | 'initial_sync_running'
  | 'connected'
  | 'degraded'
  | 'sync_failed';

export interface ActivationIntentOption {
  readonly token: string;
  readonly label: string;
  readonly description: string;
  readonly recommended_categories: readonly string[];
}

export interface ActivationExperienceCategory {
  readonly token: string;
  readonly label: string;
}

export interface ActivationIntentPicker {
  readonly intents: readonly ActivationIntentOption[];
  readonly experience_categories: readonly ActivationExperienceCategory[];
}

export interface ActivationPlanIntegration {
  readonly key: string;
  readonly family: string;
  readonly product: string;
  readonly display_name: string;
  readonly experience_category: string | null;
  readonly connectable: boolean;
  readonly connect_unavailable_reason: string | null;
  readonly credential_required: boolean;
  readonly authentication: string;
  readonly accounts_discovery: boolean;
  readonly accounts_selection_required: boolean;
  readonly sync_initial_backfill: boolean;
  readonly manifest_readiness: { readonly state: string; readonly level: number };
  /** Derived from REAL tenant row facts — never a fabricated readiness word. */
  readonly connection_state: ActivationConnectionState | string;
  readonly next_action: ActivationConnectAction | null;
  readonly can_act: boolean;
  readonly record: Record<string, unknown> | null;
}

export interface ActivationPlanCategory {
  readonly experience_category: string;
  readonly display_name: string;
  readonly recommended_by_intents: readonly string[];
  readonly connected_count: number;
  readonly integration_count: number;
  readonly integrations: readonly ActivationPlanIntegration[];
}

export interface ActivationPlan {
  readonly tenant_id: string;
  readonly needs_selection: boolean;
  readonly selected_intents: readonly string[];
  /** Present only once intents are chosen (the picker labels, for context). */
  readonly intents?: ReadonlyArray<{
    readonly token: string;
    readonly label: string;
    readonly description: string;
  }>;
  readonly categories: readonly ActivationPlanCategory[];
}

export interface ActivationSaveIntentsResult {
  readonly intents: readonly string[];
  readonly intents_updated_at: string | null;
}

export interface ActivationConnectActionResult {
  readonly family: string;
  readonly action: ActivationConnectAction;
  readonly ok: boolean;
  readonly connection_state: ActivationConnectionState | string;
  readonly next_action?: ActivationConnectAction | null;
  readonly can_act?: boolean;
  /** Honest failure detail (present when ok is false). */
  readonly detail?: string;
}

// ── Reads ────────────────────────────────────────────────────────────────────

/** The intent picker: every customer goal + the experience-category order. */
export function useActivationIntentsCatalog() {
  return useQuery({
    key: INTENTS_CATALOG_KEY,
    fetcher: () =>
      restClient
        .get('/v1/activation/intents', wrap(unknown))
        .then(r => r.data as ActivationIntentPicker),
    staleTime: 60_000,
  });
}

/** Recommended connect plan for the tenant's selected intents (real state). */
export function useActivationPlan() {
  return useQuery({
    key: PLAN_KEY,
    fetcher: () =>
      restClient
        .get('/v1/activation/plan', wrap(unknown))
        .then(r => r.data as ActivationPlan),
    staleTime: 15_000,
  });
}

// ── Writes ───────────────────────────────────────────────────────────────────

/**
 * Invalidate every surface that derives from the tenant's intent selection or
 * its connector rows — the activation plan, the status read (which now carries
 * the durable intents), and the Settings twin(s) that read the same connector
 * config store (/v1/tenant-integrations + the derived catalog).
 */
function invalidatePlanDependents(): void {
  queryCache.invalidate(PLAN_KEY);
  queryCache.invalidate('activation:status');
  queryCache.invalidate('tenant-integrations:list');
  queryCache.invalidate('integration-catalog:list');
}

export function useSaveActivationIntents() {
  return useMutation({
    mutationFn: (intents: readonly string[]) =>
      restClient
        .post('/v1/activation/intents', wrap(unknown), { intents })
        .then(r => r.data as ActivationSaveIntentsResult),
    onSuccess: invalidatePlanDependents,
  });
}

/** Run ONE connect step through the shared connector_service runtime. */
export function useActivationConnectAction() {
  return useMutation({
    mutationFn: (input: {
      family: string;
      action: ActivationConnectAction;
      name?: string;
      credential?: string;
      since?: string;
    }) =>
      restClient
        .post('/v1/activation/connect-action', wrap(unknown), input)
        .then(r => r.data as ActivationConnectActionResult),
    onSuccess: invalidatePlanDependents,
  });
}
