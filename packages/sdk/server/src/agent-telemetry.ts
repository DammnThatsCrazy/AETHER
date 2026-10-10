// =============================================================================
// Aether Server SDK — External Agent Telemetry Plane V1
// =============================================================================
//
// Observation-only telemetry client for tenant-owned agents deployed on
// external distribution surfaces (Discord bots, Slack apps, MCP servers, ...).
//
// Security invariants:
//   - Aether observes; it never executes, resolves identity, or signs anything
//   - every event carries a validated AgentDeploymentContext as
//     context.agentDeployment
//   - canonical_entity_id is never emitted — identity resolution is
//     backend-owned, so the key is stripped from properties and context
//   - batching, retry, scrubbing, and transport are inherited from
//     AetherServerSDK (events post only to the configured /v1/batch endpoint)
//
// Usage:
//   const telemetry = new AgentTelemetryClient({
//     writeKey: '...',
//     consent: { agent: true },
//     deployment: {
//       deploymentId: 'dep-1',
//       agentId: 'agent-1',
//       externalPlatform: 'discord_bot',
//       environment: 'production',
//       consentMode: 'tenant_managed',
//     },
//   });
//   telemetry.task({ taskId: 't-1', status: 'started' });
//   await telemetry.flush();

import type { AgentDeploymentContext, EventType } from '@aether/shared';
import {
  externalPlatforms,
  agentDeploymentEnvironments,
  agentDeploymentConsentModes,
} from '@aether/shared';
import { AetherServerSDK } from './index';
import type { AetherServerConfig, ServerEvent } from './types';

export interface AgentTelemetryConfig extends AetherServerConfig {
  /** Deployment context attached to every emitted event as context.agentDeployment. */
  deployment: AgentDeploymentContext;
}

// Identity resolution is backend-owned. SDKs must never emit these keys.
const FORBIDDEN_IDENTITY_KEYS = ['canonical_entity_id', 'canonicalEntityId'];

const REQUIRED_STRING_FIELDS = ['deploymentId', 'agentId'] as const;

/**
 * Validate an AgentDeploymentContext against the shared contract enums.
 * Throws with a descriptive message on the first invalid field.
 */
export function validateAgentDeploymentContext(deployment: AgentDeploymentContext): void {
  if (!deployment || typeof deployment !== 'object') {
    throw new Error('AgentTelemetryClient requires config.deployment (AgentDeploymentContext)');
  }
  for (const field of REQUIRED_STRING_FIELDS) {
    const value = deployment[field];
    if (typeof value !== 'string' || value.length === 0) {
      throw new Error(`AgentDeploymentContext.${field} is required and must be a non-empty string`);
    }
  }
  if (!externalPlatforms.includes(deployment.externalPlatform)) {
    throw new Error(
      `AgentDeploymentContext.externalPlatform "${deployment.externalPlatform}" is invalid — `
      + `expected one of: ${externalPlatforms.join(', ')}`,
    );
  }
  if (!agentDeploymentEnvironments.includes(deployment.environment)) {
    throw new Error(
      `AgentDeploymentContext.environment "${deployment.environment}" is invalid — `
      + `expected one of: ${agentDeploymentEnvironments.join(', ')}`,
    );
  }
  if (!agentDeploymentConsentModes.includes(deployment.consentMode)) {
    throw new Error(
      `AgentDeploymentContext.consentMode "${deployment.consentMode}" is invalid — `
      + `expected one of: ${agentDeploymentConsentModes.join(', ')}`,
    );
  }
}

// Strict pick of contract fields so unknown keys never leak into events.
function pickDeploymentContext(d: AgentDeploymentContext): AgentDeploymentContext {
  return {
    deploymentId: d.deploymentId,
    agentId: d.agentId,
    externalPlatform: d.externalPlatform,
    externalPlatformAccountId: d.externalPlatformAccountId,
    externalAgentId: d.externalAgentId,
    externalAppId: d.externalAppId,
    externalChannelId: d.externalChannelId,
    externalWorkspaceId: d.externalWorkspaceId,
    environment: d.environment,
    consentMode: d.consentMode,
  };
}

// Recursively drop forbidden identity keys (mirrors the scrubber's recursion).
function stripIdentityValue(value: unknown): unknown {
  if (value === null || value === undefined || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(stripIdentityValue);
  return stripIdentityKeys(value as Record<string, unknown>);
}

function stripIdentityKeys(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (FORBIDDEN_IDENTITY_KEYS.includes(k)) continue;
    out[k] = stripIdentityValue(v);
  }
  return out;
}

export class AgentTelemetryClient extends AetherServerSDK {
  private readonly deployment: AgentDeploymentContext;

  constructor(config: AgentTelemetryConfig) {
    const { deployment, ...serverConfig } = config;
    validateAgentDeploymentContext(deployment);
    super(serverConfig);
    this.deployment = pickDeploymentContext(deployment);
  }

