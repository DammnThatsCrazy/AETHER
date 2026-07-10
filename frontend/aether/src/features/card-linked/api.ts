import { z } from 'zod';
import { restClient, RestClientError } from '@aether-app/lib/api/rest/client';

const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });

const buildQS = (params: Record<string, string | number | undefined>): string => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
};

const BASE = '/v1/integrations/providers/payment-rails/card-linked';

export const cardLinkedFlowSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  card_program_id: z.string().nullish(),
  issuer_id: z.string().nullish(),
  payment_network: z.string().nullish(),
  basis: z.string(),
  rail: z.string().nullish(),
  chain: z.string().nullish(),
  asset: z.string().nullish(),
  amount_usd: z.string().nullish(),
  amount_bucket: z.string().nullish(),
  campaign_id: z.string().nullish(),
  journey_id: z.string().nullish(),
  wallet_address_hash: z.string().nullish(),
  source: z.string(),
  confidence: z.string(),
  reconciliation_state: z.string(),
  region_policy: z.string().nullish(),
  occurred_at: z.string().nullish(),
}).passthrough();

export type CardLinkedFlowRecord = z.infer<typeof cardLinkedFlowSchema>;

const flowsSchema = z.object({
  items: z.array(cardLinkedFlowSchema),
  count: z.number(),
  available_filters: z.array(z.string()).optional(),
});

const catalogSchema = z.object({
  items: z.array(z.object({
    id: z.string(),
    entity_type: z.string(),
    display_name: z.string(),
    slug: z.string(),
    aliases: z.array(z.string()),
    status: z.string(),
  }).passthrough()),
  count: z.number(),
});

const campaignOutcomesSchema = z.object({
  campaign_id: z.string(),
  card_topup_users: z.number(),
  card_spend_users: z.number(),
  card_topup_volume_usd: z.string(),
  card_spend_volume_usd: z.string(),
  card_linked_flow_count: z.number(),
  active_card_wallets: z.number(),
  programs_observed: z.array(z.string()),
  issuers_observed: z.array(z.string()),
  payment_networks_observed: z.array(z.string()),
  attribution_basis: z.string(),
  basis_breakdown: z.record(z.string(), z.number()),
  source_breakdown: z.record(z.string(), z.number()),
  confidence_breakdown: z.record(z.string(), z.number()),
}).passthrough();

export type CardLinkedCampaignOutcomes = z.infer<typeof campaignOutcomesSchema>;

export interface CardLinkedFilters {
  card_program_id?: string;
  issuer_id?: string;
  payment_network?: string;
  basis?: string;
  source?: string;
  confidence?: string;
  chain?: string;
  asset?: string;
  campaign_id?: string;
  journey_id?: string;
  volume_min?: string;
  volume_max?: string;
  since?: string;
  until?: string;
}

export function isNotEnabled(error: unknown): boolean {
  return error instanceof RestClientError && error.status === 404;
}

export const cardLinkedApi = {
  flows: async (filters: CardLinkedFilters = {}) => {
    const r = await restClient.get(`${BASE}/flows${buildQS({ ...filters })}`, wrap(flowsSchema));
    return r.data;
  },
  catalog: async (entityType?: string) => {
    const r = await restClient.get(`${BASE}/catalog${buildQS({ entity_type: entityType })}`, wrap(catalogSchema));
    return r.data;
  },
  campaignOutcomes: async (campaignId: string) => {
    const r = await restClient.get(
      `${BASE}/campaigns/${encodeURIComponent(campaignId)}/outcomes`,
      wrap(campaignOutcomesSchema),
    );
    return r.data;
  },
  profileActivity: async (entityId: string, filters: CardLinkedFilters = {}) => {
    const r = await restClient.get(
      `/v1/profile/${encodeURIComponent(entityId)}/card-linked-activity${buildQS({ ...filters })}`,
      wrap(z.object({
        entity_id: z.string(),
        summary: z.record(z.string(), z.unknown()),
        flows: z.array(cardLinkedFlowSchema),
        story: z.array(z.record(z.string(), z.unknown())),
        provenance: z.array(z.string()),
        warnings: z.array(z.string()),
      }).passthrough()),
    );
    return r.data;
  },
};
