/**
 * Governance hooks — typed wrappers for /v1/governance/* routes.
 *
 * Covers policy decision evaluation, decision history, and audit trail.
 */
import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export function useGovernanceDecisions(
  tenantId: string,
  params?: { principal_id?: string; allowed?: boolean; limit?: number }
) {
  return useQuery({
    key: `governance:decisions:${tenantId}:${params?.principal_id ?? ''}:${params?.allowed ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.governance.listDecisions(tenantId, params),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useGovernanceDecision(decisionId: string, tenantId: string) {
  return useQuery({
    key: `governance:decision:${decisionId}:${tenantId}`,
    fetcher: () => api.governance.getDecision(decisionId, tenantId),
    staleTime: STALE,
    enabled: !!(decisionId && tenantId),
  });
}

export function useGovernanceAudit(tenantId: string, limit = 100, principal_id?: string) {
  return useQuery({
    key: `governance:audit:${tenantId}:${limit}:${principal_id ?? ''}`,
    fetcher: () => api.governance.audit(tenantId, limit, principal_id),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useEvaluatePolicy() {
  return useMutation({
    mutationFn: (input: {
      tenantId: string;
      principal: { kind: string; id: string };
      action: string;
      resource: { kind: string; id: string };
      context?: Record<string, unknown>;
      policyIds?: string[];
    }) => api.governance.evaluate(input),
  });
}
