import { useQuery, useMutation } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export function useAutomationOverview(hours = 24) {
  return useQuery({
    key: `automation:overview:${hours}`,
    fetcher: () => api.automation.overview(hours),
    staleTime: STALE,
  });
}

export function useAutomationMetrics(campaignId: string, hours = 24) {
  return useQuery({
    key: `automation:metrics:${campaignId}:${hours}`,
    fetcher: () => api.automation.metrics(campaignId, hours),
    staleTime: STALE,
    enabled: !!campaignId,
  });
}

export function useAutomationInsights() {
  return useQuery({
    key: 'automation:insights',
    fetcher: () => api.automation.insights(),
    staleTime: STALE,
  });
}

export function useAutomationIngest() {
  return useMutation({
    mutationFn: (event: { type: string; campaign_id?: string; user?: Record<string, unknown>; wallet_address?: string; timestamp?: string; properties?: Record<string, unknown> }) =>
      api.automation.ingest(event),
  });
}
