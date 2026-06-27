import { useQuery, useMutation, useQueryClient } from '@aether/ui';
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
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ reviewId, campaignId, note }: { reviewId: string; campaignId: string; note?: string }) =>
      api.mappingReview.resolve(reviewId, { campaign_id: campaignId, note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['mapping-review'] });
    },
  });
}

export function useIgnoreReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ reviewId, note }: { reviewId: string; note?: string }) =>
      api.mappingReview.ignore(reviewId, { note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['mapping-review'] });
    },
  });
}
