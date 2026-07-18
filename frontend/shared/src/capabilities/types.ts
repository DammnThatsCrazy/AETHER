/**
 * Capability contract types — mirror the backend GET /v1/capabilities response
 * (services/capabilities/schema.py). Kept as plain TS types so this UI package
 * stays free of a runtime schema dependency; each app validates the payload
 * with its own zod schema before handing it to the provider.
 */

export interface EnforcementState {
  readonly policy_enforcement: boolean;
  readonly route_registry_enforced: boolean;
  readonly kyber_operator_gate: boolean;
}

export interface ReleaseCapabilities {
  readonly deployment_profile: string;
  readonly environment: string;
  readonly release_class: string | null;
  readonly enforcement: EnforcementState;
  readonly enabled_route_prefixes: readonly string[];
  readonly excluded_domains: readonly string[];
}

export interface ProviderCapability {
  readonly id: string;
  readonly category: string;
  readonly status: string;
  readonly last_successful_sync?: string | null;
  readonly error_count?: number;
  readonly staleness_label?: string;
  readonly circuit_breaker?: string;
}

export interface Capabilities {
  readonly tenant_id: string;
  readonly release: ReleaseCapabilities;
  readonly profile_sub_resources: readonly string[];
  readonly providers: readonly ProviderCapability[];
  readonly consent_purposes_granted: readonly string[];
  readonly consent_purposes_all: readonly string[];
  readonly feature_flags: Readonly<Record<string, boolean>>;
  readonly evaluated_at: string;
}

/** Frontend build identity for the diagnostics badge. */
export interface BuildInfo {
  readonly version: string;
  readonly gitSha: string;
  readonly profile: string;
  readonly environment?: string;
}

/**
 * The capability a navigation destination or route requires. A destination is
 * hidden / guarded when its domain is excluded from the release or its feature
 * flag is off for the active profile.
 */
export interface CapabilityRequirement {
  /** Release domain, matched against release.excluded_domains (plural-aware). */
  readonly domain?: string;
  /** Feature-flag key in capabilities.feature_flags that must be true. */
  readonly flag?: string;
}

/** Truthful availability of a destination given the resolved capabilities. */
export type DestinationAvailability =
  | 'available'
  | 'not_in_release'
  | 'disabled'
  | 'loading';
