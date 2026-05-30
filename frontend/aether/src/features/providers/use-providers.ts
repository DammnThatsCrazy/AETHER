import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 300_000;

export function useProvidersHealth() {
  return useQuery({
    key: 'providers:health',
    fetcher: () => api.providers.health(),
    staleTime: STALE,
  });
}

export function useProvidersCategories() {
  return useQuery({
    key: 'providers:categories',
    fetcher: () => api.providers.categories(),
    staleTime: STALE,
  });
}
