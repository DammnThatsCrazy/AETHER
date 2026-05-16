import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useAgentActions(agentId: string) {
  return useQuery({
    key: `onchain:agent-actions:${agentId}`,
    fetcher: () => api.onchain.agentActions(agentId),
    staleTime: STALE,
    enabled: !!agentId,
  });
}

export function useOnchainContract(address: string) {
  return useQuery({
    key: `onchain:contract:${address}`,
    fetcher: () => api.onchain.getContract(address),
    staleTime: STALE,
    enabled: !!address,
  });
}

export function useRPCHealth() {
  return useQuery({
    key: 'onchain:rpc-health',
    fetcher: () => api.onchain.rpcHealth(),
    staleTime: STALE,
  });
}

export function useRecordOnchainAction() {
  return useMutation({
    mutationFn: (action: Record<string, unknown>) => api.onchain.recordAction(action),
  });
}

export function useConfigureListener() {
  return useMutation({
    mutationFn: (config: Record<string, unknown>) => api.onchain.configureListener(config),
  });
}
