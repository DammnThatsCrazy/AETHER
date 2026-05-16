import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useRewardsCampaigns(params?: { status?: string; limit?: number }) {
  return useQuery({
    key: `rewards:campaigns:${params?.status ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.rewards.listCampaigns(params),
    staleTime: STALE,
  });
}

export function useRewardsCampaign(campaignId: string) {
  return useQuery({
    key: `rewards:campaign:${campaignId}`,
    fetcher: () => api.rewards.getCampaign(campaignId),
    staleTime: STALE,
    enabled: !!campaignId,
  });
}

export function useRewardsQueueStats() {
  return useQuery({
    key: 'rewards:queue-stats',
    fetcher: () => api.rewards.queueStats(),
    staleTime: STALE,
  });
}

export function useUserRewards(address: string) {
  return useQuery({
    key: `rewards:user:${address}`,
    fetcher: () => api.rewards.userRewards(address),
    staleTime: STALE,
    enabled: !!address,
  });
}

export function useRewardProof(rewardId: string) {
  return useQuery({
    key: `rewards:proof:${rewardId}`,
    fetcher: () => api.rewards.getProof(rewardId),
    staleTime: STALE,
    enabled: !!rewardId,
  });
}

export function useEvaluateRewards() {
  return useMutation({
    mutationFn: (event: { event_type: string; user_address: string; channel?: string; session_id?: string; properties?: Record<string, unknown> }) =>
      api.rewards.evaluate(event),
  });
}

export function useCreateRewardsCampaign() {
  return useMutation({
    mutationFn: (campaign: Record<string, unknown>) => api.rewards.createCampaign(campaign),
  });
}

export function useProcessRewardsQueue() {
  return useMutation({
    mutationFn: () => api.rewards.processQueue(),
  });
}
