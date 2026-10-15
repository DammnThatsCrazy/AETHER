import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export interface UsageData {
  period_start: string;
  period_end: string;
  events_used: number;
  events_quota: number;
  rpm_peak: number;
  rpm_limit: number;
  overage_events: number;
  days_remaining: number;
}

export function useUsage() {
  return useQuery<UsageData>({
    key: 'me-usage',
    fetcher: () => api.me.usage(),
  });
}
