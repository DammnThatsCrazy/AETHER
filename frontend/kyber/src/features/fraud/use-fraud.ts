import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useFraudStats() {
  return useQuery({
    key: 'fraud:stats',
    fetcher: () => api.fraud.stats(),
    staleTime: STALE,
  });
}

export function useFraudConfig() {
  return useQuery({
    key: 'fraud:config',
    fetcher: () => api.fraud.getConfig(),
    staleTime: STALE,
  });
}

export function useEvaluateFraud() {
  return useMutation({
    mutationFn: ({ event, context }: { event: Record<string, unknown>; context?: Record<string, unknown> }) =>
      api.fraud.evaluate(event, context),
  });
}

export function useEvaluateFraudBatch() {
  return useMutation({
    mutationFn: (events: unknown[]) => api.fraud.evaluateBatch(events),
  });
}

export function useUpdateFraudConfig() {
  return useMutation({
    mutationFn: (config: Record<string, unknown>) => api.fraud.updateConfig(config),
  });
}

export function useFraudNetworks(params?: { status?: string; limit?: number }) {
  return useQuery({
    key: `fraud-networks:${JSON.stringify(params)}`,
    fetcher: () => api.fraudNetworks.list(params),
    staleTime: STALE,
  });
}

export function useFraudNetworkDetail(networkId: string) {
  return useQuery({
    key: `fraud-network:${networkId}`,
    fetcher: () => api.fraudNetworks.get(networkId),
    staleTime: STALE,
    enabled: Boolean(networkId),
  });
}

export function useFraudNetworkGraph(networkId: string) {
  return useQuery({
    key: `fraud-network-graph:${networkId}`,
    fetcher: () => api.fraudNetworks.graph(networkId),
    staleTime: STALE,
    enabled: Boolean(networkId),
  });
}

export function useFraudNetworkMembers(networkId: string) {
  return useQuery({
    key: `fraud-network-members:${networkId}`,
    fetcher: () => api.fraudNetworks.members(networkId),
    staleTime: STALE,
    enabled: Boolean(networkId),
  });
}

export function useFraudNetworkEvidence(networkId: string) {
  return useQuery({
    key: `fraud-network-evidence:${networkId}`,
    fetcher: () => api.fraudNetworks.evidence(networkId),
    staleTime: STALE,
    enabled: Boolean(networkId),
  });
}

export function useBuildFraudNetwork() {
  return useMutation({
    mutationFn: (body: {
      anchor_entity_ids: string[];
      network_type: string;
      label?: string;
      notes?: string;
    }) => api.fraudNetworks.build(body),
  });
}

export function useFlowTraces(params?: { limit?: number }) {
  return useQuery({
    key: `flow-traces:${JSON.stringify(params)}`,
    fetcher: () => api.flowTrace.list(params),
    staleTime: STALE,
  });
}

export function useFlowTraceDetail(traceId: string) {
  return useQuery({
    key: `flow-trace:${traceId}`,
    fetcher: () => api.flowTrace.get(traceId),
    staleTime: STALE,
    enabled: Boolean(traceId),
  });
}

export function useFlowTracePaths(traceId: string) {
  return useQuery({
    key: `flow-trace-paths:${traceId}`,
    fetcher: () => api.flowTrace.paths(traceId),
    staleTime: STALE,
    enabled: Boolean(traceId),
  });
}

export function useCreateFlowTrace() {
  return useMutation({
    mutationFn: (body: {
      anchor_entity_id: string;
      direction: 'upstream' | 'downstream' | 'both';
      max_hops?: number;
      min_amount_usd?: number;
    }) => api.flowTrace.create(body),
  });
}
