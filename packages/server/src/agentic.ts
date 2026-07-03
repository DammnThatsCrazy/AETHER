// =============================================================================
// Aether Server SDK — Agentic observation helpers
// =============================================================================
//
// These helpers build observation-only Agentic Observation Contract v2 events.
// They never execute, sign, submit, revoke, trade, settle, send, or post.

import type {
  AgenticObservationEventV2,
  AgenticObservabilityEventType,
  AgenticRuntimeContext,
  AgenticCorrelationContext,
  AgenticMcpContext,
  AgenticAuthorizationContext,
  AgenticVerificationContext,
  AgenticPrivacyContext,
} from '@aether/shared';
import type { ServerEvent } from './types';

type TrackFn = (event: ServerEvent) => void;

export type AgenticObserverBase = {
  tenant_id: string;
  event_id?: string;
  observed_at?: string;
  source?: Partial<AgenticObservationEventV2['source']>;
  actor?: Partial<AgenticObservationEventV2['actor']>;
  agent?: AgenticObservationEventV2['agent'];
  runtime?: AgenticRuntimeContext;
  correlation?: AgenticCorrelationContext;
  mcp?: AgenticMcpContext;
  authorization?: AgenticAuthorizationContext;
  verification?: AgenticVerificationContext;
  privacy?: AgenticPrivacyContext;
};

export type AgenticObservationInput = AgenticObserverBase & {
  event_type: AgenticObservabilityEventType;
  object: AgenticObservationEventV2['object'];
  action: AgenticObservationEventV2['action'];
  risk?: AgenticObservationEventV2['risk'];
  economics?: Omit<NonNullable<AgenticObservationEventV2['economics']>, 'is_execution_by_aether'>;
};

function nowIso(): string {
  return new Date().toISOString();
}

function eventId(prefix = 'evt'): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `${prefix}_${Date.now().toString(36)}_${rand}`;
}

export function buildAgenticObservation(input: AgenticObservationInput): AgenticObservationEventV2 {
  const observedAt = input.observed_at ?? nowIso();
  return {
    event_id: input.event_id ?? eventId('agentic'),
    event_type: input.event_type,
    event_name: input.event_type,
    tenant_id: input.tenant_id,
    schema_version: '2.0',
    observed_at: observedAt,
    received_at: observedAt,
    source: {
      provider: input.source?.provider ?? 'custom',
      provider_event_id: input.source?.provider_event_id,
      integration_id: input.source?.integration_id,
      webhook_id: input.source?.webhook_id,
      sdk_name: input.source?.sdk_name ?? '@aether/server',
      sdk_version: input.source?.sdk_version,
    },
    actor: {
      actor_type: input.actor?.actor_type ?? 'agent',
      actor_id: input.actor?.actor_id ?? input.agent?.agent_id,
      external_actor_id: input.actor?.external_actor_id,
    },
    agent: input.agent,
    runtime: input.runtime,
    correlation: input.correlation,
    mcp: input.mcp,
    authorization: input.authorization,
    object: input.object,
    action: input.action,
    economics: input.economics ? { ...input.economics, is_execution_by_aether: false } : undefined,
    verification: input.verification,
    risk: input.risk,
    privacy: input.privacy ?? { content_capture_mode: 'metadata_only', privacy_class: 'metadata' },
    provenance: {
      raw_event_hash: input.event_id ?? 'sdk_generated_before_transport_hash',
      normalized_by: '@aether/server',
      schema_version: '2.0',
    },
  };
}

export function toServerEvent(event: AgenticObservationEventV2): ServerEvent {
  return {
    type: event.event_type,
    userId: event.actor.actor_type === 'human' ? event.actor.actor_id : undefined,
    messageId: event.event_id,
    timestamp: event.observed_at,
    properties: {
      ...event,
      execution_by_aether: false,
      agentic_contract_version: '2.0',
    },
  };
}

