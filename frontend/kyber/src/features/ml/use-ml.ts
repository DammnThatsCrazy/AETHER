import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 120_000;

export function useMLModels() {
  return useQuery({
    key: 'ml:models',
    fetcher: () => api.ml.models(),
    staleTime: STALE,
  });
}

export function useMLFeatures(entityId: string) {
  return useQuery({
    key: `ml:features:${entityId}`,
    fetcher: () => api.ml.features(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useMLPredict() {
  return useMutation({
    mutationFn: ({ modelName, entityId, features, useCache }: { modelName: string; entityId: string; features?: Record<string, unknown>; useCache?: boolean }) =>
      api.ml.predict(modelName, entityId, features, useCache),
  });
}

export function useMLPredictBatch() {
  return useMutation({
    mutationFn: ({ modelName, entities }: { modelName: string; entities: Array<{ entity_id: string; features?: Record<string, unknown> }> }) =>
      api.ml.predictBatch(modelName, entities),
  });
}