  /** Get the validated deployment context attached to every event. */
  getDeployment(): AgentDeploymentContext {
    return { ...this.deployment };
  }

  /**
   * Queue a single event for batched delivery. The deployment context is
   * attached as context.agentDeployment and forbidden identity keys are
   * stripped before the inherited scrub/queue/transport path runs.
   */
  track(event: ServerEvent): void {
    super.track({
      ...event,
      properties: event.properties ? stripIdentityKeys(event.properties) : undefined,
      context: {
        ...(event.context ? stripIdentityKeys(event.context) : undefined),
        agentDeployment: { ...this.deployment },
      },
    });
  }

  /** Observe an end-user interaction with the external agent. */
  interaction(params: {
    name: string;
    userId?: string;
    anonymousId?: string;
    properties?: Record<string, unknown>;
  }): void {
    const type: EventType = 'track';
    this.track({
      type,
      userId: params.userId,
      anonymousId: params.anonymousId,
      properties: {
        name: params.name,
        ...params.properties,
      },
    });
  }

  /** Observe an agent task lifecycle transition. */
  task(params: {
    taskId: string;
    status: 'started' | 'completed' | 'failed';
    durationMs?: number;
    errorCode?: string;
    properties?: Record<string, unknown>;
  }): void {
    const type: EventType = params.status === 'started'
      ? 'agent_task_started'
      : params.status === 'completed' ? 'agent_task_completed' : 'agent_task_failed';
    this.track({
      type,
      properties: {
        taskId: params.taskId,
        durationMs: params.durationMs,
        errorCode: params.errorCode,
        ...params.properties,
      },
    });
  }

  /** Observe an agent tool invocation on the external surface. */
  toolInvocation(params: {
    toolName: string;
    status?: 'observed' | 'succeeded_observed' | 'failed_observed' | 'denied_observed';
    durationMs?: number;
    mcpServerName?: string;
    properties?: Record<string, unknown>;
  }): void {
    const type: EventType = 'agent_tool_invocation_observed';
    this.track({
      type,
      properties: {
        toolName: params.toolName,
        status: params.status ?? 'observed',
        durationMs: params.durationMs,
        mcpServerName: params.mcpServerName,
        ...params.properties,
      },
    });
  }

  /** Observe wallet or on-chain transaction activity (observation only — never signing). */
  walletObservation(params: {
    kind: 'wallet' | 'transaction';
    address?: string;
    chainId?: string | number;
    transactionHash?: string;
    asset?: string;
    amount?: number;
    direction?: 'inbound' | 'outbound';
    userId?: string;
    properties?: Record<string, unknown>;
  }): void {
    const type: EventType = params.kind === 'transaction' ? 'transaction' : 'wallet';
    this.track({
      type,
      userId: params.userId,
      properties: {
        address: params.address,
        chainId: params.chainId,
        transactionHash: params.transactionHash,
        asset: params.asset,
        amount: params.amount,
        direction: params.direction,
        ...params.properties,
      },
    });
  }

  /** Observe a payment lifecycle transition (observation only — never execution). */
  paymentObservation(params: {
    status: 'initiated' | 'completed' | 'failed';
    paymentId?: string;
    amount?: number;
    currency?: string;
    rail?: string;
    errorCode?: string;
    userId?: string;
    properties?: Record<string, unknown>;
  }): void {
    const type: EventType = params.status === 'initiated'
      ? 'payment_initiated'
      : params.status === 'completed' ? 'payment_completed' : 'payment_failed';
    this.track({
      type,
      userId: params.userId,
      properties: {
        paymentId: params.paymentId,
        amount: params.amount,
        currency: params.currency,
        rail: params.rail,
        errorCode: params.errorCode,
        ...params.properties,
      },
    });
  }

  /** Record an observed agent outcome. */
  outcomeRecorded(params: {
    outcome: string;
    taskId?: string;
    success?: boolean;
    score?: number;
    properties?: Record<string, unknown>;
  }): void {
    const type: EventType = 'agent_outcome_recorded';
    this.track({
      type,
      properties: {
        outcome: params.outcome,
        taskId: params.taskId,
        success: params.success,
        score: params.score,
        ...params.properties,
      },
    });
  }

  /** Observe a risk signal raised for the external agent. */
  riskSignal(params: {
    riskLevel: 'low' | 'medium' | 'high' | 'critical';
    reasonCodes?: string[];
    policyFlags?: string[];
    properties?: Record<string, unknown>;
  }): void {
    const type: EventType = 'agent_risk_signal_observed';
    this.track({
      type,
      properties: {
        riskLevel: params.riskLevel,
        reasonCodes: params.reasonCodes ?? [],
        policyFlags: params.policyFlags ?? [],
        ...params.properties,
      },
    });
  }
}
