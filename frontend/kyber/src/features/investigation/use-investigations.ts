import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

function key(segment: string, id: string, suffix = '') {
  return `investigation:${segment}:${id}${suffix ? `:${suffix}` : ''}`;
}

// ── Queries ───────────────────────────────────────────────────────────────────

export function useInvestigations(tenantId: string, params?: { status?: string; limit?: number }) {
  const suffix = `${params?.status ?? ''}:${params?.limit ?? ''}`;
  return useQuery({
    key: key('list', tenantId, suffix),
    fetcher: () => api.investigations.list(tenantId, params),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useInvestigation(caseId: string, tenantId: string) {
  return useQuery({
    key: key('get', caseId, tenantId),
    fetcher: () => api.investigations.get(caseId, tenantId),
    staleTime: STALE,
    enabled: !!caseId && !!tenantId,
  });
}

// ── Mutations ─────────────────────────────────────────────────────────────────

export function useCreateInvestigation() {
  return useMutation({
    mutationFn: (body: {
      tenantId: string;
      title: string;
      subjects?: Array<{ kind: string; id: string }>;
      createdBy: string;
    }) => api.investigations.create(body),
  });
}

export function useTransitionInvestigationStatus() {
  return useMutation({
    mutationFn: ({ caseId, body }: {
      caseId: string;
      body: {
        tenantId: string;
        status: 'open' | 'triage' | 'active' | 'escalated' | 'closed';
        reason?: string;
      };
    }) => api.investigations.transitionStatus(caseId, body),
  });
}

export function useAddInvestigationEvidence() {
  return useMutation({
    mutationFn: ({ caseId, body }: {
      caseId: string;
      body: {
        tenantId: string;
        evidence: Array<{ id: string; type: string; source: string }>;
      };
    }) => api.investigations.addEvidence(caseId, body),
  });
}

export function useAddInvestigationAnnotation() {
  return useMutation({
    mutationFn: ({ caseId, body }: {
      caseId: string;
      body: {
        tenantId: string;
        body: string;
        authorId: string;
        entityRefs?: Array<{ kind: string; id: string }>;
      };
    }) => api.investigations.addAnnotation(caseId, body),
  });
}
