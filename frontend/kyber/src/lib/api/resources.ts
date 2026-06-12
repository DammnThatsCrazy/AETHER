/**
 * KYBER adapter — Protected Resources domain.
 * Wraps /v1/x402/resources CRUD + policy endpoints.
 */
import { z } from 'zod';
import { restClient } from '@kyber/lib/api';
import { protectedResourceSchema, policyDecisionSchema, type ResourceClass } from '@kyber/lib/schemas/commerce';

const envelope = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, meta: z.record(z.string(), z.unknown()).optional() });

export const resourcesApi = {
  list: () =>
    restClient
      .get('/v1/x402/resources', envelope(z.array(protectedResourceSchema)))
      .then((r) => r.data),

  get: (resourceId: string) =>
    restClient
      .get(`/v1/x402/resources/${resourceId}`, envelope(protectedResourceSchema))
      .then((r) => r.data),

  register: (body: {
    name: string;
    resource_class: ResourceClass;
    path_pattern: string;
    owner_service: string;
    description?: string;
    price_usd: number;
    accepted_assets: string[];
    accepted_chains: string[];
    approval_required?: boolean;
    entitlement_ttl_seconds?: number;
  }) =>
    restClient
      .post('/v1/x402/resources', envelope(protectedResourceSchema), body)
      .then((r) => r.data),

  update: (resourceId: string, body: Partial<{ price_usd: number; active: boolean; approval_required: boolean; entitlement_ttl_seconds: number }>) =>
    restClient
      .patch(`/v1/x402/resources/${resourceId}`, envelope(protectedResourceSchema), body)
      .then((r) => r.data),

  getPolicy: (resourceId: string) =>
    restClient
      .get(`/v1/x402/resources/${resourceId}/policy`, envelope(policyDecisionSchema))
      .then((r) => r.data),
};
