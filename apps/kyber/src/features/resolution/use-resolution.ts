import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 30_000;
const STALE_SLOW = 120_000;

export function useResolutionCluster(userId: string) {
  return useQuery({
    key: `resolution:cluster:${userId}`,
    fetcher: () => api.resolution.cluster(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useResolutionPending(limit = 50) {
  return useQuery({
    key: `resolution:pending:${limit}`,
    fetcher: () => api.resolution.pending(limit),
    staleTime: STALE,
  });
}

export function useResolutionAudit(decisionId: string) {
  return useQuery({
    key: `resolution:audit:${decisionId}`,
    fetcher: () => api.resolution.audit(decisionId),
    staleTime: STALE_SLOW,
    enabled: !!decisionId,
  });
}

export function useResolutionConfig() {
  return useQuery({
    key: 'resolution:config',
    fetcher: () => api.resolution.getConfig(),
    staleTime: STALE_SLOW,
  });
}

export function useApproveResolution() {
  return useMutation({
    mutationFn: (decisionId: string) => api.resolution.approve(decisionId),
  });
}

export function useRejectResolution() {
  return useMutation({
    mutationFn: (decisionId: string) => api.resolution.reject(decisionId),
  });
}

export function useUpdateResolutionConfig() {
  return useMutation({
    mutationFn: (config: Record<string, unknown>) => api.resolution.updateConfig(config),
  });
}

export function useRunResolutionBatch() {
  return useMutation({
    mutationFn: () => api.resolution.runBatch(),
  });
}
