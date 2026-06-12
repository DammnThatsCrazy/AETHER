/**
 * KYBER adapter — Settlement domain.
 * Wraps /v1/x402/settlements/* and /v1/diagnostics/commerce/settlement-* endpoints.
 */
import { z } from 'zod';
import { restClient } from '@kyber/lib/api';
import { settlementSchema } from '@kyber/lib/schemas/commerce';

const envelope = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, meta: z.record(z.string(), z.unknown()).optional() });

const stuckSettlementSchema = z.object({
  settlement_id: z.string(),
  state: z.string(),
  created_at: z.string(),
  age_seconds: z.number(),
  resource_id: z.string().nullable().optional(),
  amount: z.number().nullable().optional(),
});

export const settlementApi = {
  get: (settlementId: string) =>
    restClient
      .get(`/v1/x402/settlements/${settlementId}`, envelope(settlementSchema))
      .then((r) => r.data),

  settle: (receiptId: string) =>
    restClient
      .post('/v1/x402/settle', envelope(settlementSchema), { receipt_id: receiptId })
      .then((r) => r.data),

  listStuck: (timeoutSeconds = 300) =>
    restClient
      .get(
        `/v1/diagnostics/commerce/settlement-timeouts?timeout_seconds=${timeoutSeconds}`,
        envelope(
          z.object({
            stuck_settlements: z.array(stuckSettlementSchema),
            count: z.number(),
            timeout_seconds: z.number(),
          })
        )
      )
      .then((r) => r.data),

  listVerificationFailures: (limit = 50) =>
    restClient
      .get(
        `/v1/diagnostics/commerce/verification-failures?limit=${limit}`,
        envelope(z.object({ failures: z.array(z.record(z.string(), z.unknown())), count: z.number() }))
      )
      .then((r) => r.data),

  reconciliationDrift: () =>
    restClient
      .get(
        '/v1/diagnostics/commerce/reconciliation-drift',
        envelope(
          z.object({
            drifted_intents: z.array(z.record(z.string(), z.unknown())),
            count: z.number(),
            total_intents_scanned: z.number(),
          })
        )
      )
      .then((r) => r.data),
};
