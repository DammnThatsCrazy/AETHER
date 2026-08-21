/**
 * Mobile installation + push-subscription contract (v1).
 *
 * TS twin of `shared/mobile/models.py`. A native installation is a per-app device
 * identity that extends the tenant session / Kyber device planes; a push
 * subscription binds a provider token to it. Push tokens are never carried in the
 * clear — only a `token_hash` (for dedupe); the encrypted token lives in the
 * credential platform. Parity-tested by
 * `tests/contracts/test_installation_contract_parity.py`. Fields are snake_case.
 */

/** Native platforms an installation can run on. */
export const installationPlatforms = [
  'ios',
  'android',
  'web',
] as const;

export type InstallationPlatform = typeof installationPlatforms[number];

/** Which application an installation belongs to. */
export const installationAppKinds = [
  'aether',
  'kyber',
] as const;

export type InstallationAppKind = typeof installationAppKinds[number];

/** Push transport providers. */
export const pushProviders = [
  'apns',
  'fcm',
  'web_push',
] as const;

export type PushProvider = typeof pushProviders[number];

/** Installation trust lifecycle. */
export const installationTrustStates = [
  'registered',
  'trusted',
  'revoked',
] as const;

export type InstallationTrustState = typeof installationTrustStates[number];

export interface MobileInstallation {
  id: string;
  principal_id: string;
  tenant_id?: string | null;
  app_kind: InstallationAppKind;
  platform: InstallationPlatform;
  bundle_id: string;
  environment: string;
  device_name?: string | null;
  trust_state: InstallationTrustState;
  app_version?: string | null;
  distribution_profile?: string | null;
  created_at: string;
  last_seen_at?: string | null;
  revoked_at?: string | null;
}

export interface InstallationRegistration {
  app_kind: InstallationAppKind;
  platform: InstallationPlatform;
  bundle_id: string;
  environment: string;
  device_name?: string | null;
  push_token?: string | null;
  push_provider?: PushProvider | null;
  app_version?: string | null;
  distribution_profile?: string | null;
}

export interface PushSubscription {
  id: string;
  installation_id: string;
  principal_id: string;
  platform: InstallationPlatform;
  provider: PushProvider;
  token_hash: string;
  environment: string;
  active: boolean;
  created_at: string;
  revoked_at?: string | null;
}

export interface InstallationRevocation {
  installation_id: string;
  reason?: string | null;
}