export function makeAgenticObserver(track: TrackFn) {
  const observeAgentic = (input: AgenticObservationInput): void => {
    track(toServerEvent(buildAgenticObservation(input)));
  };

  return {
    observeAgentic,

    observeAgent(input: AgenticObserverBase & { agent_id: string; owner_id?: string; organization_id?: string }): void {
      observeAgentic({
        ...input,
        event_type: 'agent_activity_observed',
        agent: { ...input.agent, agent_id: input.agent_id, owner_id: input.owner_id, organization_id: input.organization_id },
        object: { object_type: 'agent', object_id: input.agent_id },
        action: { name: 'agent_observed', status: 'observed' },
      });
    },

    observeRuntime(input: AgenticObserverBase & { runtime_id: string; agent_id?: string }): void {
      observeAgentic({
        ...input,
        event_type: 'agent_activity_observed',
        agent: { ...input.agent, agent_id: input.agent_id, runtime_id: input.runtime_id },
        runtime: { ...input.runtime, runtime_id: input.runtime_id },
        object: { object_type: 'runtime', object_id: input.runtime_id },
        action: { name: 'runtime_observed', status: 'observed' },
      });
    },

    observeExternalAccount(input: AgenticObserverBase & { external_account_id: string; provider: string; agent_id?: string }): void {
      observeAgentic({
        ...input,
        event_type: 'agentic_account_observed',
        source: { ...input.source, provider: 'custom' },
        agent: { ...input.agent, agent_id: input.agent_id },
        authorization: { ...input.authorization, external_account_id: input.external_account_id },
        object: { object_type: 'agentic_account', object_id: input.external_account_id, external_object_id: input.external_account_id },
        action: { name: 'external_account_observed', status: 'observed' },
      });
    },

    observeAuthorization(input: AgenticObserverBase & { authorization_id: string; external_account_id: string; scopes: string[]; agent_id?: string }): void {
      observeAgentic({
        ...input,
        event_type: 'agent_permission_observed',
        agent: { ...input.agent, agent_id: input.agent_id },
        authorization: {
          ...input.authorization,
          authorization_id: input.authorization_id,
          external_account_id: input.external_account_id,
          scopes: input.scopes,
        },
        object: { object_type: 'authorization_grant', object_id: input.authorization_id },
        action: { name: 'authorization_observed', status: 'observed' },
      });
    },

    observeProviderAction(input: AgenticObserverBase & { provider_action_id: string; provider_request_id?: string; external_object_id?: string; agent_id?: string }): void {
      observeAgentic({
        ...input,
        event_type: 'agent_tool_invocation_observed',
        agent: { ...input.agent, agent_id: input.agent_id },
        correlation: {
          ...input.correlation,
          provider_request_id: input.provider_request_id ?? input.correlation?.provider_request_id,
          external_object_id: input.external_object_id ?? input.correlation?.external_object_id,
        },
        object: { object_type: 'provider_action', object_id: input.provider_action_id, external_object_id: input.external_object_id },
        action: { name: 'provider_action_observed', status: 'observed' },
      });
    },

    observeProviderVerification(input: AgenticObserverBase & { verification_id: string; provider_request_id?: string; external_object_id?: string; status: NonNullable<AgenticVerificationContext['verification_status']> }): void {
      observeAgentic({
        ...input,
        event_type: input.status === 'contradicted' ? 'agent_risk_signal_observed' : 'agent_activity_observed',
        verification: {
          ...input.verification,
          verification_status: input.status,
          provider_request_id: input.provider_request_id,
          external_object_id: input.external_object_id,
        },
        object: { object_type: 'provider_verification', object_id: input.verification_id, external_object_id: input.external_object_id },
        action: { name: 'provider_verification_observed', status: input.status === 'contradicted' ? 'failed_observed' : 'observed' },
      });
    },

    observeMcpConnection(input: AgenticObserverBase & { connection_id: string; server_name?: string; agent_id?: string }): void {
      observeAgentic({
        ...input,
        event_type: 'agent_mcp_connection_observed',
        agent: { ...input.agent, agent_id: input.agent_id },
        correlation: { ...input.correlation, connection_id: input.connection_id },
        mcp: { ...input.mcp, server_name: input.server_name ?? input.mcp?.server_name },
        object: { object_type: 'mcp_connection', object_id: input.connection_id },
        action: { name: 'mcp_connection_observed', status: 'observed' },
      });
    },

    observeToolInvocation(input: AgenticObserverBase & { invocation_id: string; tool_name: string; tool_id?: string; agent_id?: string }): void {
      observeAgentic({
        ...input,
        event_type: 'agent_tool_invocation_observed',
        agent: { ...input.agent, agent_id: input.agent_id },
        correlation: { ...input.correlation, invocation_id: input.invocation_id },
        mcp: { ...input.mcp, tool_name: input.tool_name, tool_id: input.tool_id ?? input.mcp?.tool_id },
        object: { object_type: 'tool', object_id: input.tool_id ?? input.tool_name },
        action: { name: 'tool_invocation_observed', status: 'observed' },
      });
    },
  };
}
