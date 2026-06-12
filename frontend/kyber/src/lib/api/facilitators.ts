/**
 * KYBER adapter — Facilitators & Assets domain.
 * Wraps /v1/x402/facilitators/* and /v1/x402/assets/* endpoints.
 */
import { z } from 'zod';
import { restClient } from '@kyber/lib/api';
import { facilitatorSchema, stablecoinAssetSchema } from '@kyber/lib/schemas/commerce';

const envelope = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, meta: z.record(z.string(), z.unknown()).optional() });

const facilitatorHealthSchema = z.object({
  facilitator_id: z.string(),
  health_status: z.string(),
  avg_latency_ms: z.number(),
  success_rate: z.number(),
  last_checked: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
}).passthrough();

export const facilitatorsApi = {
  list: () =>
    restClient
      .get('/v1/x402/facilitators', envelope(z.array(facilitatorSchema)))
      .then((r) => r.data),

  getHealth: (facilitatorId: string) =>
    restClient
      .get(`/v1/x402/facilitators/${facilitatorId}/health`, envelope(facilitatorHealthSchema))
      .then((r) => r.data),

  register: (body: {
    name: string;
    endpoint_url: string;
    mode: string;
    supported_assets: string[];
    supported_chains: string[];
  }) =>
    restClient
      .post('/v1/x402/facilitators', envelope(facilitatorSchema), body)
      .then((r) => r.data),

  listAssets: () =>
    restClient
      .get('/v1/x402/assets', envelope(z.array(stablecoinAssetSchema)))
      .then((r) => r.data),

  registerAsset: (body: {
    symbol: string;
    chain: string;
    network: string;
    issuer: string;
    contract_address: string;
    decimals: number;
    settlement_scheme: string;
  }) =>
    restClient
      .post('/v1/x402/assets', envelope(stablecoinAssetSchema), body)
      .then((r) => r.data),

  performance: () =>
    restClient
      .get(
        '/v1/commerce/facilitators/performance',
        envelope(
          z.object({
            facilitators: z.array(
              z.object({
                facilitator_id: z.string(),
                total_volume_usd: z.number(),
                transaction_count: z.number(),
                success_rate: z.number(),
                avg_latency_ms: z.number().nullable().optional(),
              }).passthrough()
            ),
          })
        )
      )
      .then((r) => r.data),
};
