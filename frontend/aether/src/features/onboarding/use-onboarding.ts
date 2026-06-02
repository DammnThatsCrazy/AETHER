import { useMutation, useQuery, queryCache } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@aether-app/lib/api/rest/client';
import type { TenantOnboardingStatus } from '@aether/shared';

const wrap = <T extends z.ZodType>(dataSchema: T) => z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });
const unknown = z.unknown();

export function useOnboardingStatus() {
  return useQuery({
    key: 'onboarding:status',
    fetcher: () => restClient.get('/v1/onboarding/status', wrap(unknown)).then(r => r.data as TenantOnboardingStatus),
    staleTime: 60_000,
  });
}

export function useOnboardingChecklist() {
  return useQuery({
    key: 'onboarding:checklist',
    fetcher: () => restClient.get('/v1/onboarding/checklist', wrap(unknown)).then(r => r.data as { items: TenantOnboardingStatus['steps']; tenant_actions: TenantOnboardingStatus['steps']; blockers: TenantOnboardingStatus['blockers'] }),
    staleTime: 60_000,
  });
}

export function useSdkInstructions() {
  return useQuery({ key: 'onboarding:sdk', fetcher: () => restClient.get('/v1/onboarding/sdk-instructions', wrap(unknown)).then(r => r.data as Record<string, unknown>), staleTime: 300_000 });
}

export function useEventRequirements() {
  return useQuery({ key: 'onboarding:events', fetcher: () => restClient.get('/v1/onboarding/event-requirements', wrap(unknown)).then(r => r.data as Record<string, unknown>), staleTime: 300_000 });
}

export function useGoLiveReadiness() {
  return useQuery({ key: 'onboarding:readiness', fetcher: () => restClient.get('/v1/onboarding/go-live-readiness', wrap(unknown)).then(r => r.data as Record<string, unknown>), staleTime: 60_000 });
}

export function usePatchOnboardingStep() {
  return useMutation({
    mutationFn: (input: { stepId: string; status: string }) => restClient.patch(`/v1/onboarding/steps/${input.stepId}`, wrap(unknown), { status: input.status }).then(r => r.data),
    onSuccess: () => {
      queryCache.invalidate('onboarding:status');
      queryCache.invalidate('onboarding:checklist');
      queryCache.invalidate('onboarding:readiness');
    },
  });
}
