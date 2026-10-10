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

export function useRewardsDecisions(params?: { decision?: string; campaign_id?: string; limit?: number }) {
  const key = `rewards:decisions:${params?.decision ?? 'all'}:${params?.campaign_id ?? 'all'}:${params?.limit ?? 50}`;
  return useQuery({
    key,
    fetcher: () => api.rewards.listDecisions({ limit: 50, ...params }),
    staleTime: STALE,
  });
}

export function useRewardDecision(decisionId: string) {
  return useQuery({
    key: `rewards:decision:${decisionId}`,
    fetcher: () => api.rewards.getDecision(decisionId),
    staleTime: STALE,
    enabled: !!decisionId,
  });
}

export function useRewardsActions(params?: { status?: string; rail?: string; limit?: number }) {
  const key = `rewards:actions:${params?.status ?? 'all'}:${params?.rail ?? 'all'}:${params?.limit ?? 50}`;
  return useQuery({
    key,
    fetcher: () => api.rewards.listActions({ limit: 50, ...params }),
    staleTime: STALE,
  });
}

export function useRewardsApprovalQueue() {
  return useRewardsActions({ status: 'pending_approval', limit: 100 });
}

export function useRewardsRails() {
  return useQuery({
    key: 'rewards:rails',
    fetcher: () => api.rewards.listRails(),
    staleTime: STALE,
  });
}

export function useRewardsProofs(params?: { status?: string; limit?: number }) {
  const key = `rewards:proofs:${params?.status ?? 'all'}:${params?.limit ?? 50}`;
  return useQuery({
    key,
    fetcher: () => api.rewards.listProofs({ limit: 50, ...params }),
    staleTime: STALE,
  });
}
