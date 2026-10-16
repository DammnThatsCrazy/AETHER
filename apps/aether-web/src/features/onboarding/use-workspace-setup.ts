import { queryCache, useMutation, useQuery } from '@aether/ui';
import { z } from 'zod';
import { api } from '@aether-app/lib/api/endpoints';
import { restClient } from '@aether-app/lib/api/rest/client';

/**
 * Reads and writes behind the workspace onboarding flow that are not already
 * covered by the activation client (features/activation). Each is a thin pass
 * through an existing tenant endpoint — no local defaults stand in for data.
 */

const ORG_KEY = 'onboarding:organization';
const TEMPORAL_KEY = 'onboarding:temporal-defaults';
const ME_KEY = 'onboarding:me';
const KEYS_KEY = 'onboarding:api-keys';
const SUMMARY_KEY = 'onboarding:analytics-summary';

// ── Workspace (organization profile) ─────────────────────────────────────────

export function useOrganizationProfile() {
  return useQuery({ key: ORG_KEY, fetcher: () => api.organization.profile(), staleTime: 60_000 });
}

export function useUpdateOrganizationProfile() {
  return useMutation({
    mutationFn: (body: { name?: string; slug?: string }) => api.organization.updateProfile(body),
    onSuccess: () => queryCache.invalidate(ORG_KEY),
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
  return useQuery({
    key: TEMPORAL_KEY,
    fetcher: () =>
      restClient
        .get('/v1/tenants/temporal-defaults', temporalEnvelope)
        .then(r => r.data as TenantTemporalDefaults),
    staleTime: 300_000,
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
    onSuccess: () => queryCache.invalidate(TEMPORAL_KEY),
  });
}

// ── Tenant profile (plan tier chosen at signup) ──────────────────────────────

export function useTenantProfile() {
  return useQuery({ key: ME_KEY, fetcher: () => api.me.profile(), staleTime: 60_000 });
}

// ── Tenant API keys (names carry the per-SDK label) ──────────────────────────

export function useTenantApiKeys() {
  return useQuery({ key: KEYS_KEY, fetcher: () => api.settings.listKeys(), staleTime: 15_000 });
}

export function useCreateTenantApiKey() {
  return useMutation({
    mutationFn: (input: { name: string; platform: string }) =>
      api.settings.createKey({ name: input.name, platform: input.platform }),
    onSuccess: () => queryCache.invalidate(KEYS_KEY),
  });
}

export function invalidateTenantApiKeys(): void {
  queryCache.invalidate(KEYS_KEY);
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
  return useQuery({
    key: SUMMARY_KEY,
    fetcher: () => api.analytics.dashboardSummary().then(d => d as AnalyticsSummary),
    staleTime: 15_000,
    pollInterval: options?.pollInterval,
  });
}
