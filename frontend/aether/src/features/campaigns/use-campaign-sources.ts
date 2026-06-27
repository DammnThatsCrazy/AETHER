import { useQuery, useMutation } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 30_000;

export function useCampaignSources() {
  return useQuery({
    key: 'campaign-sources:list',
    fetcher: () => api.campaignSources.list(),
    staleTime: STALE,
  });
}

export function useCampaignSourceHealth(connectorId: string) {
  return useQuery({
    key: `campaign-source:${connectorId}:health`,
    fetcher: () => api.campaignSources.health(connectorId),
    staleTime: 15_000,
    enabled: !!connectorId,
  });
}

export function useSyncCampaignSource() {
  return useMutation({
    mutationFn: (connectorId: string) => api.campaignSources.sync(connectorId),
    invalidateKeys: ['campaign-sources:list'],
  });
}

export function useCreateCampaignSource() {
  return useMutation({
    mutationFn: (body: { platform: string; connector_id: string; credentials?: Record<string, unknown>; label?: string }) =>
      api.campaignSources.create(body),
    invalidateKeys: ['campaign-sources:list'],
  });
}
