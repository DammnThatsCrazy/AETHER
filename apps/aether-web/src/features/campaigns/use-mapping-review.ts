import { useQuery, useMutation, queryCache } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 20_000;

export function useMappingReviews(params?: { status?: string; limit?: number }) {
  return useQuery({
    key: `mapping-review:${params?.status ?? 'open'}:${params?.limit ?? 50}`,
    fetcher: () => api.mappingReview.list(params),
    staleTime: STALE,
  });
}

export function useResolveReview() {
  return useMutation({
    mutationFn: ({ reviewId, campaignId, note }: { reviewId: string; campaignId: string; note?: string }) =>
      api.mappingReview.resolve(reviewId, {
        campaign_id: campaignId,
        ...(note !== undefined ? { note } : {}),
      }),
    onSuccess: () => {
      queryCache.invalidatePrefix('mapping-review:');
    },
  });
}

export function useIgnoreReview() {
  return useMutation({
    mutationFn: ({ reviewId, note }: { reviewId: string; note?: string }) =>
      api.mappingReview.ignore(reviewId, {
        ...(note !== undefined ? { note } : {}),
      }),
    onSuccess: () => {
      queryCache.invalidatePrefix('mapping-review:');
    },
  });
}
