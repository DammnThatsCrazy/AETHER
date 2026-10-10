/**
 * KYBER zod schemas for the payment-rail operator health contract.
 *
 * Mirrors the typed, versioned backend contract in
 * `services/integrations/providers/payment_rails/kyber_contract.py`
 * (contract_version "1.0.0"). Every response from
 * `GET /v1/admin/kyber/payment-rails/health` and
 * `GET /v1/admin/kyber/payment-rails/{tenant_id}` is runtime-validated against
 * these schemas via the endpoints `wrap(...)` helper.
 *
 * `.nullable()` is load-bearing: a null count means "unknown" — a value the
 * server could not compute yet — and must never be rendered as a confident 0.
 * The `status` vocabulary is a closed enum so the console can render each state
 * (`healthy` / `degraded` / `error` / `not_configured` / `disabled` /
 * `unknown`) distinctly.
 */
import { z } from 'zod';

/** Provider/health status vocabulary — the console renders each distinctly. */
export const providerStatusSchema = z.enum([
  'healthy',
  'degraded',
  'error',
  'not_configured',
  'disabled',
  'unknown',
]);

export type ProviderStatus = z.infer<typeof providerStatusSchema>;

// ── Fleet-level ───────────────────────────────────────────────────────────────

export const providerFleetRowSchema = z
  .object({
    provider: z.string(),
    status: providerStatusSchema,
    enabled: z.boolean(),
    configured_tenants: z.number(),
    webhook_verified_24h: z.number(),
    webhook_rejected_24h: z.number(),
    signature_failures_24h: z.number(),
    sessions_observed_24h: z.number(),
    sessions_completed_24h: z.number(),
    sessions_failed_24h: z.number(),
    sessions_pending: z.number(),
    sessions_stale: z.number(),
    sessions_unresolved: z.number(),
    // null = unknown (no records to reconcile), never a misleading 0.
    reconciliation_matched_rate: z.number().nullable(),
    reconciliation_conflicts: z.number(),
    // Operational depth — null until computable.
    polling_cursor_age_seconds: z.number().nullable(),
    provider_probe_status: z.string().nullable(),
  })
  .passthrough();

export type ProviderFleetRow = z.infer<typeof providerFleetRowSchema>;

export const tenantFleetRowSchema = z
  .object({
    tenant_id: z.string(),
    status: providerStatusSchema,
    providers_configured: z.number(),
    providers_degraded: z.number(),
    sessions_observed_24h: z.number(),
    sessions_unresolved: z.number(),
    reconciliation_conflicts: z.number(),
  })
  .passthrough();

export type TenantFleetRow = z.infer<typeof tenantFleetRowSchema>;

export const fleetTotalsSchema = z
  .object({
    configured_tenants: z.number(),
    enabled_tenants: z.number(),
    providers_degraded: z.number(),
    sessions_observed_24h: z.number(),
    sessions_completed_24h: z.number(),
    sessions_failed_24h: z.number(),
    sessions_pending: z.number(),
    sessions_stale: z.number(),
    sessions_unresolved: z.number(),
    webhook_verified_24h: z.number(),
    webhook_rejected_24h: z.number(),
    signature_failures_24h: z.number(),
    reconciliation_matched_rate: z.number().nullable(),
    reconciliation_conflicts: z.number(),
    // Delivery backlogs (from the durable receipt ledger).
    oldest_incomplete_receipt_age_seconds: z.number().nullable(),
    canonical_backlog: z.number(),
    outbox_lag: z.number().nullable(),
    repair_backlog: z.number(),
    dead_lettered: z.number(),
    // Worker liveness — null when unknown (no heartbeat this process).
    worker_heartbeat: z.boolean().nullable(),
    last_successful_worker_cycle: z.string().nullable(),
  })
  .passthrough();

export type FleetTotals = z.infer<typeof fleetTotalsSchema>;

export const fleetHealthResponseSchema = z
  .object({
    contract_version: z.string(),
    tenants_observed: z.number(),
    totals: fleetTotalsSchema,
    providers: z.array(providerFleetRowSchema),
    tenants: z.array(tenantFleetRowSchema),
  })
  .passthrough();

export type FleetHealthResponse = z.infer<typeof fleetHealthResponseSchema>;

// ── Tenant-level ──────────────────────────────────────────────────────────────

export const credentialSlotStateSchema = z
  .object({
    slot_name: z.string(),
    required: z.boolean(),
    configured: z.boolean(),
    // active|previous|pending|revoked|… ; null = unknown.
    state: z.string().nullable(),
  })
  .passthrough();

export type CredentialSlotState = z.infer<typeof credentialSlotStateSchema>;

export const tenantProviderAdapterSchema = z
  .object({
    status: z.string(),
    environment: z.string().nullable(),
    webhook_configured: z.boolean(),
    polling_configured: z.boolean(),
    webhook_endpoint_registered: z.boolean(),
    credential_slots: z.array(credentialSlotStateSchema),
  })
  .passthrough();

export type TenantProviderAdapter = z.infer<typeof tenantProviderAdapterSchema>;

export const tenantProviderHealthSchema = z
  .object({
    status: providerStatusSchema,
    sessions_observed_24h: z.number(),
    sessions_completed_24h: z.number(),
    sessions_failed_24h: z.number(),
    sessions_unresolved: z.number(),
    webhook_verified_24h: z.number(),
    webhook_rejected_24h: z.number(),
    reconciliation_matched_rate: z.number().nullable(),
    reconciliation_conflicts: z.number(),
    last_event_at: z.string().nullable(),
    last_poll_at: z.string().nullable(),
    last_successful_poll_at: z.string().nullable(),
    last_failed_poll_at: z.string().nullable(),
    polling_cursor_age_seconds: z.number().nullable(),
    provider_poll_health: z.string().nullable(),
    connection_probe_result: z.string().nullable(),
  })
  .passthrough();

export type TenantProviderHealth = z.infer<typeof tenantProviderHealthSchema>;

export const tenantProviderDiagnosticsSchema = z
  .object({
    provider: z.string(),
    adapter: tenantProviderAdapterSchema,
    health: tenantProviderHealthSchema,
  })
  .passthrough();

export type TenantProviderDiagnostics = z.infer<typeof tenantProviderDiagnosticsSchema>;

export const tenantBacklogsSchema = z
  .object({
    receipt_backlog: z.number(),
    canonical_backlog: z.number(),
    outbox_backlog: z.number().nullable(),
    repair_backlog: z.number(),
    dead_lettered: z.number(),
    oldest_incomplete_receipt_age_seconds: z.number().nullable(),
  })
  .passthrough();

export type TenantBacklogs = z.infer<typeof tenantBacklogsSchema>;

export const tenantDiagnosticsResponseSchema = z
  .object({
    contract_version: z.string(),
    tenant_id: z.string(),
    providers: z.array(tenantProviderDiagnosticsSchema),
    backlogs: tenantBacklogsSchema,
    recent_audit: z.array(z.record(z.string(), z.unknown())),
    recent_repair_outcomes: z.array(z.record(z.string(), z.unknown())),
  })
  .passthrough();

export type TenantDiagnosticsResponse = z.infer<typeof tenantDiagnosticsResponseSchema>;
