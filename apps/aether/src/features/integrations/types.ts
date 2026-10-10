/**
 * Unified integration catalog wire types (R1 contract-spine FE twin).
 *
 * Transport schemas for the Settings→Integrations read model served by
 * services/integrations/connectors/catalog_endpoints.py:
 *   - /v1/integration-catalog        (derived one-customer catalog)
 *   - /v1/tenant-integrations[/{id}] (tenant's configured integrations)
 *   - /v1/integration-readiness      (catalog-level readiness matrix)
 *
 * These are *transport* types, never a parallel vocabulary: readiness tokens
 * and experience categories are single-sourced server-side
 * (readiness-vocabulary.json / shared.integration_contracts.experience) and
 * pass through here as plain strings so the FE can render without re-deriving
 * them. ``readiness`` on a tenant integration is the manifest's catalog
 * baseline and may be absent for families the catalog does not cover; the
 * joined tenant readiness graph is a later workstream.
 */
import { z } from 'zod';

// ─── Readiness (manifest catalog baseline) ───────────────────────────────────
export const catalogReadinessSchema = z.object({
  state: z.string(),
  rank: z.number(),
  level: z.number(),
});
export type CatalogReadiness = z.infer<typeof catalogReadinessSchema>;

// ─── Derived catalog entry (one connectable manifest) ────────────────────────
export const integrationCatalogEntrySchema = z.object({
  key: z.string(),
  family: z.string(),
  product: z.string(),
  capability: z.string(),
  display_name: z.string(),
  category: z.string(),
  experience_category: z.string().nullable(),
  source: z.string(),
  tenant_self_service: z.boolean(),
  environments: z.array(z.string()),
  authentication: z.string(),
  accounts_discovery: z.boolean(),
  accounts_selection_required: z.boolean(),
  webhooks_supported: z.boolean(),
  sync_incremental: z.boolean(),
  sync_initial_backfill: z.boolean(),
  readiness: catalogReadinessSchema,
  data_outputs: z.array(z.string()),
  product_destinations: z.array(z.string()),
});
export type IntegrationCatalogEntry = z.infer<
  typeof integrationCatalogEntrySchema
>;

export const integrationCatalogResponseSchema = z.object({
  tenant_id: z.string(),
  count: z.number(),
  /** Canonical experience-category order for stable UI grouping. */
  experience_categories: z.array(z.string()),
  entries: z.array(integrationCatalogEntrySchema),
});
export type IntegrationCatalogResponse = z.infer<
  typeof integrationCatalogResponseSchema
>;

// ─── Tenant integration (a configured connector + its record facts) ──────────
export const tenantIntegrationItemSchema = z.object({
  id: z.string(),
  family: z.string(),
  name: z.string().nullable(),
  display_name: z.string(),
  experience_category: z.string().nullable(),
  /** Record fact (enabled | secret configured | ever synced) — never a readiness claim. */
  connected: z.boolean(),
  enabled: z.boolean(),
  secret_configured: z.boolean(),
  sync_status: z.string(),
  last_synced_at: z.string().nullable(),
  /** Manifest catalog baseline; absent when no manifest covers this family. */
  readiness: catalogReadinessSchema.optional(),
});
export type TenantIntegrationItem = z.infer<typeof tenantIntegrationItemSchema>;

export const tenantIntegrationsResponseSchema = z.object({
  tenant_id: z.string(),
  count: z.number(),
  items: z.array(tenantIntegrationItemSchema),
});
export type TenantIntegrationsResponse = z.infer<
  typeof tenantIntegrationsResponseSchema
>;

export const tenantIntegrationResponseSchema = tenantIntegrationItemSchema;
export type TenantIntegrationResponse = TenantIntegrationItem;

// ─── Readiness matrix (catalog-level, honest reuse of the ladder) ────────────
export const integrationReadinessItemSchema = z.object({
  key: z.string(),
  family: z.string(),
  display_name: z.string(),
  experience_category: z.string().nullable(),
  readiness: catalogReadinessSchema,
});
export type IntegrationReadinessItem = z.infer<
  typeof integrationReadinessItemSchema
>;

export const integrationReadinessResponseSchema = z.object({
  tenant_id: z.string(),
  count: z.number(),
  states_present: z.array(z.string()),
  items: z.array(integrationReadinessItemSchema),
});
export type IntegrationReadinessResponse = z.infer<
  typeof integrationReadinessResponseSchema
>;


// ─── Tenant-contextual readiness (joined graph, WS-4) ───────────────────────
// Transport shapes for services/readiness_graph/tenant_integration_readiness_routes.py:
//   - /v1/tenant/integration-readiness
// One item per connectable catalog manifest (plus any tenant-configured family
// the catalog no longer exposes), joined with the tenant's connection record
// facts into an evidence-derived ``tenant_state``. ``readiness`` is ALWAYS the
// manifest catalog baseline (a healthy connection can never raise it);
// ``connection`` carries record facts (``connected`` is a fact, never a
// readiness claim); ``ready`` is only emitted when BOTH the provider
// (sandbox-validated+) and the connection (healthy) axes are proven.

export const tenantReadinessConnectionSchema = z.object({
  configured: z.boolean(),
  connected: z.boolean(),
  state: z.string().nullable(),
  enabled: z.boolean(),
  secret_configured: z.boolean(),
  sync_status: z.string(),
  last_synced_at: z.string().nullable(),
  error_count: z.number(),
  last_error_at: z.string().nullable(),
});
export type TenantReadinessConnection = z.infer<
  typeof tenantReadinessConnectionSchema
>;

export const tenantReadinessItemSchema = z.object({
  key: z.string(),
  family: z.string(),
  display_name: z.string(),
  experience_category: z.string().nullable(),
  source: z.string(),
  /** Manifest catalog baseline — provider truth; null when no manifest covers the family. */
  readiness: catalogReadinessSchema.nullable(),
  /** Evidence-derived connection/attention label; never a capability-readiness word. */
  tenant_state: z.string(),
  attention_reasons: z.array(z.string()),
  connection: tenantReadinessConnectionSchema,
});
export type TenantReadinessItem = z.infer<typeof tenantReadinessItemSchema>;

export const tenantReadinessResponseSchema = z.object({
  tenant_id: z.string(),
  count: z.number(),
  states_present: z.array(z.string()),
  items: z.array(tenantReadinessItemSchema),
});
export type TenantReadinessResponse = z.infer<
  typeof tenantReadinessResponseSchema
>;
