import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useAnalyticsSources() {
  return useQuery({
    key: 'traffic:sources',
    fetcher: () => api.analytics.sources(),
    staleTime: STALE,
  });
}

export function useAnalyticsSource(sourceId: string) {
  return useQuery({
    key: `traffic:source:${sourceId}`,
    fetcher: () => api.analytics.getSource(sourceId),
    staleTime: STALE,
    enabled: !!sourceId,
  });
}

export function useAnalyticsChannels() {
  return useQuery({
    key: 'traffic:channels',
    fetcher: () => api.analytics.channels(),
    staleTime: STALE,
  });
}

export function useReportTrafficSource() {
  return useMutation({
    mutationFn: (source: { session_id: string; source: string; timestamp: string; [k: string]: unknown }) =>
      api.traffic.reportSource(source),
  });
}

export function useTrackEvent() {
  return useMutation({
    mutationFn: (event: { type: string; session_id: string; timestamp: string; data?: Record<string, unknown> }) =>
      api.traffic.trackEvent(event),
  });
}
