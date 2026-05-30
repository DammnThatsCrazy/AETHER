import { useQuery, useMutation } from '@aether/ui';
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

export function useAttributionModels() {
  return useQuery({
    key: 'attribution:models',
    fetcher: () => api.attribution.models(),
    staleTime: STALE,
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

export function useResolveAttribution() {
  return useMutation({
    mutationFn: (params: { user_id: string; event: Record<string, unknown>; model?: string; touchpoints?: unknown[] }) =>
      api.attribution.resolve(params),
  });
}

export function useRecordTouchpoint() {
  return useMutation({
    mutationFn: (tp: { user_id: string; channel: string; source: string; campaign?: string; event_type: string; timestamp: string; properties?: Record<string, unknown> }) =>
      api.attribution.recordTouchpoint(tp),
  });
}

export function useClearAttributionJourney() {
  return useMutation({
    mutationFn: (userId: string) => api.attribution.clearJourney(userId),
  });
}

