/**
 * KYBER provider-connections — manifest-driven read/monitor + operator-certify.
 *
 * The Universal Provider Runtime (UPR) catalog is a typed, manifest-driven
 * contract. This module holds the ONE shape the Kyber UI is allowed to render
 * from — there is deliberately zero connector-specific code anywhere on this
 * surface. If the backend adds a provider tomorrow and the manifest ships it,
 * this page renders it; nothing here ever special-cases a connector name.
 *
 * ── Honest scope ─────────────────────────────────────────────────────────────
 *
 * Connection create / test / sync stay TENANT-scoped API calls
 * (``/v1/provider-connections/*``) and are NOT claimed by the Kyber operator
 * UI. The aggregate operator surface is read/monitor only, plus the
 * operator-certify action (``POST /v1/admin/kyber/provider-connections/certify``)
 * which runs the certification harness against an installed plugin. The admin
 * ``providers`` route shape (the contract this file codes against) is:
 *
 *     { identity, display_name, category, readiness:{level}, availability:{
 *       environments }, authentication:{type}, capabilities:[...], certification_state }
 *
 * Everything else is preserved via ``.passthrough()`` so an operator can always
 * see the raw payload bytes a digest was taken over, not a subset this file
 * happened to model.
 *
 * Sources of truth:
 *   services/provider_runtime/routes.py         — admin + tenant routers
 *   shared/integration_contracts/manifest.py    — ProviderManifest sub-models
 *   shared/integration_contracts/certification.py — CertificationReport
 */
import { useMutation, useQuery } from '@aether/ui';
import { z } from 'zod';
import { api } from '@kyber/lib/api/endpoints';

const KEY_PREFIX = 'kyber-provider-connections';
const STALE = 30_000;

// ── Contract schemas (the manifest-driven shape) ───────────────────────────

export const environmentAvailabilitySchema = z
  .object({
    local: z.boolean().default(false),
    integration: z.boolean().default(false),
    staging: z.boolean().default(false),
    production: z.boolean().default(false),
  })
  .passthrough();

export type EnvironmentAvailability = z.infer<typeof environmentAvailabilitySchema>;

export const readinessSchema = z
  .object({
    // Coarse 1-5 productization level. 0 is the backend's fallback for a
    // manifest with no readiness — rendered as unscored, never a page failure.
    level: z.number().int().min(0).max(5),
    state: z.string().nullish(),
  })
  .passthrough();

export type ManifestReadiness = z.infer<typeof readinessSchema>;

export const availabilitySchema = z
  .object({
    environments: environmentAvailabilitySchema,
    tenant_self_service: z.boolean().nullish(),
    kyber_managed: z.boolean().nullish(),
    olympus_system: z.boolean().nullish(),
  })
  .passthrough();

export type ManifestAvailability = z.infer<typeof availabilitySchema>;

export const authenticationSchema = z
  .object({
    // oauth2 | api_key | composite | webhook_only | none
    type: z.string(),
  })
  .passthrough();

export type ManifestAuthentication = z.infer<typeof authenticationSchema>;

export const providerCatalogEntrySchema = z
  .object({
    identity: z.string(),
    display_name: z.string(),
    category: z.string(),
    readiness: readinessSchema,
    availability: availabilitySchema,
    authentication: authenticationSchema,
    // Capability badges read from the plugin's honest adapter accessors:
    // auth/account/pull/webhook/report/stream/reconciliation → boolean.
    capabilities: z.record(z.boolean()),
    certification_state: z.string(),
    // Installed-source attribution ("legacy" | "plugin" | ...).
    source: z.string().nullish(),
  })
  .passthrough();

export type ProviderCatalogEntry = z.infer<typeof providerCatalogEntrySchema>;

/** An entry the backend shipped that failed per-entry validation. */
export interface ProviderCatalogIssue {
  /** Best-effort identity extraction from the malformed entry. */
  readonly identity: string;
  readonly status: 'invalid';
  /** Why the entry failed per-entry validation (zod issue list). */
  readonly reason: string;
}

