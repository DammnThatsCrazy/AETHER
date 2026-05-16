import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export function useCampaigns(params?: { status?: string; limit?: number }) {
  return useQuery({
    key: `campaigns:list:${params?.status ?? 'all'}:${params?.limit ?? 50}`,
    fetcher: () => api.campaigns.list({ limit: 50, ...params }),
    staleTime: STALE,
  });
}

export function useCampaign(campaignId: string) {
  return useQuery({
    key: `campaign:${campaignId}`,
    fetcher: () => api.campaigns.get(campaignId),
    staleTime: STALE,
    enabled: !!campaignId,
  });
}

export function useCampaignAttribution(campaignId: string, model?: string) {
  return useQuery({
    key: `campaign:${campaignId}:attribution:${model ?? 'multi_touch'}`,
    fetcher: () => api.campaigns.attribution(campaignId, { model: model ?? 'multi_touch' }),
    staleTime: STALE,
    enabled: !!campaignId,
  });
}

export function useCampaignMetrics(campaignId: string, hours = 24) {
  return useQuery({
    key: `campaign:${campaignId}:metrics:${hours}h`,
    fetcher: () => api.automation.metrics(campaignId, hours),
    staleTime: 30_000,
    enabled: !!campaignId,
  });
}

export function usePlatformOverview(hours = 24) {
  return useQuery({
    key: `automation:overview:${hours}h`,
    fetcher: () => api.automation.overview(hours),
    staleTime: 30_000,
  });
}

export function useAutomationInsights() {
  return useQuery({
    key: 'automation:insights',
    fetcher: () => api.automation.insights(),
    staleTime: 60_000,
  });
}
