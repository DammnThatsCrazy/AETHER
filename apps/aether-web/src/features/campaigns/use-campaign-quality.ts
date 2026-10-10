import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export function useCampaignQuality() {
  return useQuery({
    key: 'campaign-quality',
    fetcher: () => api.campaigns.quality(),
    staleTime: 60_000,
  });
}
