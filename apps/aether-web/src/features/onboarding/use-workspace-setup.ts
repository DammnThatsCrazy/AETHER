import { queryCache, useMutation, useQuery } from '@aether/ui';
import { z } from 'zod';
import { useAuth } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';
import { restClient } from '@aether-app/lib/api/rest/client';

/**
 * Reads and writes behind the workspace onboarding flow that are not already
 * covered by the activation client (features/activation). Each is a thin pass
 * through an existing tenant endpoint — no local defaults stand in for data.
 *
 * Cache keys carry the authenticated principal, like the tenant readiness
 * queries: a sign-out and sign-in as another tenant in the same SPA must never
 * be served the previous tenant's organization, keys, sites or totals.
 */

const ORG = 'onboarding:organization';
const TEMPORAL = 'onboarding:temporal-defaults';
const ME = 'onboarding:me';
const KEYS = 'onboarding:api-keys';
const SITES = 'onboarding:sdk-sites';
const SUMMARY = 'onboarding:analytics-summary';

function useScope(): { readonly scope: string; readonly enabled: boolean } {
  const { user } = useAuth();
  const id = user?.id ?? null;
  return { scope: id ? encodeURIComponent(id) : 'anonymous', enabled: Boolean(id) };
}

const scoped = (prefix: string, scope: string) => `${prefix}:${scope}`;

const wrap = <T extends z.ZodType>(data: T) => z.object({ data, status: z.string(), timestamp: z.string() }).passthrough();

// ── Workspace (organization profile) ─────────────────────────────────────────

export function useOrganizationProfile() {
  const { scope, enabled } = useScope();
  return useQuery({ key: scoped(ORG, scope), fetcher: () => api.organization.profile(), staleTime: 60_000, enabled });
}

export function useUpdateOrganizationProfile() {
  return useMutation({
    mutationFn: (body: { name?: string; slug?: string }) => api.organization.updateProfile(body),
    onSuccess: () => queryCache.invalidatePrefix(ORG),
  });
}

// ── Tenant temporal defaults (/v1/tenants/temporal-defaults) ─────────────────
// Behind the temporal_integrity feature flag server-side: a 404 means the
// feature is off for this deployment and the timezone is simply not stored.

const temporalEnvelope = z.object({ data: z.record(z.unknown()) }).passthrough();

export interface TenantTemporalDefaults {
  readonly business_time_zone?: string | null;
  readonly default_display_time_zone?: string | null;
}

export function useTenantTemporalDefaults() {
  const { scope, enabled } = useScope();
  return useQuery({
    key: scoped(TEMPORAL, scope),
    fetcher: () =>
      restClient
        .get('/v1/tenants/temporal-defaults', temporalEnvelope)
        .then(r => r.data as TenantTemporalDefaults),
    staleTime: 300_000,
    enabled,
  });
}

export function useSaveTenantTimezone() {
  return useMutation({
    mutationFn: (input: { timezone: string; current: TenantTemporalDefaults | null }) =>
      restClient
        .put('/v1/tenants/temporal-defaults', temporalEnvelope, {
          ...(input.current ?? {}),
          business_time_zone: input.timezone,
          default_display_time_zone: input.timezone,
        })
        .then(r => r.data as TenantTemporalDefaults),
    onSuccess: () => queryCache.invalidatePrefix(TEMPORAL),
  });
}

// ── Tenant profile (plan tier chosen at signup) ──────────────────────────────

export function useTenantProfile() {
  const { scope, enabled } = useScope();
  return useQuery({ key: scoped(ME, scope), fetcher: () => api.me.profile(), staleTime: 60_000, enabled });
}

// ── Tenant API keys (names carry the per-SDK label) ──────────────────────────

export interface TenantApiKey {
  readonly id: string;
  readonly name: string;
  readonly platform: string | null;
}

const KEY_PAGE = 100;
const keyPageSchema = wrap(
  z.object({
    api_keys: z.array(z.object({ id: z.string(), name: z.string(), platform: z.string().nullish() }).passthrough()),
    total: z.number(),
  }),
);

/**
 * Every key on the tenant, across pages. Absence from a single page is not
 * proof an SDK has no key, so onboarding reads them all before offering to
 * mint one. Records minted by the activation flow carry no `platform` field,
 * which this read tolerates.
 */
