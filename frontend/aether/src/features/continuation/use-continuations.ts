/**
 * Cross-device continuation hooks (M5c).
 *
 * Typed access to the continuation plane: recent continuations (GET
 * /v1/continuations/recent), creation (POST /v1/continuations) and deep-link
 * handoff (POST /v1/continuations/{id}/handoff). Reads are gated by the
 * `enableContinuations` feature flag (D8, default OFF): with the flag off the
 * queries never fetch and the mutations refuse to dispatch, so no HTTP request
 * can fire from these hooks.
 */
import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import type {
  ContinuationContext,
  ContinuationSelection,
} from '@aether/shared';
import type {
  ContinuationCreateInput,
  ContinuationHandoffInput,
} from '@aether-app/lib/api/endpoints';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';

export interface RecentContinuationsResponse {
  readonly continuations: ContinuationContext[];
}

export function useRecentContinuations(limit = 25) {
  const enabled = isFeatureEnabled('enableContinuations');
  return useQuery<RecentContinuationsResponse>({
    key: `continuations-recent-${limit}`,
    fetcher: () => api.continuations.recent(limit) as Promise<RecentContinuationsResponse>,
    enabled,
  });
}

export function useCreateContinuation() {
  const enabled = isFeatureEnabled('enableContinuations');
  return useMutation<ContinuationCreateInput, ContinuationContext>({
    mutationFn: async input => {
      if (!enabled) throw new Error('Continuations are not enabled.');
      return api.continuations.create(input);
    },
    invalidateKeys: ['continuations-recent'],
  });
}

export interface HandoffMutationInput {
  readonly continuation_id: string;
  readonly body: ContinuationHandoffInput;
}

export function useHandoffContinuation() {
  const enabled = isFeatureEnabled('enableContinuations');
  return useMutation<HandoffMutationInput, ContinuationSelection>({
    mutationFn: async ({ continuation_id, body }) => {
      if (!enabled) throw new Error('Continuations are not enabled.');
      return api.continuations.handoff(continuation_id, body);
    },
    invalidateKeys: ['continuations-recent'],
  });
}
