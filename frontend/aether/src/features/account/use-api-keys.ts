import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export type ApiKey = { id: string; name: string; tier: string; permissions: string[]; last_used_at: string | null };

export function useApiKeys() {
  return useQuery<ApiKey[]>({
    key: 'api-keys',
    fetcher: () => api.settings.listKeys().then(r => (r as unknown as { api_keys?: ApiKey[]; keys?: ApiKey[] }).api_keys ?? (r as unknown as { keys: ApiKey[] }).keys),
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
