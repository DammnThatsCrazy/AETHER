import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useBehavioralSummary() {
  return useQuery({
    key: 'behavioral:summary',
    fetcher: () => api.behavioral.summary(),
    staleTime: STALE,
  });
}

export function useBehavioralEntity(entityId: string) {
  return useQuery({
    key: `behavioral:entity:${entityId}`,
    fetcher: () => api.behavioral.entity(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useBehavioralSignals(entityId: string, params?: { family?: string; limit?: number }) {
  return useQuery({
    key: `behavioral:signals:${entityId}:${params?.family ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.behavioral.signals(entityId, params),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useBehavioralRegistry() {
  return useQuery({
    key: 'behavioral:registry',
    fetcher: () => api.behavioral.registry(),
    staleTime: STALE,
  });
}

export function useExpectationsSummary() {
  return useQuery({
    key: 'expectations:summary',
    fetcher: () => api.expectations.summary(),
    staleTime: STALE,
  });
}

export function useExpectationsContradictions(limit = 50) {
  return useQuery({
    key: `expectations:contradictions:${limit}`,
    fetcher: () => api.expectations.contradictions(limit),
    staleTime: STALE,
  });
}

export function useExpectationsSilence() {
  return useQuery({
    key: 'expectations:silence',
    fetcher: () => api.expectations.silence(),
    staleTime: STALE,
  });
}

export function useExpectationsGroup(populationId: string) {
  return useQuery({
    key: `expectations:group:${populationId}`,
    fetcher: () => api.expectations.group(populationId),
    staleTime: STALE,
    enabled: !!populationId,
  });
}

export function useExpectationsGroupGaps(populationId: string) {
  return useQuery({
    key: `expectations:group-gaps:${populationId}`,
    fetcher: () => api.expectations.groupGaps(populationId),
    staleTime: STALE,
    enabled: !!populationId,
  });
}

export function useExpectationsEntity(entityId: string) {
  return useQuery({
    key: `expectations:entity:${entityId}`,
    fetcher: () => api.expectations.entity(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useExpectationsEntitySignals(entityId: string, params?: { signal_type?: string; limit?: number }) {
  return useQuery({
    key: `expectations:entity-signals:${entityId}:${params?.signal_type ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.expectations.entitySignals(entityId, params),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useExpectationsExplain(entityId: string) {
  return useQuery({
    key: `expectations:explain:${entityId}`,
    fetcher: () => api.expectations.explain(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useExpectationsSignal(signalId: string) {
  return useQuery({
    key: `expectations:signal:${signalId}`,
    fetcher: () => api.expectations.getSignal(signalId),
    staleTime: STALE,
    enabled: !!signalId,
  });
}

export function useScanBehavior() {
  return useMutation({
    mutationFn: (entityId: string) => api.behavioral.scan(entityId),
  });
}

export function useScanExpectations() {
  return useMutation({
    mutationFn: (entityId: string) => api.expectations.scan(entityId),
  });
}