export interface ProviderCatalogResult {
  /** Entries that satisfy the contract — the render set. */
  readonly providers: readonly ProviderCatalogEntry[];
  /** Entries the backend shipped but that failed per-entry validation. */
  readonly issues: readonly ProviderCatalogIssue[];
}

/**
 * The S3 envelope is ``{ providers: [...], count }`` — the ONE shape this layer
 * mirrors (identical to ``providerRuntimeCatalogEnvelopeSchema`` in endpoints.ts;
 * there is deliberately no bare-array fallback). Entry validation is per-entry
 * tolerant: one malformed plugin entry (out-of-range readiness, non-boolean
 * capability) is surfaced as an ``issues`` entry and skipped — it never takes
 * down the whole catalog and is never dropped silently.
 */
export const providerCatalogListSchema = z
  .object({
    providers: z.array(z.unknown()),
    count: z.number(),
  })
  .passthrough()
  .transform(raw => {
    const providers: ProviderCatalogEntry[] = [];
    const issues: ProviderCatalogIssue[] = [];
    for (const item of raw.providers) {
      const parsed = providerCatalogEntrySchema.safeParse(item);
      if (parsed.success) {
        providers.push(parsed.data);
      } else {
        const identity =
          typeof item === 'object' && item !== null && typeof (item as { identity?: unknown }).identity === 'string'
            ? (item as { identity: string }).identity
            : '<unknown>';
        issues.push({
          identity,
          status: 'invalid',
          reason: parsed.error.issues
            .map(issue => `${issue.path.join('.') || '<root>'}: ${issue.message}`)
            .join('; '),
        });
      }
    }
    return { providers, issues };
  });

export const runtimeHealthSchema = z
  .object({
    providers_loaded: z.number(),
    legacy_count: z.number().nullish(),
    native_count: z.number().nullish(),
    environment: z.string().nullish(),
  })
  .passthrough();

export type ProviderRuntimeHealth = z.infer<typeof runtimeHealthSchema>;

export const connectionsOverviewSchema = z
  .object({
    // identity -> lifecycle state -> count
    providers: z.record(z.record(z.number())),
    total: z.number(),
    truncated: z.boolean().nullish(),
    cap: z.number().nullish(),
  })
  .passthrough();

export type ProviderConnectionsOverview = z.infer<typeof connectionsOverviewSchema>;

export const tenantViewItemSchema = z
  .object({
    connection: z.record(z.unknown()),
    health: z.record(z.unknown()).nullable().nullish(),
    health_error: z.string().nullish(),
  })
  .passthrough();

export type ProviderTenantViewItem = z.infer<typeof tenantViewItemSchema>;

export const tenantViewSchema = z
  .object({
    tenant_id: z.string(),
    items: z.array(tenantViewItemSchema),
  })
  .passthrough();

export type ProviderTenantView = z.infer<typeof tenantViewSchema>;

export const certifyReportSchema = z
  .object({
    identity: z.string(),
    passed: z.boolean(),
    checks: z.array(
      z
        .object({ name: z.string(), passed: z.boolean(), detail: z.string().nullish() })
        .passthrough(),
    ),
    generated_at: z.string().nullish(),
    environment: z.string().nullish(),
    plugin_version: z.string().nullish(),
  })
  .passthrough();

export type ProviderCertifyReport = z.infer<typeof certifyReportSchema>;

// ── Pure selectors (render logic, kept here to be testable) ─────────────────

/** True when the manifest claims the provider is visible in ANY environment. */
export function isProviderVisible(entry: ProviderCatalogEntry): boolean {
  const envs = entry.availability?.environments;
  if (!envs) return false;
  return Boolean(envs.local || envs.integration || envs.staging || envs.production);
}

/** The environments the manifest claims, in a stable display order. */
export function providerEnvironments(entry: ProviderCatalogEntry): readonly string[] {
  const envs = entry.availability?.environments;
  if (!envs) return [];
  const order = ['production', 'staging', 'integration', 'local'] as const;
  return order.filter(env => envs[env] === true);
}

