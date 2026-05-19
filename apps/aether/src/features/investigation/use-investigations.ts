/**
 * Investigation hooks — typed wrappers for /v1/investigations/* routes.
 *
 * Covers case CRUD, status transitions, evidence and annotation management.
 */
import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 30_000;

export function useInvestigations(tenantId: string, status?: string, limit = 50) {
  return useQuery({
    key: `investigations:list:${tenantId}:${status ?? ''}:${limit}`,
    fetcher: () => api.investigations.list(tenantId, status, limit),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useInvestigation(caseId: string, tenantId: string) {
  return useQuery({
    key: `investigations:get:${caseId}:${tenantId}`,
    fetcher: () => api.investigations.get(caseId, tenantId),
    staleTime: STALE,
    enabled: !!(caseId && tenantId),
  });
}

export function useCreateInvestigation() {
  return useMutation({
    mutationFn: (input: {
      tenantId: string;
      title: string;
      subjects?: Array<{ kind: string; id: string }>;
      createdBy: string;
    }) => api.investigations.create(input),
  });
}

export function useTransitionInvestigationStatus() {
  return useMutation({
    mutationFn: (input: {
      caseId: string;
      tenantId: string;
      status: 'open' | 'triage' | 'active' | 'escalated' | 'closed';
      reason?: string;
    }) =>
      api.investigations.transitionStatus(input.caseId, {
        tenantId: input.tenantId,
        status: input.status,
        ...(input.reason !== undefined && { reason: input.reason }),
      }),
  });
}

export function useAddEvidence() {
  return useMutation({
    mutationFn: (input: {
      caseId: string;
      tenantId: string;
      evidence: Array<{ id: string; type: string; source: string }>;
    }) =>
      api.investigations.addEvidence(input.caseId, {
        tenantId: input.tenantId,
        evidence: input.evidence,
      }),
  });
}

export function useAddAnnotation() {
  return useMutation({
    mutationFn: (input: {
      caseId: string;
      tenantId: string;
      body: string;
      authorId: string;
      entityRefs?: Array<{ kind: string; id: string }>;
    }) =>
      api.investigations.addAnnotation(input.caseId, {
        tenantId: input.tenantId,
        body: input.body,
        authorId: input.authorId,
        ...(input.entityRefs !== undefined && { entityRefs: input.entityRefs }),
      }),
  });
}
