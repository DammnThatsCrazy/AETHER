import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useConsentGovernance(userId: string) {
  return useQuery({
    key: `consent:governance:${userId}`,
    fetcher: () => api.consent.getRecords(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useConsentRetentionManifest() {
  return useQuery({
    key: 'consent:retention-manifest',
    fetcher: () => api.consent.retentionManifest(),
    staleTime: STALE,
  });
}