/**
 * Certification semantics: an empty / missing certification state is NOT a
 * failure state but it is also not a pass — the operator must treat the provider
 * as uncertified until a report exists. Never default the string to "passed".
 */
export function providerCertified(entry: ProviderCatalogEntry): boolean {
  const state = entry.certification_state?.trim().toLowerCase();
  if (!state) return false;
  return state === 'certified' || state === 'passed';
}

// ── Fetchers ────────────────────────────────────────────────────────────────

export function fetchProviderCatalog(): Promise<ProviderCatalogResult> {
  return api.admin.kyber.providerConnections.providers().then(raw => {
    // Boundary re-parse: the render layer only ever sees manifest data that
    // satisfies the contract above, even if the wire envelope drifted.
    return providerCatalogListSchema.parse(raw);
  });
}

export function fetchProviderRuntimeHealth(): Promise<ProviderRuntimeHealth> {
  return api.admin.kyber.providerConnections.health().then(raw => runtimeHealthSchema.parse(raw));
}

export function fetchProviderConnectionsOverview(): Promise<ProviderConnectionsOverview> {
  return api.admin.kyber.providerConnections
    .overview()
    .then(raw => connectionsOverviewSchema.parse(raw));
}

export function fetchProviderTenantView(tenantId: string): Promise<ProviderTenantView> {
  return api.admin.kyber.providerConnections
    .tenant(tenantId)
    .then(raw => tenantViewSchema.parse(raw));
}

// ── Hooks ───────────────────────────────────────────────────────────────────

export interface ProviderQueryState<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
}

/** The merged provider manifest catalog behind the operator surface. */
export function useProviderCatalog(): ProviderQueryState<ProviderCatalogResult> {
  const { data, isLoading, error, refetch } = useQuery({
    key: `${KEY_PREFIX}:catalog`,
    fetcher: fetchProviderCatalog,
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Aggregate connection counts by lifecycle state (never per-tenant). */
export function useProviderOverview(): ProviderQueryState<ProviderConnectionsOverview> {
  const { data, isLoading, error, refetch } = useQuery({
    key: `${KEY_PREFIX}:overview`,
    fetcher: fetchProviderConnectionsOverview,
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Registry summary: providers loaded, legacy vs native plugin counts. */
export function useProviderRuntimeHealth(): ProviderQueryState<ProviderRuntimeHealth> {
  const { data, isLoading, error, refetch } = useQuery({
    key: `${KEY_PREFIX}:health`,
    fetcher: fetchProviderRuntimeHealth,
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Disabled until a tenant id is named. */
export function useProviderConnections(
  tenantId: string | null,
): ProviderQueryState<ProviderTenantView> {
  const enabled = tenantId !== null && tenantId.trim() !== '';
  const { data, isLoading, error, refetch } = useQuery({
    key: `${KEY_PREFIX}:tenant:${tenantId ?? ''}`,
    fetcher: () => fetchProviderTenantView(tenantId as string),
    staleTime: STALE,
    enabled,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}


// ── Operator-certify (the only mutation on this surface) ────────────────────

export interface CertifyProviderState {
  readonly certify: (identityKey: string) => Promise<ProviderCertifyReport | null>;
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly data: ProviderCertifyReport | null;
  readonly reset: () => void;
}

/**
 * POST /v1/admin/kyber/provider-connections/certify — run the certification
 * harness against an installed provider plugin.
 *
 * Aggregate-only, operator-gated. On success the catalog and overview caches are
 * invalidated so the certification_state on the manifest refreshes.
 */
export function useCertifyProvider(): CertifyProviderState {
  const mutation = useMutation<string, ProviderCertifyReport>({
    mutationFn: async identityKey => {
      const raw = await api.admin.kyber.providerConnections.certify(identityKey);
      return certifyReportSchema.parse(raw);
    },
    invalidateKeys: [`${KEY_PREFIX}:catalog`, `${KEY_PREFIX}:overview`],
  });
  return {
    certify: mutation.mutate,
    isLoading: mutation.isLoading,
    error: mutation.error,
    data: mutation.data,
    reset: mutation.reset,
  };
}
