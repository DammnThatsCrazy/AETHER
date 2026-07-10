/**
 * KYBER adapter — Derivatives Intelligence ops (/v1/admin/kyber/derivatives).
 * Observation-only domain: adapter fleet with honest implementation
 * statuses, connector checkpoints, stream gaps, reconciliation variances,
 * and the audited conformance trigger.
 */
import { restClient } from '@kyber/lib/api';
import { adapterFleetSchema, opsListSchema, opsRowSchema } from '@kyber/lib/schemas/economic-ops';

export const derivativesOpsApi = {
  fleet: () =>
    restClient.get('/v1/admin/kyber/derivatives/fleet', adapterFleetSchema),

  checkpoints: (limit = 50) =>
    restClient.get(`/v1/admin/kyber/derivatives/checkpoints?limit=${limit}`, opsListSchema),

  streamGaps: (limit = 50) =>
    restClient.get(`/v1/admin/kyber/derivatives/stream-gaps?limit=${limit}`, opsListSchema),

  variances: (limit = 50) =>
    restClient.get(`/v1/admin/kyber/derivatives/variances?limit=${limit}`, opsListSchema),

  runConformance: (adapterId: string) =>
    restClient.post(`/v1/admin/kyber/derivatives/conformance/${encodeURIComponent(adapterId)}`, opsRowSchema),
};
