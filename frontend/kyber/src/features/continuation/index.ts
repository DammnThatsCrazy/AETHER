/**
 * Continuation — operator continuation routing (M4b stubs, router lands M5).
 *
 * The hooks are inert by design and the affordance is gated behind the
 * `enableKyberContinuations` feature flag, which defaults OFF. Nothing here fires
 * an HTTP request until the M5 operator continuation router exists.
 */
export {
  isContinuationRoutingEnabled,
  useContinuations,
  useCreateContinuation,
} from './use-continuations';
export type {
  Continuation,
  ContinuationListState,
  CreateContinuationInput,
  CreateContinuationResult,
  CreateContinuationState,
} from './use-continuations';
export { ContinuationCreateButton } from './continuation-create-button';
