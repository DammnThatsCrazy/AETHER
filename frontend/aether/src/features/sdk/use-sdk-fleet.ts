import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import type { SDKFleetStatus, SilentSDK } from '@aether-app/types/sdk';

/** Fleet health summary across all of the tenant's installed SDKs. */
export function useSdkFleet() {
  return useQuery<SDKFleetStatus>({
    key: 'sdk-fleet',
    fetcher: () => api.sdk.fleet() as Promise<SDKFleetStatus>,
  });
}

/** SDK instances that have stopped sending heartbeats. */
export function useSilentSdks() {
  return useQuery<SilentSDK[]>({
    key: 'sdk-silent',
    fetcher: () =>
      api.sdk.silent().then(r => (r as { silent_sdks?: SilentSDK[] }).silent_sdks ?? []),
  });
}
