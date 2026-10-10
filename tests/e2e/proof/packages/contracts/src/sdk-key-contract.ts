import type { PlatformType } from '@aether/shared/contextual';

/** An SDK key — used by SDKs to authenticate with the Aether platform. */
export interface SDKKey {
  readonly key_id: string;
  readonly key_prefix: string;
  readonly workspace_id: string;
  readonly tenant_id: string;
  readonly name: string;
  readonly capabilities: readonly SDKKeyCapability[];
  readonly status: SDKKeyStatus;
  readonly created_at: string;
  readonly updated_at?: string;
  readonly expires_at?: string;
  readonly last_used_at?: string;
  readonly platform: PlatformType;
}

/** Request to create a new SDK key. */
export interface SDKKeyCreateRequest {
  readonly workspace_id: string;
  readonly name: string;
  readonly capabilities?: readonly SDKKeyCapability[];
  readonly expires_in_days?: number;
  readonly platform?: PlatformType;
}

/** Install instructions for an SDK key. */
export interface SDKKeyInstallInstructions {
  readonly sdk_name: string;
  readonly sdk_version: string;
  readonly installation_code: string;
  readonly environment_variables?: readonly string[];
  readonly initialization_code: string;
  readonly documentation_url: string;
  readonly platform: PlatformType;
}

/** SDK key response — returned after creating an SDK key. */
export interface SDKKeyResponse {
  readonly key_id: string;
  readonly key_prefix: string;
  readonly workspace_id: string;
  readonly tenant_id: string;
  readonly created_at: string;
  readonly install_instructions: SDKKeyInstallInstructions;
  readonly capabilities: readonly SDKKeyCapability[];
  readonly expires_at?: string;
  readonly status: SDKKeyStatus;
}

/** SDK key capability. */
export type SDKKeyCapability =
  | 'event_send'
  | 'batch_send'
  | 'identify'
  | 'consent'
  | 'hydrate'
  | 'revenue'
  | 'alias'
  | 'session_start'
  | 'session_end';

/** SDK key status. */
export type SDKKeyStatus =
  | 'active'
  | 'revoked'
  | 'expired'
  | 'pending';

/** Platform status value. */
export type PlatformStatusValue =
  | 'connected'
  | 'disconnected'
  | 'error'
  | 'pending'
  | 'auth_failure'
  | 'rate_limited';
