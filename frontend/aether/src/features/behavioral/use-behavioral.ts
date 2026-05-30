import { useQuery, useMutation } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

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

export function useBehavioralSnapshot(entityId: string) {
  return useQuery({
    key: `behavioral:snapshot:${entityId}`,
    fetcher: () => api.behavioral.snapshot(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useBehavioralHistory(entityId: string, params?: { window?: string; limit?: number }) {
  return useQuery({
    key: `behavioral:history:${entityId}:${params?.window ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.behavioral.history(entityId, params),
    staleTime: STALE,
    enabled: !!entityId,
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

export function useExpectationsSignals(entityId: string, params?: { signal_type?: string; limit?: number }) {
  return useQuery({
    key: `expectations:signals:${entityId}:${params?.signal_type ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.expectations.signals(entityId, params),
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

export function useScanBehavioral() {
  return useMutation({
    mutationFn: (entityId: string) => api.behavioral.scan(entityId),
  });
}

export function useScanExpectations() {
  return useMutation({
    mutationFn: (entityId: string) => api.expectations.scan(entityId),
  });
}
