import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export type MeProfile = Awaited<ReturnType<typeof api.me.profile>>;

export function useMeProfile() {
  return useQuery<MeProfile>({
    key: 'me-profile',
    fetcher: () => api.me.profile(),
  });
}
