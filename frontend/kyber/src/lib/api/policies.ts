/**
 * KYBER adapter — Policies domain.
 * Wraps /v1/x402/policies/* endpoints.
 */
import { z } from 'zod';
import { restClient } from '@kyber/lib/api';
import { policyDecisionSchema } from '@kyber/lib/schemas/commerce';

const envelope = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, meta: z.record(z.string(), z.unknown()).optional() });

const policyRecordSchema = z.object({
  policy_id: z.string(),
  tenant_id: z.string(),
  name: z.string(),
  rule_type: z.string(),
  outcome: z.string(),
  conditions: z.record(z.string(), z.unknown()),
  active: z.boolean(),
  created_at: z.string(),
}).passthrough();

export type PolicyRecord = z.infer<typeof policyRecordSchema>;

export const policiesApi = {
  list: () =>
    restClient
      .get('/v1/x402/policies', envelope(z.array(policyRecordSchema)))
      .then((r) => r.data),

  get: (policyId: string) =>
    restClient
      .get(`/v1/x402/policies/${policyId}`, envelope(policyRecordSchema))
      .then((r) => r.data),

  create: (body: { name: string; rule_type: string; outcome: string; conditions: Record<string, unknown> }) =>
    restClient
      .post('/v1/x402/policies', envelope(policyRecordSchema), body)
      .then((r) => r.data),

  update: (policyId: string, body: Partial<{ name: string; conditions: Record<string, unknown>; active: boolean }>) =>
    restClient
      .patch(`/v1/x402/policies/${policyId}`, envelope(policyRecordSchema), body)
      .then((r) => r.data),

  simulate: (body: {
    resource_id: string;
    requester_id: string;
    amount_usd: number;
    asset_symbol: string;
    chain: string;
  }) =>
    restClient
      .post('/v1/x402/policies/simulate', envelope(policyDecisionSchema), body)
      .then((r) => r.data),

  getDecision: (decisionId: string) =>
    restClient
      .get(`/v1/x402/policies/decisions/${decisionId}`, envelope(policyDecisionSchema))
      .then((r) => r.data),
};