export async function fetchAllTenantApiKeys(): Promise<{ readonly api_keys: readonly TenantApiKey[] }> {
  const out: TenantApiKey[] = [];
  for (let offset = 0, guard = 0; guard < 50; guard++, offset += KEY_PAGE) {
    const page = await restClient.get(`/v1/me/api-keys?limit=${KEY_PAGE}&offset=${offset}`, keyPageSchema);
    out.push(...page.data.api_keys.map(k => ({ id: k.id, name: k.name, platform: k.platform ?? null })));
    if (page.data.api_keys.length < KEY_PAGE || out.length >= page.data.total) break;
  }
  return { api_keys: out };
}

export function useTenantApiKeys() {
  const { scope, enabled } = useScope();
  return useQuery({ key: scoped(KEYS, scope), fetcher: fetchAllTenantApiKeys, staleTime: 15_000, enabled });
}

/** The authority an SDK key needs to send events (mirrors the activation mint). */
export const SDK_KEY_PERMISSIONS = ['read', 'write', 'ingest', 'analytics'] as const;

export function useCreateTenantApiKey() {
  return useMutation({
    mutationFn: (input: { name: string; platform: string }) =>
      api.settings.createKey({ name: input.name, platform: input.platform, permissions: [...SDK_KEY_PERMISSIONS] }),
    onSuccess: () => queryCache.invalidatePrefix(KEYS),
  });
}

export function invalidateTenantApiKeys(): void {
  queryCache.invalidatePrefix(KEYS);
}

// ── Web install sites + publishable keys (/v1/sdk/sites) ────────────────────
// Browser code is public, so a browser SDK gets a `pk_` publishable key bound
// to a registered site (its origins), never a secret `ak_` key.

const siteSchema = z.object({ id: z.string(), name: z.string(), status: z.string().optional(), origins: z.array(z.string()).optional() }).passthrough();

export type SdkSite = z.infer<typeof siteSchema>;

export function useSdkSites() {
  const { scope, enabled } = useScope();
  return useQuery({
    key: scoped(SITES, scope),
    fetcher: () => restClient.get('/v1/sdk/sites?limit=200', wrap(z.object({ sites: z.array(siteSchema) }))).then(r => r.data.sites),
    staleTime: 15_000,
    enabled,
  });
}

export async function createSdkSite(input: { name: string; origins: readonly string[] }): Promise<SdkSite> {
  const res = await restClient.post('/v1/sdk/sites', wrap(z.object({ site: siteSchema })), {
    name: input.name,
    origins: input.origins,
    environment: 'production',
  });
  queryCache.invalidatePrefix(SITES);
  return res.data.site;
}

export interface PublishableKey {
  readonly id: string;
  readonly key: string;
  readonly siteId: string;
  readonly snippet: string;
}

export async function createSitePublishableKey(siteId: string, name: string): Promise<PublishableKey> {
  const res = await restClient.post(
    `/v1/sdk/sites/${encodeURIComponent(siteId)}/keys`,
    wrap(z.object({ api_key: z.string(), id: z.string(), site_id: z.string(), snippet: z.string() }).passthrough()),
    { name },
  );
  queryCache.invalidatePrefix(KEYS);
  return { id: res.data.id, key: res.data.api_key, siteId: res.data.site_id, snippet: res.data.snippet };
}

/** Per-site install liveness (the loader's own milestone events). */
export function useSiteLive(siteId: string | null) {
  const { scope, enabled } = useScope();
  return useQuery({
    key: `onboarding:site-live:${scope}:${siteId ?? 'none'}`,
    fetcher: () =>
      restClient
        .get(`/v1/sdk/sites/${encodeURIComponent(siteId ?? '')}/live`, wrap(z.object({ live: z.boolean(), state: z.string() }).passthrough()))
        .then(r => r.data),
    staleTime: 5_000,
    pollInterval: 10_000,
    enabled: enabled && Boolean(siteId),
  });
}

// ── Last-24h ingestion summary (/v1/analytics/dashboard/summary) ─────────────

export interface AnalyticsSummary {
  readonly period?: string;
  readonly total_events?: number;
  readonly total_sessions?: number;
  readonly unique_users?: number;
  readonly top_event_types?: ReadonlyArray<Record<string, unknown>>;
}

export function useAnalyticsSummary(options?: { readonly pollInterval?: number }) {
  const { scope, enabled } = useScope();
  return useQuery({
    key: scoped(SUMMARY, scope),
    fetcher: () => api.analytics.dashboardSummary().then(d => d as AnalyticsSummary),
    staleTime: 15_000,
    pollInterval: options?.pollInterval,
    enabled,
  });
}
