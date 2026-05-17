import { useQuery, useMutation } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 120_000;

export function useAnalyticsDashboard() {
  return useQuery({
    key: 'analytics:dashboard:summary',
    fetcher: () => api.analytics.dashboardSummary(),
    staleTime: STALE,
  });
}

export function useExportStatus(exportId: string) {
  return useQuery({
    key: `analytics:export:${exportId}`,
    fetcher: () => api.analytics.exportStatus(exportId),
    staleTime: 10_000,
    enabled: !!exportId,
  });
}

export function useQueryEvents() {
  return useMutation({
    mutationFn: (query: { event_type?: string; start_date?: string; end_date?: string; user_id?: string; session_id?: string; limit?: number }) =>
      api.analytics.queryEvents(query),
  });
}

export function useAnalyticsGraphql() {
  return useMutation({
    mutationFn: ({ query, variables }: { query: string; variables?: Record<string, unknown> }) =>
      api.analytics.graphql(query, variables),
  });
}

export function useExportEvents() {
  return useMutation({
    mutationFn: (params: { format?: 'csv' | 'json' | 'parquet'; start_date?: string; end_date?: string; event_type?: string }) =>
      api.analytics.export(params),
  });
}
