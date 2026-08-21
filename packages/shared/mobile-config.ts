/**
 * Mobile config contract (v1) — GET /v1/mobile/config.
 *
 * TS twin of `services/mobile/config.py` (MobileConfig + DistributionProfile +
 * UpgradePolicy). Parity-tested by `tests/contracts/test_mobile_config_parity.py`.
 * Fields are snake_case (decision-log D6).
 */

/** Distribution-family labels. `dev` is family-agnostic. */
export const distributionFamilies = [
  'ios',
  'android',
] as const;

export type DistributionFamily = typeof distributionFamilies[number];

/** iOS distribution profiles (dev is family-agnostic). */
export const iosDistributionProfiles = [
  'dev',
  'testflight',
  'app_store',
] as const;

/** Android distribution profiles (dev is family-agnostic). */
export const androidDistributionProfiles = [
  'dev',
  'play_internal',
  'managed',
] as const;

/** All valid distribution profiles (snake_case). */
export const distributionProfiles = [
  'dev',
  'testflight',
  'app_store',
  'play_internal',
  'managed',
] as const;

export type DistributionProfile = typeof distributionProfiles[number];

/** Upgrade policy derived from the app-version comparison. */
export const upgradePolicies = [
  'required',
  'suggested',
  'none',
] as const;

export type UpgradePolicy = typeof upgradePolicies[number];

export interface MobileConfig {
  app_kind: 'aether' | 'kyber';
  environment: string;
  min_version: string;
  latest_version: string;
  upgrade_policy: UpgradePolicy;
  distribution_profile: DistributionProfile;
  feature_flags: Record<string, boolean>;
  service_capabilities: Record<string, boolean>;
  externally_blocked_providers: string[];
}

export interface MobileConfigRequest {
  installation_id: string;
}
