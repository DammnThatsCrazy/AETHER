import { useQuery, useMutation } from '@aether/ui';
import { restClient } from '@aether-app/lib/api/rest/client';
import { z } from 'zod';

const STALE = 30_000;
const OVERVIEW_KEY = 'campaign-sources:overview';
const OPTIONS_KEY = 'campaign-sources:ad-options';

// ── Additive wire schemas (WS-2 advertising connect flow) ───────────────
// Backend responses are the campaign API's snake_case surface, returned inside
// the {data,status,timestamp} envelope; these schemas describe the *unwrapped*
// data payload. They are tolerant (passthrough) because the campaign service
// keeps growing additively.

function wrap<T extends z.ZodType>(schema: T) {
  return z.object({ data: schema, status: z.string(), timestamp: z.string() }).passthrough();
}

export const campaignSourceSchema = z.object({
  connector_id: z.string().nullish(),
  platform: z.string().nullish(),
  connector_type: z.string().nullish(),
  name: z.string().nullish(),
  status: z.string().nullish(),
  enabled: z.boolean().nullish(),
  is_ad_platform: z.boolean().nullish(),
  account_field: z.string().nullish(),
  account_id: z.string().nullish(),
  secret_configured: z.boolean().nullish(),
  missing_secrets: z.array(z.string()).nullish(),
  secrets_total: z.number().nullish(),
  health_status: z.string().nullish(),
  health_message: z.string().nullish(),
  last_sync_at: z.string().nullish(),
  last_success_at: z.string().nullish(),
  next_sync_at: z.string().nullish(),
  sync_run_count: z.number().nullish(),
  error_count: z.number().nullish(),
  created_at: z.string().nullish(),
  updated_at: z.string().nullish(),
}).passthrough();

export type CampaignSourceRecord = z.infer<typeof campaignSourceSchema>;

const sourcesOverviewSchema = z.object({
  items: z.array(campaignSourceSchema),
  counts: z.object({
    total: z.number().nullish(),
    active: z.number().nullish(),
    disabled: z.number().nullish(),
    ad_families: z.number().nullish(),
  }).passthrough().nullish(),
  ad_families: z.array(z.string()).nullish(),
  source_status: z.string().nullish(),
}).passthrough();

export type CampaignSourcesOverview = z.infer<typeof sourcesOverviewSchema>;

const credentialFieldSchema = z.object({
  name: z.string(),
  type: z.string().nullish(),
  secret: z.boolean().nullish(),
  required: z.boolean().nullish(),
}).passthrough();

const adOptionSchema = z.object({
  family: z.string(),
  display_name: z.string().nullish(),
  account_field: z.string().nullish(),
  account_discovery: z.boolean().nullish(),
  already_connected: z.boolean().nullish(),
  credential_fields: z.array(credentialFieldSchema).nullish(),
}).passthrough();

export type CampaignSourceAdOption = z.infer<typeof adOptionSchema>;

const adOptionsSchema = z.object({
  items: z.array(adOptionSchema),
  source_status: z.string().nullish(),
}).passthrough();

const connectResultSchema = z.object({
  already_connected: z.boolean().nullish(),
  platform: z.string().nullish(),
  source: campaignSourceSchema.nullish(),
  message: z.string().nullish(),
}).passthrough();

const testResultSchema = z.object({
  family: z.string().nullish(),
  account_field: z.string().nullish(),
  account_value: z.string().nullish(),
  valid: z.boolean().nullish(),
  status_message: z.string().nullish(),
}).passthrough();

const accountResultSchema = z.object({
  connector_id: z.string().nullish(),
  platform: z.string().nullish(),
  account_id: z.string().nullish(),
  account_rotated: z.boolean().nullish(),
  unchanged: z.boolean().nullish(),
  status: z.string().nullish(),
  superseded_connector_id: z.string().nullish(),
  source: campaignSourceSchema.nullish(),
}).passthrough();

const actionResultSchema = z.object({
  connector_id: z.string().nullish(),
  platform: z.string().nullish(),
  status: z.string().nullish(),
  enabled: z.boolean().nullish(),
  unchanged: z.boolean().nullish(),
}).passthrough();

// ── Reads ────────────────────────────────────────────────────────────────

/** Redacted overview of connected campaign sources (never carries secrets). */
export function useCampaignSources() {
  return useQuery({
    key: OVERVIEW_KEY,
    fetcher: async () => {
      const res = await restClient.get('/v1/campaign-sources/overview', wrap(sourcesOverviewSchema));
      return res.data;
    },
    staleTime: STALE,
  });
}

/** Ad platforms the tenant can connect, with credential shape + connect state. */
export function useCampaignSourceAdOptions() {
  return useQuery({
    key: OPTIONS_KEY,
    fetcher: async () => {
      const res = await restClient.get('/v1/campaign-sources/ad-options', wrap(adOptionsSchema));
      return res.data;
    },
    staleTime: STALE,
  });
}

export function useCampaignSourceHealth(connectorId: string) {
  return useQuery({
    key: `campaign-source:${connectorId}:health`,
    fetcher: () => restClient
      .get(`/v1/campaign-sources/${connectorId}/health`, wrap(campaignSourceSchema))
      .then(r => r.data),
    staleTime: 15_000,
    enabled: !!connectorId,
  });
}

// ── Mutations ───────────────────────────────────────────────────────────

export interface ConnectCampaignSourceInput {
  platform: string;
  name?: string | undefined;
  config: Record<string, string>;
}

export function useSyncCampaignSource() {
  return useMutation({
    mutationFn: (connectorId: string) => restClient
      .post(`/v1/campaign-sources/${connectorId}/sync`, wrap(actionResultSchema), {})
      .then(r => r.data),
    invalidateKeys: [OVERVIEW_KEY, 'campaign-sources:list'],
  });
}

export function useConnectCampaignSource() {
  return useMutation({
    mutationFn: (input: ConnectCampaignSourceInput) => restClient
      .post('/v1/campaign-sources/connect', wrap(connectResultSchema), input)
      .then(r => r.data),
    invalidateKeys: [OVERVIEW_KEY, OPTIONS_KEY, 'campaign-sources:list'],
  });
}

export function useTestCampaignSource() {
  return useMutation({
    mutationFn: (connectorId: string) => restClient
      .post(`/v1/campaign-sources/${connectorId}/test`, wrap(testResultSchema), {})
      .then(r => r.data),
    invalidateKeys: [],
  });
}

export function useSetCampaignSourceAccount() {
  return useMutation({
    mutationFn: (input: { connectorId: string; accountId: string }) => restClient
      .post(`/v1/campaign-sources/${input.connectorId}/account`, wrap(accountResultSchema), {
        account_id: input.accountId,
      })
      .then(r => r.data),
    invalidateKeys: [OVERVIEW_KEY, OPTIONS_KEY],
  });
}

export function useDisableCampaignSource() {
  return useMutation({
    mutationFn: (connectorId: string) => restClient
      .post(`/v1/campaign-sources/${connectorId}/disable`, wrap(actionResultSchema), {})
      .then(r => r.data),
    invalidateKeys: [OVERVIEW_KEY, OPTIONS_KEY],
  });
}

export function useEnableCampaignSource() {
  return useMutation({
    mutationFn: (connectorId: string) => restClient
      .post(`/v1/campaign-sources/${connectorId}/enable`, wrap(actionResultSchema), {})
      .then(r => r.data),
    invalidateKeys: [OVERVIEW_KEY, OPTIONS_KEY],
  });
}
