/**
 * Event replay hooks — typed wrappers for /v1/events/replay/* routes.
 *
 * Enables Bronze-tier source_tag based replay with cursor-based progress tracking.
 */
import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 15_000;

export function useReplayJob(jobId: string, tenantId: string) {
  return useQuery({
    key: `event-replay:job:${jobId}:${tenantId}`,
    fetcher: () => api.eventReplay.getJob(jobId, tenantId),
    staleTime: STALE,
    enabled: !!(jobId && tenantId),
  });
}

export function useReplayJobs(tenantId: string, limit = 50) {
  return useQuery({
    key: `event-replay:jobs:${tenantId}:${limit}`,
    fetcher: () => api.eventReplay.listJobs(tenantId, limit),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useSubmitReplay() {
  return useMutation({
    mutationFn: (input: {
      tenantId: string;
      sourceTag: string;
      fromTime: string;
      toTime?: string;
      eventTypes?: string[];
      dryRun?: boolean;
    }) => api.eventReplay.submit(input),
  });
}

export function useCancelReplay() {
  return useMutation({
    mutationFn: (input: { jobId: string; tenantId: string }) =>
      api.eventReplay.cancel(input.jobId, input.tenantId),
  });
}
