import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

function key(segment: string, id: string, suffix = '') {
  return `governance:${segment}:${id}${suffix ? `:${suffix}` : ''}`;
}

// ── Queries ───────────────────────────────────────────────────────────────────

export function useGovernanceDecisions(tenantId: string, params?: {
  principal_id?: string;
  allowed?: boolean;
  limit?: number;
}) {
  const suffix = `${params?.principal_id ?? ''}:${params?.allowed ?? ''}:${params?.limit ?? ''}`;
  return useQuery({
    key: key('decisions', tenantId, suffix),
    fetcher: () => api.governance.listDecisions(tenantId, params),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useGovernanceDecision(decisionId: string, tenantId: string) {
  return useQuery({
    key: key('decision', decisionId, tenantId),
    fetcher: () => api.governance.getDecision(decisionId, tenantId),
    staleTime: STALE,
    enabled: !!decisionId && !!tenantId,
  });
}

export function useGovernanceAudit(tenantId: string, params?: {
  limit?: number;
  principal_id?: string;
}) {
  const suffix = `${params?.limit ?? ''}:${params?.principal_id ?? ''}`;
  return useQuery({
    key: key('audit', tenantId, suffix),
    fetcher: () => api.governance.audit(tenantId, params),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

// ── Mutations ─────────────────────────────────────────────────────────────────

export function useEvaluateGovernance() {
  return useMutation({
    mutationFn: (body: {
      tenantId: string;
      principal: { kind: string; id: string };
      action: string;
      resource: { kind: string; id: string };
      context?: Record<string, unknown>;
      policyIds?: string[];
    }) => api.governance.evaluate(body),
  });
}
