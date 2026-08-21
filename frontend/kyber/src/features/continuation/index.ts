/**
 * Continuation — operator continuation routing (M5d real hooks, M5b router).
 *
 * The M4b inert stubs were replaced with real flag-gated hooks: the list reads
 * GET /v1/kyber/continuations/recent, create POSTs /v1/kyber/continuations and
 * handoff POSTs /v1/kyber/continuations/{id}/handoff. Everything is gated behind the
 * `enableKyberContinuations` feature flag, which defaults OFF (D8) — while the flag
 * is off no HTTP request fires and the surfaces render nothing.
 */
export {
  isContinuationRoutingEnabled,
  useContinuations,
  useCreateContinuation,
  useCreateOperatorContinuation,
  useHandoffOperatorContinuation,
  useOperatorContinuations,
} from './use-continuations';
export type {
  Continuation,
  ContinuationListState,
  CreateContinuationInput,
  CreateContinuationResult,
  CreateContinuationState,
  HandoffContinuationInput,
  HandoffContinuationResult,
  HandoffContinuationState,
  OperatorContinuation,
  OperatorHandoffSelection,
} from './use-continuations';
export { ContinuationCreateButton } from './continuation-create-button';
export type { ContinuationCreateButtonProps } from './continuation-create-button';
export { OperatorContinuationPanel } from './operator-continuation-panel';
