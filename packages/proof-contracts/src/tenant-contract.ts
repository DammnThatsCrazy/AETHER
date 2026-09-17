import type { PlatformType } from '@aether/shared/contextual';
import type { SourceClassification } from './source-classification';

/** A tenant — the top-level organizational entity. */
export interface TenantDetail {
  readonly tenant_id: string;
  readonly name: string;
  readonly slug: string;
  readonly status: TenantStatus;
  readonly plan: string;
  readonly settings: TenantSettings;
  readonly workspaces: readonly WorkspaceDetail[];
  readonly platforms: readonly PlatformRegistration[];
  readonly created_at: string;
  readonly updated_at?: string;
  readonly owner_id?: string;
  readonly contact_email?: string;
}

/** Tenant status. */
export type TenantStatus =
  | 'active'
  | 'suspended'
  | 'pending'
  | 'deleted'
  | 'trial';

/** Tenant settings. */
export interface TenantSettings {
  readonly default_environment?: 'development' | 'staging' | 'production';
  readonly consent_policy_url?: string;
  readonly consent_policy_version?: string;
  readonly SSO_enabled?: boolean;
  readonly allow_wallet_connections?: boolean;
  readonly allow_agent_observability?: boolean;
  readonly custom_settings?: Record<string, unknown>;
}

/** A workspace within a tenant. */
export interface WorkspaceDetail {
  readonly workspace_id: string;
  readonly name: string;
  readonly slug: string;
  readonly tenant_id: string;
  readonly status: WorkspaceStatus;
  readonly settings: WorkspaceSettings;
  readonly created_at: string;
  readonly updated_at?: string;
  readonly created_by?: string;
}

/** Workspace status. */
export type WorkspaceStatus =
  | 'active'
  | 'paused'
  | 'archived'
  | 'pending';

/** Workspace settings. */
export interface WorkspaceSettings {
  readonly environment?: 'development' | 'staging' | 'production';
  readonly default_currency?: string;
  readonly time_zone?: string;
  readonly custom_settings?: Record<string, unknown>;
}

/** A platform registration for a tenant/workspace. */
export interface PlatformRegistration {
  readonly platform: PlatformType;
  readonly platform_id?: string;
  readonly status: import('./sdk-key-contract').SDKKeyStatus;
  readonly connected_at?: string;
  readonly last_seen_at?: string;
  readonly event_count?: number;
  readonly error_count?: number;
  readonly settings?: Record<string, unknown>;
  readonly source?: SourceClassification;
}

/** Platform status — aggregate health of a platform integration. */
export interface PlatformStatus {
  readonly platform: PlatformType;
  readonly platform_id?: string;
  readonly state: import('./sdk-key-contract').PlatformStatusValue;
  readonly last_seen_at?: string;
  readonly event_count: number;
  readonly error_count: number;
  readonly latency_ms?: number;
  readonly last_error?: string;
  readonly last_error_at?: string;
}

/** Platform status value. */
export type PlatformStatusValue =
  | 'connected'
  | 'disconnected'
  | 'error'
  | 'pending'
  | 'auth_failure'
  | 'rate_limited';

/** Create a new tenant. */
export interface TenantCreate {
  readonly name: string;
  readonly slug: string;
  readonly contact_email: string;
  readonly plan?: string;
  readonly settings?: TenantSettings;
}

/** Create a new workspace. */
export interface WorkspaceCreate {
  readonly tenant_id: string;
  readonly name: string;
  readonly slug: string;
  readonly settings?: WorkspaceSettings;
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

/** SDK key status. */
export type SDKKeyStatus =
  | 'active'
  | 'revoked'
  | 'expired'
  | 'pending';

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

/** SDK key install instructions. */
export interface SDKKeyInstallInstructions {
  readonly sdk_name: string;
  readonly sdk_version: string;
  readonly installation_code: string;
  readonly environment_variables?: readonly string[];
  readonly initialization_code: string;
  readonly documentation_url: string;
  readonly platform: PlatformType;
}

/** Create an SDK key. */
export interface SDKKeyCreateRequest {
  readonly workspace_id: string;
  readonly name: string;
  readonly capabilities?: readonly SDKKeyCapability[];
  readonly expires_in_days?: number;
}
