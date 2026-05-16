import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useCampaignsList(params?: { status?: string; limit?: number; offset?: number }) {
  const key = `campaigns:list:${params?.status ?? ''}:${params?.limit ?? ''}:${params?.offset ?? ''}`;
  return useQuery({
    key,
    fetcher: () => api.campaigns.list(params),
    staleTime: STALE,
  });
}

export function useCampaign(campaignId: string) {
  return useQuery({
    key: `campaigns:get:${campaignId}`,
    fetcher: () => api.campaigns.get(campaignId),
    staleTime: STALE,
    enabled: !!campaignId,
  });
}

export function useCampaignAttribution(campaignId: string, params?: { model?: string; start_date?: string; end_date?: string }) {
  return useQuery({
    key: `campaigns:attribution:${campaignId}:${params?.model ?? ''}`,
    fetcher: () => api.campaigns.attribution(campaignId, params),
    staleTime: STALE,
    enabled: !!campaignId,
  });
}

export function useCreateCampaign() {
  return useMutation({
    mutationFn: (campaign: Record<string, unknown>) => api.campaigns.create(campaign),
  });
}

export function useUpdateCampaign() {
  return useMutation({
    mutationFn: ({ campaignId, updates }: { campaignId: string; updates: Record<string, unknown> }) =>
      api.campaigns.update(campaignId, updates),
  });
}

export function useDeleteCampaign() {
  return useMutation({
    mutationFn: (campaignId: string) => api.campaigns.delete(campaignId),
  });
}

export function useRecordCampaignTouchpoint() {
  return useMutation({
    mutationFn: ({ campaignId, touchpoint }: { campaignId: string; touchpoint: { channel?: string; source?: string; user_id?: string; session_id?: string; event_type?: string; is_conversion?: boolean; revenue_usd?: number; timestamp?: string; properties?: Record<string, unknown> } }) =>
      api.campaigns.touchpoint(campaignId, touchpoint),
  });
}
