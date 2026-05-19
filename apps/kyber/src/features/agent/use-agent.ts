import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 15_000;
const STALE_SLOW = 60_000;

export function useAgentStatus() {
  return useQuery({
    key: 'agent:status',
    fetcher: () => api.agent.status(),
    staleTime: STALE,
  });
}

export function useAgentTask(taskId: string) {
  return useQuery({
    key: `agent:task:${taskId}`,
    fetcher: () => api.agent.getTask(taskId),
    staleTime: STALE,
    enabled: !!taskId,
  });
}

export function useAgentAudit(limit = 50) {
  return useQuery({
    key: `agent:audit:${limit}`,
    fetcher: () => api.agent.audit(limit),
    staleTime: STALE_SLOW,
  });
}

export function useAgentGraph(agentId: string, layer = 'all') {
  return useQuery({
    key: `agent:graph:${agentId}:${layer}`,
    fetcher: () => api.agent.agentGraph(agentId, layer),
    staleTime: STALE_SLOW,
    enabled: !!agentId,
  });
}

export function useAgentTrust(agentId: string) {
  return useQuery({
    key: `agent:trust:${agentId}`,
    fetcher: () => api.agent.agentTrust(agentId),
    staleTime: STALE_SLOW,
    enabled: !!agentId,
  });
}

export function useSubmitTask() {
  return useMutation({
    mutationFn: ({ workerType, priority, payload }: { workerType: string; priority: string; payload: Record<string, unknown> }) =>
      api.agent.submitTask(workerType, priority, payload),
  });
}

export function useKillSwitch() {
  return useMutation({
    mutationFn: (action: string) => api.agent.killSwitch(action),
  });
}
