/**
 * KYBER operator continuations — real, flag-gated hooks (M5d).
 *
 * The operator continuation router (M5b) lands behind `settings.continuation.enabled`
 * and the `enableKyberContinuations` flag defaults OFF (D8), so every hook here gates
 * its HTTP traffic on the flag:
 *
 *   · flag OFF — the list hook returns an empty list that is never loading/errored and
 *     the create/handoff hooks resolve `{ skipped: true }`. No request is ever fired.
 *   · flag ON  — these hit the M5b operator router:
 *         GET  /v1/kyber/continuations/recent
 *         POST /v1/kyber/continuations
 *         POST /v1/kyber/continuations/{id}/handoff
 *
 * All wire fields are snake_case (D6) and mirror `packages/shared/continuation.ts`
 * (`ContinuationContext` / `ContinuationSelection`).
 */
import { useMutation, useQuery } from '@aether/ui';
import { useCallback } from 'react';
import { api } from '@kyber/lib/api/endpoints';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';

/**
 * One durable operator continuation — wire twin of the shared ContinuationContext.
 * Fields the wire schema marks optional are widened with explicit `| undefined` so
 * the zod-inferred type assigns under `exactOptionalPropertyTypes` (the API may
 * send `field: null` / omit the key / send the key as undefined).
 */
export interface OperatorContinuation {
  readonly version?: string | undefined;
  readonly id: string;
  readonly principal_id: string;
  readonly tenant_id?: string | null | undefined;
  readonly app_kind?: 'aether' | 'kyber' | string | null | undefined;
  readonly source_client: string;
  readonly surface: string;
  readonly resource_references?: ReadonlyArray<{ kind: string; id: string }> | undefined;
  readonly canonical_context?: Record<string, unknown> | null | undefined;
  readonly summary: {
    readonly title: string;
    readonly subtitle?: string | null | undefined;
    readonly last_meaningful_action?: string | null | undefined;
  };
  readonly state_revision?: number | undefined;
  readonly sensitivity?: string | undefined;
  readonly freshness?: string | null | undefined;
  readonly expires_at?: string | null | undefined;
  readonly updated_at: string;
}

/** The deep-link selection token minted at handoff — shared ContinuationSelection twin. */
export interface OperatorHandoffSelection {
  readonly token: string;
  readonly tenant_scope: string;
  readonly principal_id: string;
  readonly mode?: string | undefined;
  readonly resource_ids?: readonly string[] | null | undefined;
  readonly saved_view_id?: string | null | undefined;
  readonly query_id?: string | null | undefined;
  readonly as_of?: string | null | undefined;
  readonly expires_at?: string | null | undefined;
  readonly created_at: string;
}

/** Backwards-compatible name retained from the M4b scaffold. */
export type Continuation = OperatorContinuation;

export interface ContinuationListState {
  readonly data: readonly OperatorContinuation[];
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly refetch: () => void;
}

/**
 * GET /v1/kyber/continuations/recent — recent operator continuations.
 *
 * Flag-gated: while `enableKyberContinuations` is off, `useQuery` runs with
 * `enabled: false` so no HTTP request fires and the list is empty.
 */
export function useOperatorContinuations(): ContinuationListState {
  const enabled = isContinuationRoutingEnabled();
  const { data, isLoading, error, refetch } = useQuery<{ continuations: OperatorContinuation[] }>({
    key: 'kyber-operator-continuations-recent',
    fetcher: () => api.continuations.recent(),
    enabled,
    staleTime: 15_000,
  });
  return {
    data: data?.continuations ?? [],
    isLoading: data === null && isLoading,
    error,
    refetch,
  };
}

/** Alias retained from the M4b scaffold — the real recent-continuations hook. */
export function useContinuations(): ContinuationListState {
  return useOperatorContinuations();
}

export interface CreateContinuationInput {
  readonly source_command_id?: string;
  readonly objective?: string;
  readonly title?: string;
}

export interface CreateContinuationResult {
  readonly skipped: boolean;
  readonly continuation?: OperatorContinuation;
}

export interface CreateContinuationState {
  readonly create: (input?: CreateContinuationInput) => Promise<CreateContinuationResult>;
  readonly isAvailable: boolean;
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly data: CreateContinuationResult | null;
  readonly reset: () => void;
}

/**
 * POST /v1/kyber/continuations — mint an operator continuation.
 *
 * Flag-gated: while the flag is off `create` resolves `{ skipped: true }` and no HTTP
 * request fires. When on, the input is sent snake_case.
 */
export function useCreateOperatorContinuation(): CreateContinuationState {
  const enabled = isContinuationRoutingEnabled();
  const mutation = useMutation<CreateContinuationInput | undefined, CreateContinuationResult>({
    mutationFn: async input => {
      if (!enabled) return { skipped: true };
      const continuation = await api.continuations.create({
        ...(input?.source_command_id ? { source_command_id: input.source_command_id } : {}),
        ...(input?.objective ? { objective: input.objective } : {}),
        ...(input?.title ? { title: input.title } : {}),
      });
      return { skipped: false, continuation };
    },
  });

  const create = useCallback(
    async (input?: CreateContinuationInput): Promise<CreateContinuationResult> => {
      const result = await mutation.mutate(input);
      return result ?? { skipped: true };
    },
    [mutation.mutate],
  );

  return {
    create,
    isAvailable: enabled,
    isLoading: mutation.isLoading,
    error: mutation.error,
    data: mutation.data,
    reset: mutation.reset,
  };
}

/** Alias retained from the M4b scaffold — the real create hook. */
export function useCreateContinuation(): CreateContinuationState {
  return useCreateOperatorContinuation();
}

export interface HandoffContinuationInput {
  readonly continuation_id: string;
  readonly reason?: string;
}

export interface HandoffContinuationResult {
  readonly skipped: boolean;
  readonly selection?: OperatorHandoffSelection;
}

export interface HandoffContinuationState {
  readonly handoff: (input: HandoffContinuationInput) => Promise<HandoffContinuationResult>;
  readonly isAvailable: boolean;
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly data: HandoffContinuationResult | null;
  readonly reset: () => void;
}

/**
 * POST /v1/kyber/continuations/{id}/handoff — mint the deep-link selection token.
 *
 * Flag-gated: while the flag is off `handoff` resolves `{ skipped: true }` and no HTTP
 * request fires.
 */
export function useHandoffOperatorContinuation(): HandoffContinuationState {
  const enabled = isContinuationRoutingEnabled();
  const mutation = useMutation<HandoffContinuationInput, HandoffContinuationResult>({
    mutationFn: async input => {
      if (!enabled) return { skipped: true };
      const selection = await api.continuations.handoff(input.continuation_id, {
        ...(input.reason ? { reason: input.reason } : {}),
      });
      return { skipped: false, selection };
    },
  });

  const handoff = useCallback(
    async (input: HandoffContinuationInput): Promise<HandoffContinuationResult> => {
      const result = await mutation.mutate(input);
      return result ?? { skipped: true };
    },
    [mutation.mutate],
  );

  return {
    handoff,
    isAvailable: enabled,
    isLoading: mutation.isLoading,
    error: mutation.error,
    data: mutation.data,
    reset: mutation.reset,
  };
}

/** The M5d gate: these surfaces render only while this flag is on. */
export function isContinuationRoutingEnabled(): boolean {
  return isFeatureEnabled('enableKyberContinuations');
}
