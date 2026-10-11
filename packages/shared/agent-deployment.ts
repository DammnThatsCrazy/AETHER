// =============================================================================
// External Agent Telemetry Plane — deployment contracts
// =============================================================================
// Aether observes telemetry from tenant-owned agents deployed on external
// distribution surfaces. Aether does not publish, host, or operate external
// agents, and it does not operate a marketplace. `custom_marketplace` refers
// only to a tenant/customer-owned or third-party marketplace surface.
//
// SDKs may attach an AgentDeploymentContext to observed events. SDKs must
// never emit `canonical_entity_id`; identity resolution is backend-owned.
// =============================================================================

export const AGENT_DEPLOYMENT_SCHEMA_VERSION = 'agent.deployment.v1' as const;

/** External distribution surface a tenant-owned agent is deployed on. */
export const externalPlatforms = [
  'web_widget',
  'mobile_app',
  'discord_bot',
  'telegram_bot',
  'slack_app',
  'shopify_app',
  'salesforce_app',
  'custom_marketplace',
  'wallet_app',
  'browser_extension',
  'mcp_server',
  'backend_worker',
  'api_agent',
  'unknown',
] as const;
export type ExternalPlatform = typeof externalPlatforms[number];

export const agentDeploymentEnvironments = [
  'production',
  'staging',
  'sandbox',
  'development',
] as const;
export type AgentDeploymentEnvironment = typeof agentDeploymentEnvironments[number];

/** Who manages end-user consent for telemetry observed via this deployment. */
export const agentDeploymentConsentModes = [
  'tenant_managed',
  'platform_managed',
  'aether_managed',
] as const;
export type AgentDeploymentConsentMode = typeof agentDeploymentConsentModes[number];

/** Deployment lifecycle. Transitions are enforced by the backend registry. */
export const agentDeploymentStatuses = [
  'active',
  'paused',
  'revoked',
  'error',
  'archived',
] as const;
export type AgentDeploymentStatus = typeof agentDeploymentStatuses[number];

/**
 * Tenant-declared origin for an external agent deployment. This records where
 * the tenant says a template came from; it is not proof that the marketplace
 * published the listing or that the listed capabilities are granted at run
 * time. `sourceNamespace` scopes all source references and is never a
 * canonical agent identity.
 */
export interface AgentMarketplaceOrigin {
  schemaVersion?: 'agent.marketplace-origin.v1';
  sourceNamespace: string;
  listingRef: string;
  templateRef: string;
  templateVersion: string;
  listingUrl?: string;
  category?: string;
  /** Catalog labels only; these are not runtime authority grants. */
  catalogCapabilities?: string[];
  /** Set by the registry. Callers cannot claim provider verification. */
  assertion?: 'tenant_declared';
}

/**
 * Deployment-aware context attached to telemetry emitted by external agent
 * runtimes. `deploymentId` identifies the deployment and `agentId` the agent;
 * neither identifies a human by itself and neither is a merge-eligible
 * identity signal.
 */
export interface AgentDeploymentContext {
  deploymentId: string;
  agentId: string;
  externalPlatform: ExternalPlatform;
  externalPlatformAccountId?: string;
  externalAgentId?: string;
  externalAppId?: string;
  externalChannelId?: string;
  externalWorkspaceId?: string;
  environment: AgentDeploymentEnvironment;
  consentMode: AgentDeploymentConsentMode;
}

/** Rolling 24h telemetry health counters maintained by the backend. */
export interface AgentDeploymentHealth {
  healthScore?: number;
  eventCount24h: number;
  acceptedCount24h: number;
  rejectedCount24h: number;
  errorCount24h: number;
  consentBlockedCount24h: number;
  graphProjectionLagMs?: number;
}

/**
 * Tenant-scoped external agent deployment registry record as returned by
 * `/v1/agent/deployments` APIs. Secrets are never stored on or returned with
 * a deployment; `metadata` is sanitized server-side.
 */
export interface AgentDeployment extends AgentDeploymentHealth {
  id: string;
  tenantId: string;
  agentId: string;
  displayName: string;
  description?: string;
  externalPlatform: ExternalPlatform;
  externalPlatformAccountId?: string;
  externalAgentId?: string;
  externalAppId?: string;
  externalChannelId?: string;
  externalWorkspaceId?: string;
  environment: AgentDeploymentEnvironment;
  status: AgentDeploymentStatus;
  consentMode: AgentDeploymentConsentMode;
  /** Canonical event families this deployment may emit (subset of registry families). */
  allowedEventFamilies: string[];
  /** Consent purposes that must be satisfied for events from this deployment. */
  requiredConsentPurposes: string[];
  /** Declared capability scopes (observation-only; never execution grants). */
  capabilityScopes: string[];
  /** Optional source lineage, immutable after deployment creation. */
  marketplaceOrigin?: AgentMarketplaceOrigin;
  /** Present on deployment-create responses when an origin was supplied. */
  marketplaceOriginGraphProjectionStatus?:
    | 'queued'
    | 'persisted'
    | 'partial'
    | 'failed'
    | 'disabled';
  metadata?: Record<string, unknown>;
  firstSeenAt?: string;
  lastSeenAt?: string;
  lastEventAt?: string;
  createdAt: string;
  updatedAt: string;
  revokedAt?: string;
  archivedAt?: string;
}

/** Audit record for deployment lifecycle changes. */
export interface AgentDeploymentAuditRecord {
  id: string;
  tenantId: string;
  deploymentId: string;
  action:
    | 'created'
    | 'updated'
    | 'paused'
    | 'reactivated'
    | 'revoked'
    | 'archived'
    | 'errored';
  actor: string;
  requestId?: string;
  detail?: Record<string, unknown>;
  occurredAt: string;
}
