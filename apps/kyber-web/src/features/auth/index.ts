/**
 * Kyber auth feature barrel.
 *
 * Note what is NOT exported and never will be again: `getAccessToken`. The
 * browser holds no token; call sites use `credentialedFetch` from
 * `@kyber/lib/auth` (cookie + CSRF header) instead.
 */

export { AuthProvider, useAuth, useOptionalAuth, SESSION_POLL_INTERVAL_MS } from './auth-context';
export type { KyberAuthContextValue, KyberAuthStatus } from './auth-context';

export { RequireAuth } from './require-auth';
export { LoginPage } from './login-page';

export {
  useKyberSession,
  useKyberPrincipal,
  useKyberCapabilities,
  useKyberDevice,
  useKyberScope,
  useKyberStepUp,
  formatCountdown,
} from './hooks';
export type {
  KyberSessionSnapshot,
  KyberCapabilitySnapshot,
  KyberDeviceSnapshot,
  KyberScopeSnapshot,
  KyberStepUpSnapshot,
  StepUpState,
} from './hooks';

export {
  KyberSessionBanners,
  SessionBanner,
  RestrictedSessionBanner,
  RiskLimitedSessionBanner,
  TerminatedSessionBanner,
  UnapprovedDeviceBanner,
  StepUpRequiredBanner,
  ActiveScopeBanner,
} from './session-banners';

export {
  fetchPrincipal,
  fetchSession,
  buildLoginUrl,
  sanitiseReturnTo,
  startLogin,
  endSession,
  requestStepUpOptions,
  verifyStepUp,
} from './session-client';

export {
  enterScope,
  exitScope,
  fetchCurrentScope,
  fetchScopeHistory,
  describePurpose,
  SCOPE_PURPOSES,
} from './scope-client';
export type { EnterScopeInput } from './scope-client';

export {
  fetchWorkforcePrincipals,
  fetchInvitations,
  createInvitation,
  revokeInvitation,
  acceptInvitation,
  fetchAuditEvents,
} from './workforce-client';
export type { CreateInvitationInput, AuditQuery } from './workforce-client';
