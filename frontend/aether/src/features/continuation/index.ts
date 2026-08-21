/**
 * Cross-device continuation surfaces (M5c).
 *
 * Everything here is gated by feature flags that default OFF (D8) — when the
 * flags are off the components render nothing and no HTTP request fires.
 */
export {
  useRecentContinuations,
  useCreateContinuation,
  useHandoffContinuation,
} from './use-continuations';
export type {
  RecentContinuationsResponse,
  HandoffMutationInput,
} from './use-continuations';
export { useClientSync } from './use-client-sync';
export { ContinueOnPhone } from './continue-on-phone';
export { RecentActivity, SYNC_CHANGE_TYPE_LABELS, syncChangeTypeLabel } from './recent-activity';
