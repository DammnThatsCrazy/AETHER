import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 120_000;

export function useAttributionJourney(userId: string) {
  return useQuery({
    key: `attribution:journey:${userId}`,
    fetcher: () => api.attribution.journey(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useCampaignAttribution(campaignId: string, model?: string) {
  return useQuery({
    key: `attribution:campaign:${campaignId}:${model ?? 'multi_touch'}`,
    fetcher: () => api.campaigns.attribution(campaignId, { model: model ?? 'multi_touch' }),
    staleTime: STALE,
    enabled: !!campaignId,
  });
}
