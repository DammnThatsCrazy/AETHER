import { useMutation, useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE_FAST = 10_000;
const STALE_SLOW = 60_000;

export function useAgentControlPlane() {
  const health = useQuery({
    key: 'agent:control-plane:health',
    fetcher: () => api.agent.health(),
    staleTime: STALE_FAST,
  });
  const controllers = useQuery({
    key: 'agent:control-plane:controllers',
    fetcher: () => api.agent.controllersStatus(),
    staleTime: STALE_FAST,
  });
  const objectives = useQuery({
    key: 'agent:control-plane:objectives',
    fetcher: () => api.agent.objectives(undefined, 100),
    staleTime: STALE_FAST,
  });
  const reviewBatches = useQuery({
    key: 'agent:control-plane:review-batches',
    fetcher: () => api.agent.reviewBatches('pending', 100),
    staleTime: STALE_FAST,
  });
  const events = useQuery({
    key: 'agent:control-plane:events',
    fetcher: () => api.agent.events({ limit: 100 }),
    staleTime: STALE_FAST,
  });
  const audit = useQuery({
    key: 'agent:control-plane:audit',
    fetcher: () => api.agent.audit(50),
    staleTime: STALE_SLOW,
  });

  return { health, controllers, objectives, reviewBatches, events, audit };
}

export function useSubmitObjective() {
  return useMutation({
    mutationFn: ({ goal, payload, severity, priority }: { goal: string; payload?: Record<string, unknown>; severity?: string; priority?: number }) =>
      api.agent.submitObjective(goal, payload ?? {}, { ...(severity ? { severity } : {}), ...(priority !== undefined ? { priority } : {}) }),
  });
}

export function useDispatchObjective() {
  return useMutation({
    mutationFn: ({ objectiveId, controller }: { objectiveId: string; controller?: string }) =>
      api.agent.dispatch(objectiveId, controller),
  });
}

export function useObjectiveLifecycle() {
  return {
    pause: useMutation({ mutationFn: ({ objectiveId, reason }: { objectiveId: string; reason?: string }) => api.agent.pauseObjective(objectiveId, reason) }),
    resume: useMutation({ mutationFn: ({ objectiveId, reason }: { objectiveId: string; reason?: string }) => api.agent.resumeObjective(objectiveId, reason) }),
    cancel: useMutation({ mutationFn: ({ objectiveId, reason }: { objectiveId: string; reason?: string }) => api.agent.cancelObjective(objectiveId, reason) }),
  };
}

export function useReviewBatchDecision() {
  return {
    approve: useMutation({ mutationFn: ({ batchId, notes }: { batchId: string; notes?: string }) => api.agent.approveReviewBatch(batchId, notes) }),
    reject: useMutation({ mutationFn: ({ batchId, notes }: { batchId: string; notes?: string }) => api.agent.rejectReviewBatch(batchId, notes) }),
  };
}
