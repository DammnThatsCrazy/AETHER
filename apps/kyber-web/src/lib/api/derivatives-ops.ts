/**
 * KYBER adapter — Derivatives Intelligence ops (/v1/admin/kyber/derivatives/runtime).
 * Observation-only domain: adapter fleet with honest implementation
 * statuses, connector checkpoints, stream gaps, reconciliation variances,
 * and the audited conformance trigger.
 */
import { restClient } from '@kyber/lib/api';
import { adapterFleetSchema, opsListSchema, opsRowSchema } from '@kyber/lib/schemas/economic-ops';

export const derivativesOpsApi = {
  fleet: () =>
    restClient.get('/v1/admin/kyber/derivatives/runtime/fleet', adapterFleetSchema),

  checkpoints: (limit = 50) =>
    restClient.get(`/v1/admin/kyber/derivatives/runtime/checkpoints?limit=${limit}`, opsListSchema),

  streamGaps: (limit = 50) =>
    restClient.get(`/v1/admin/kyber/derivatives/runtime/stream-gaps?limit=${limit}`, opsListSchema),

  variances: (limit = 50) =>
    restClient.get(`/v1/admin/kyber/derivatives/runtime/variances?limit=${limit}`, opsListSchema),

  runConformance: (adapterId: string) =>
    restClient.post(`/v1/admin/kyber/derivatives/runtime/conformance/${encodeURIComponent(adapterId)}`, opsRowSchema),
};
