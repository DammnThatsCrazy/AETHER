import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import type { SDKManifest, SDKRolloutStatus, PublishManifestInput } from '@aether-app/types/sdk';

/** Active remote-config manifest the tenant's SDKs receive on startup. */
export function useSdkManifest() {
  return useQuery<SDKManifest | null>({
    key: 'sdk-manifest',
    fetcher: () =>
      api.sdk.manifest().then(r => (r as { manifest?: SDKManifest | null }).manifest ?? (r as SDKManifest | null)),
  });
}

/** Rollout adoption status + manifest versioning metadata. */
export function useSdkRollout() {
  return useQuery<SDKRolloutStatus>({
    key: 'sdk-rollout',
    fetcher: () => api.sdk.rolloutStatus() as Promise<SDKRolloutStatus>,
  });
}

/** Publish a new manifest version (admin permission required). */
export function usePublishManifest() {
  return useMutation({
    mutationFn: (input: PublishManifestInput) =>
      api.sdk.publishManifest(input as Record<string, unknown>),
  });
}

/** Roll back to the previous manifest version (admin permission required). */
export function useRollbackManifest() {
  return useMutation({
    mutationFn: (_: void) => api.sdk.rollback(),
  });
}
