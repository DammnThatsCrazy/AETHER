import { useQuery, useMutation } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

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
    mutationFn: ({ userId, purposes, granted, source }: { userId: string; purposes: string[]; granted: boolean; source?: string }) =>
      api.consent.update(userId, purposes, granted, source),
  });
}

export function useSubmitDsr() {
  return useMutation({
    mutationFn: ({ userId, requestType, details }: { userId: string; requestType: 'access' | 'deletion' | 'portability'; details?: Record<string, unknown> }) =>
      api.consent.submitDsr(userId, requestType, details),
  });
}
