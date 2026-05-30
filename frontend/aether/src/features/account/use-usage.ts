import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { RestClientError } from '@aether-app/lib/api/rest/client';

export interface UsageData {
  period_start: string;
  period_end: string;
  events_used: number;
  events_quota: number;
  rpm_peak: number;
  rpm_limit: number;
  overage_events: number;
  days_remaining: number;
  _fallback?: boolean;
}

const FALLBACK: UsageData = {
  period_start: '',
  period_end: '',
  events_used: 0,
  events_quota: 0,
  rpm_peak: 0,
  rpm_limit: 0,
  overage_events: 0,
  days_remaining: 0,
  _fallback: true,
};

export function useUsage() {
  return useQuery<UsageData>({
    key: 'me-usage',
    fetcher: async () => {
      try {
        return await api.me.usage();
      } catch (err) {
        if (err instanceof RestClientError && (err.status === 404 || err.status === 0)) {
          return FALLBACK;
        }
        throw err;
      }
    },
  });
}
