/**
 * Aether Agentic SDK — Contract v2 observation envelope builders.
 *
 * INVARIANT: execution_by_aether is always false. These are observation-only envelopes.
 */

export type AgentEventProvider =
  | "robinhood"
  | "agentmail"
  | "x402"
  | "mcp"
  | "custom"
  | "unknown";

export type ActorType = "human" | "agent" | "service" | "organization";

export type ActionStatus =
  | "observed"
  | "succeeded_observed"
  | "failed_observed"
  | "denied_observed"
  | "unknown";

export interface AgentObservationSource {
  provider: AgentEventProvider;
  provider_event_id?: string;
  integration_id?: string;
  webhook_id?: string;
  sdk_name?: string;
  sdk_version?: string;
}

export interface AgentObservationActor {
  actor_type: ActorType;
  actor_id?: string;
  external_actor_id?: string;
}

export interface AgentRef {
  agent_id?: string;
  external_agent_id?: string;
  model?: string;
  framework?: string;
  autonomy_level?: "manual" | "assisted" | "semi_autonomous" | "autonomous_observed";
  agent_version?: string;
  model_version?: string;
  framework_version?: string;
  runtime_id?: string;
  environment?: string;
  owner_id?: string;
  organization_id?: string;
}

export interface AgentObservationObject {
  object_type: string;
  object_id?: string;
  external_object_id?: string;
}

export interface AgentObservationAction {
  name: string;
  status?: ActionStatus;
  intent?: string;
  outcome?: string;
}

export interface AgentObservationEconomics {
  amount?: number;
  currency?: string;
  asset?: string;
  network?: string;
  rail?: string;
  direction?: string;
  is_execution_by_aether: false;
}

export interface RuntimeRef {
  runtime_id?: string;
  environment?: string;
  instance_id?: string;
}

export interface CorrelationRef {
  trace_id?: string;
  span_id?: string;
  session_id?: string;
  parent_observation_id?: string;
}

export interface MCPObservationContext {
  server_name?: string;
  server_url?: string;
  tool_name?: string;
  protocol_version?: string;
}

export interface AuthorizationContext {
  grant_id?: string;
  scope?: string[];
  delegated_by?: string;
  expires_at?: string;
}

export interface VerificationContext {
  verified_by?: string;
  verification_method?: string;
  verification_status?: string;
  verified_at?: string;
}

export interface PrivacyContext {
  privacy_class?: string;
  consent_snapshot_id?: string;
  dsr_applicable?: boolean;
}

export interface AgentEventEnvelope {
  tenant_id: string;
  event_name: string;
  source: AgentObservationSource;
  actor: AgentObservationActor;
  agent?: AgentRef;
  object: AgentObservationObject;
  action: AgentObservationAction;
  economics?: AgentObservationEconomics;
  runtime?: RuntimeRef;
  correlation?: CorrelationRef;
  mcp?: MCPObservationContext;
  authorization?: AuthorizationContext;
  verification?: VerificationContext;
  privacy?: PrivacyContext;
  execution_by_aether?: false;
}

export function buildAgentEvent(params: AgentEventEnvelope): AgentEventEnvelope {
  if ((params as any).execution_by_aether === true) {
    throw new Error(
      "execution_by_aether must be false — AETHER observes; it does not execute"
    );
  }
  if (params.economics && (params.economics as any).is_execution_by_aether === true) {
    throw new Error("economics.is_execution_by_aether must be false");
  }
  return {
    ...params,
    execution_by_aether: false as const,
    economics: params.economics
      ? { ...params.economics, is_execution_by_aether: false as const }
      : undefined,
  };
}

export function buildMCPObservation(params: {
  tenant_id: string;
  agent_id?: string;
  server_name: string;
  server_url?: string;
  tools?: string[];
}) {
  return {
    tenant_id: params.tenant_id,
    agent_id: params.agent_id,
    server_name: params.server_name,
    server_url: params.server_url,
    tools: params.tools ?? [],
    execution_by_aether: false as const,
  };
}

export function buildToolInvocation(params: {
  tenant_id: string;
  tool_name: string;
  agent_id?: string;
  duration_ms?: number;
  status?: ActionStatus;
}) {
  return {
    tenant_id: params.tenant_id,
    tool_name: params.tool_name,
    agent_id: params.agent_id,
    duration_ms: params.duration_ms,
    status: params.status ?? ("observed" as ActionStatus),
    execution_by_aether: false as const,
  };
}

export function buildRiskSignal(params: {
  tenant_id: string;
  agent_id?: string;
  risk_level: "low" | "medium" | "high" | "critical";
  reason_codes?: string[];
  policy_flags?: string[];
}) {
  return {
    tenant_id: params.tenant_id,
    agent_id: params.agent_id,
    risk_level: params.risk_level,
    reason_codes: params.reason_codes ?? [],
    policy_flags: params.policy_flags ?? [],
  };
}
