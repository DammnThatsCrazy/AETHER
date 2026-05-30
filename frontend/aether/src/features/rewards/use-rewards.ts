import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export function useRewardsCampaigns(params?: { status?: string; limit?: number }) {
  return useQuery({
    key: `rewards:campaigns:${params?.status ?? 'all'}:${params?.limit ?? 50}`,
    fetcher: () => api.rewards.listCampaigns({ limit: 50, ...params }),
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

export function useProfileRewards(userId: string) {
  return useQuery({
    key: `profile:rewards:${userId}`,
    fetcher: () => api.profile.rewards(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}
