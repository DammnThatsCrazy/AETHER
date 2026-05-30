import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 120_000;

export function usePopulationSummary() {
  return useQuery({
    key: 'population:summary',
    fetcher: () => api.population.summary(),
    staleTime: STALE,
  });
}

export function usePopulationGroups(type?: string, limit = 50) {
  return useQuery({
    key: `population:groups:${type ?? ''}:${limit}`,
    fetcher: () => api.population.groups(type, limit),
    staleTime: STALE,
  });
}
