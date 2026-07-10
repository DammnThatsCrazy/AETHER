/**
 * KYBER adapter — Stablecoin Intelligence ops (/v1/admin/kyber/stablecoins).
 * Observation-only domain: reads registry/finality/reconciliation state;
 * the only mutations are audited operator actions (registry seed).
 */
import { restClient } from '@kyber/lib/api';
import {
  opsListSchema, opsRowSchema, stablecoinRegistryStatusSchema,
} from '@kyber/lib/schemas/economic-ops';

export const stablecoinsOpsApi = {
  registryStatus: () =>
    restClient.get('/v1/admin/kyber/stablecoins/registry/status', stablecoinRegistryStatusSchema),

  seedRegistry: () =>
    restClient.post('/v1/admin/kyber/stablecoins/registry/seed', opsRowSchema),

  finalityCheckpoints: (limit = 50) =>
    restClient.get(`/v1/admin/kyber/stablecoins/finality/checkpoints?limit=${limit}`, opsListSchema),

  reconciliation: (limit = 50) =>
    restClient.get(`/v1/admin/kyber/stablecoins/reconciliation?limit=${limit}`, opsListSchema),

  unresolvedObservations: (limit = 50) =>
    restClient.get(`/v1/admin/kyber/stablecoins/observations/unresolved?limit=${limit}`, opsListSchema),
};
