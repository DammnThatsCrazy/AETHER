import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export type ApiKey = Awaited<ReturnType<typeof api.settings.listKeys>>['keys'][number];

export function useApiKeys() {
  return useQuery({
    key: 'api-keys',
    fetcher: () => api.settings.listKeys().then(r => r.keys),
  });
}

export function useCreateApiKey() {
  return useMutation({
    mutationFn: (payload: { name: string; tier?: string; permissions?: string[] }) =>
      api.settings.createKey(payload),
  });
}

export function useRevokeApiKey() {
  return useMutation({
    mutationFn: (id: string) => api.settings.revokeKey(id),
  });
}
