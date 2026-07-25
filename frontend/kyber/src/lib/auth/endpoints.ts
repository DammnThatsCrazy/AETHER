/**
 * Canonical Kyber control-plane auth/authz endpoint paths.
 *
 * Single source of truth so no component hand-writes a path. `login` is a
 * plain browser navigation — the backend owns state/nonce/PKCE, the browser
 * generates none of it.
 */

export const KYBER_AUTH_ENDPOINTS = {
  me: '/v1/kyber/me',
  session: '/v1/kyber/auth/session',
  login: '/v1/kyber/auth/login',
  callback: '/v1/kyber/auth/callback',
  logout: '/v1/kyber/auth/logout',
  stepUpOptions: '/v1/kyber/auth/step-up/options',
  stepUpVerify: '/v1/kyber/auth/step-up/verify',
} as const;

export const KYBER_DEVICE_ENDPOINTS = {
  list: '/v1/kyber/devices',
  registrationOptions: '/v1/kyber/devices/registration/options',
  registrationVerify: '/v1/kyber/devices/registration/verify',
  proofChallenge: '/v1/kyber/devices/proof/challenge',
  proofVerify: '/v1/kyber/devices/proof/verify',
  approve: (deviceId: string) => `/v1/kyber/devices/${encodeURIComponent(deviceId)}/approve`,
  suspend: (deviceId: string) => `/v1/kyber/devices/${encodeURIComponent(deviceId)}/suspend`,
  revoke: (deviceId: string) => `/v1/kyber/devices/${encodeURIComponent(deviceId)}/revoke`,
  rename: (deviceId: string) => `/v1/kyber/devices/${encodeURIComponent(deviceId)}/rename`,
} as const;

export const KYBER_SCOPE_ENDPOINTS = {
  enter: '/v1/kyber/scopes',
  current: '/v1/kyber/scopes/current',
  list: '/v1/kyber/scopes',
  exit: (scopeId: string) => `/v1/kyber/scopes/${encodeURIComponent(scopeId)}`,
} as const;

export const KYBER_WORKFORCE_ENDPOINTS = {
  principals: '/v1/kyber/workforce/principals',
  invitations: '/v1/kyber/workforce/invitations',
  revokeInvitation: (invitationId: string) =>
    `/v1/kyber/workforce/invitations/${encodeURIComponent(invitationId)}/revoke`,
  acceptInvitation: (invitationId: string) =>
    `/v1/kyber/workforce/invitations/${encodeURIComponent(invitationId)}/accept`,
} as const;

/**
 * Audit read.
 *
 * This is the pre-existing security audit ledger, which lives under the admin
 * Kyber surface rather than the workforce plane — there is no
 * `/v1/kyber/audit/events`. Reading it requires `kyber.audit.read`.
 * See `Backend Architecture/aether-backend/services/security/admin_routes.py`.
 */
export const KYBER_AUDIT_ENDPOINTS = {
  events: '/v1/admin/kyber/security/audit-events',
} as const;
