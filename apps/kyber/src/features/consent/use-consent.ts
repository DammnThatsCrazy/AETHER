import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useConsentProfile(userId: string) {
  return useQuery({
    key: `consent:profile:${userId}`,
    fetcher: () => api.consent.getProfile(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useDsrRequests(params?: { status?: string; limit?: number }) {
  return useQuery({
    key: `consent:dsr:${params?.status ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.consent.listDsrRequests(params),
    staleTime: STALE,
  });
}

export function useDsrRequest(requestId: string) {
  return useQuery({
    key: `consent:dsr-request:${requestId}`,
    fetcher: () => api.consent.getDsrRequest(requestId),
    staleTime: STALE,
    enabled: !!requestId,
  });
}

export function useUpdateConsent() {
  return useMutation({
    mutationFn: ({ userId, purposes }: { userId: string; purposes: Record<string, boolean> }) =>
      api.consent.update(userId, purposes),
  });
}

export function useCompleteDsr() {
  return useMutation({
    mutationFn: ({ requestId, notes }: { requestId: string; notes?: string }) =>
      api.consent.completeDsr(requestId, notes),
  });
}
