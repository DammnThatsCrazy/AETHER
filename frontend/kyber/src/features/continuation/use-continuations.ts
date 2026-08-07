/**
 * KYBER continuations — inert stubs (M4b).
 *
 * The operator continuation router is M5. Until it ships, these hooks are
 * deliberately inert: they hold no state, call no network, and report the surface
 * as unavailable. They exist so the operator UI can be wired and flag-gated
 * without pretending the router exists. Nothing here fires an HTTP request.
 */
import { isFeatureEnabled } from '@kyber/lib/featureFlags';

/** One durable continuation once the M5 router exists. */
export interface Continuation {
  readonly continuation_id: string;
  readonly source_command_id: string;
  readonly status: string;
  readonly created_at: string;
}

export interface ContinuationListState {
  readonly data: readonly Continuation[];
  readonly isLoading: boolean;
  readonly error: null;
  readonly refetch: () => void;
}

/**
 * List hook — inert until the M5 continuation router exists. Always returns an
 * empty list that is never loading and never errors.
 */
export function useContinuations(): ContinuationListState {
  return { data: [], isLoading: false, error: null, refetch: () => undefined };
}

export interface CreateContinuationInput {
  readonly source_command_id?: string;
  readonly objective?: string;
}

export interface CreateContinuationResult {
  readonly skipped: boolean;
}

export interface CreateContinuationState {
  readonly create: (input?: CreateContinuationInput) => Promise<CreateContinuationResult>;
  readonly isAvailable: boolean;
  readonly isLoading: boolean;
  readonly error: null;
  readonly data: CreateContinuationResult | null;
  readonly reset: () => void;
}

/**
 * Creation hook — inert stub. `create` resolves `{ skipped: true }` (nothing was
 * dispatched) and `isAvailable` is always false until the M5 router exists.
 */
export function useCreateContinuation(): CreateContinuationState {
  return {
    create: async () => ({ skipped: true }),
    isAvailable: false,
    isLoading: false,
    error: null,
    data: null,
    reset: () => undefined,
  };
}

/** The M4b gate: the affordance renders only while this flag is on. */
export function isContinuationRoutingEnabled(): boolean {
  return isFeatureEnabled('enableKyberContinuations');
}
