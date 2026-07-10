/**
 * KYBER adapter — Interoperability Intelligence ops (/v1/admin/kyber/interop).
 * Observation-only domain: provider health with honest implementation
 * statuses, checkpoint lag, security-policy drift, correlation health,
 * and the audited governed-scan trigger. Aether never relays messages.
 */
import { restClient } from '@kyber/lib/api';
import {
  interopCorrelationHealthSchema, opsListSchema, opsRowSchema,
} from '@kyber/lib/schemas/economic-ops';

export const interopOpsApi = {
  providersHealth: () =>
    restClient.get('/v1/admin/kyber/interop/providers/health', opsListSchema),

  checkpoints: (limit = 100) =>
    restClient.get(`/v1/admin/kyber/interop/checkpoints?limit=${limit}`, opsListSchema),

  policyDrift: (limit = 500) =>
    restClient.get(`/v1/admin/kyber/interop/policy-drift?limit=${limit}`, opsListSchema),

  correlationHealth: () =>
    restClient.get('/v1/admin/kyber/interop/correlation/health', interopCorrelationHealthSchema),

  runScan: (providerId: string) =>
    restClient.post(`/v1/admin/kyber/interop/scan/${encodeURIComponent(providerId)}`, opsRowSchema),
};
