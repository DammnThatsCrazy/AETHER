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
    /** Stable caller-owned run reference; scoped to this deployment by Aether. */
    runId?: string;
    /** Caller-reported payment record reference for later tenant-scoped correlation. */
    paymentIntentId?: string;
    /** Caller-reported settlement record reference for later tenant-scoped correlation. */
    settlementEventId?: string;
    status: 'started' | 'completed' | 'failed';
    durationMs?: number;
    errorCode?: string;
    triggerId?: string;
    triggerType?: string;
    actionId?: string;
    actionType?: string;
    properties?: Record<string, unknown>;
  }): void {
    const type: EventType = params.status === 'started'
      ? 'agent_task_started'
      : params.status === 'completed' ? 'agent_task_completed' : 'agent_task_failed';
    this.track({
      type,
      properties: {
        taskId: params.taskId,
        runId: params.runId,
        paymentIntentId: params.paymentIntentId,
        settlementEventId: params.settlementEventId,
        durationMs: params.durationMs,
        errorCode: params.errorCode,
        triggerId: params.triggerId,
        triggerType: params.triggerType,
        actionId: params.actionId,
        actionType: params.actionType,
        ...params.properties,
      },
    });
  }

  /** Observe an agent tool invocation on the external surface. */
  toolInvocation(params: {
    toolName: string;
    taskId?: string;
    /** Stable caller-owned run reference; scoped to this deployment by Aether. */
    runId?: string;
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
        taskId: params.taskId,
        runId: params.runId,
        status: params.status ?? 'observed',
        durationMs: params.durationMs,
        mcpServerName: params.mcpServerName,
        ...params.properties,
      },
    });
  }

  /** Record a source-reported policy decision that preceded an agent action. */
  policyEvaluated(params: {
    runId: string;
    taskId?: string;
    decisionId?: string;
    actionId?: string;
    actionType?: string;
    triggerId?: string;
    triggerType?: string;
    policyId: string;
    policyVersion?: string;
    decision: 'allow' | 'deny' | 'require_approval' | 'unknown';
    reasonCodes?: string[];
  }): void {
    const type: EventType = 'agent_policy_evaluated';
    this.track({
      type,
      properties: {
        runId: params.runId,
        taskId: params.taskId,
        decisionId: params.decisionId,
        actionId: params.actionId,
        actionType: params.actionType,
        triggerId: params.triggerId,
        triggerType: params.triggerType,
        policyId: params.policyId,
        policyVersion: params.policyVersion,
        decision: params.decision,
        reasonCodes: params.reasonCodes ?? [],
      },
    });
  }

  /** Record a source-reported delegation without asserting canonical agent identity. */
  delegatedTask(params: {
    runId: string;
    taskId?: string;
    delegationId: string;
    delegatedToAgentId: string;
    /** Explicit target namespace; the backend never infers it from the actor. */
    delegatedToNamespace?: string;
    actionId?: string;
    actionType?: string;
    triggerId?: string;
    triggerType?: string;
  }): void {
    const type: EventType = 'agent_delegated_task';
    this.track({
      type,
      properties: {
        runId: params.runId,
        taskId: params.taskId,
        delegationId: params.delegationId,
        delegatedToAgentId: params.delegatedToAgentId,
        delegatedToNamespace: params.delegatedToNamespace,
        actionId: params.actionId,
        actionType: params.actionType,
        triggerId: params.triggerId,
        triggerType: params.triggerType,
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
    outcomeId?: string;
    outcome: string;
    taskId?: string;
    /** Stable caller-owned run reference; scoped to this deployment by Aether. */
    runId?: string;
    /** Caller-reported payment record reference for later tenant-scoped correlation. */
    paymentIntentId?: string;
    /** Caller-reported settlement record reference for later tenant-scoped correlation. */
    settlementEventId?: string;
    success?: boolean;
    score?: number;
    properties?: Record<string, unknown>;
  }): void {
    const type: EventType = 'agent_outcome_recorded';
    this.track({
      type,
      properties: {
        outcomeId: params.outcomeId,
        outcome: params.outcome,
        taskId: params.taskId,
        runId: params.runId,
        paymentIntentId: params.paymentIntentId,
        settlementEventId: params.settlementEventId,
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

  // ---------------------------------------------------------------------------
  // Agent behavior taxonomy (WO-030 / WO-120). References and measurements
  // only: no prompt, response, message or memory content is accepted.
  // ---------------------------------------------------------------------------

  /** Observe an objective lifecycle step. */
  objective(params: {
    objectiveId: string;
    status: 'created' | 'started' | 'modified' | 'completed' | 'failed' | 'abandoned';
    parentObjectiveId?: string;
    ownerActorId?: string;
    goal?: string;
    objectiveType?: string;
    successCriteria?: string[];
    constraints?: string[];
    priority?: number;
    changes?: Record<string, unknown>;
    modifiedBy?: string;
    runId?: string;
    taskId?: string;
  }): void {
    const { status, ...props } = params;
    this.track({ type: `agent_objective_${status}` as EventType, properties: { ...props } });
  }

  /** Observe one step of a decision: opened, candidates, selection, closure. */
  decision(params: {
    decisionId: string;
    phase: 'started' | 'candidate_considered' | 'candidate_rejected' | 'action_selected' | 'completed';
    objectiveId?: string;
    candidateId?: string;
    amount?: string;
    currency?: string;
    vendor?: string;
    reason?: string;
    actionType?: string;
    recommendedBy?: string;
    candidateSetComplete?: boolean;
    outcome?: string;
    runId?: string;
    taskId?: string;
  }): void {
    const { phase, ...props } = params;
    assertDecimalString(props.amount);
    const type = (
      phase === 'started' || phase === 'completed' ? `agent_decision_${phase}`
        : phase === 'action_selected' ? 'agent_action_selected' : `agent_${phase}`
    ) as EventType;
    this.track({ type, properties: { ...props } });
  }

  /** Observe an authorization request or its source-reported answer. */
  authorization(params: {
    authorizationId: string;
    status: 'requested' | 'granted' | 'denied';
    decisionId?: string;
    approverActorId?: string;
    actionType?: string;
    resourceRef?: string;
  }): void {
    const { status, ...props } = params;
    this.track({ type: `agent_authorization_${status}` as EventType, properties: { ...props } });
  }

  /** Observe a tool retry or a switch to another tool. */
  toolAdaptation(params: {
    kind: 'retried' | 'switched';
    toolName: string;
    fromToolName?: string;
    attempt?: number;
    runId?: string;
    taskId?: string;
    decisionId?: string;
  }): void {
    const { kind, ...props } = params;
    this.track({ type: `agent_tool_${kind}` as EventType, properties: { ...props } });
  }

  /** Observe execution of a selected action (observation only). */
  execution(params: {
    status: 'started' | 'succeeded' | 'failed' | 'aborted';
    decisionId?: string;
    actionType?: string;
    actionId?: string;
    resourceRef?: string;
    verifiedBy?: string;
    errorCode?: string;
    runId?: string;
    taskId?: string;
  }): void {
    const { status, ...props } = params;
    this.track({ type: `agent_execution_${status}` as EventType, properties: { ...props } });
  }

  /** Observe a quote, price evaluation or transaction step. Amounts are decimal strings. */
  economic(params: {
    kind: 'quote_received' | 'price_evaluated' | 'transaction_initiated' | 'transaction_authorized'
      | 'transaction_settled' | 'transaction_failed';
    amount?: string;
    currency?: string;
    decisionId?: string;
    objectType?: string;
    objectId?: string;
    resourceRef?: string;
    authorizationId?: string;
    fundingActorId?: string;
    runId?: string;
  }): void {
    const { kind, ...props } = params;
    assertDecimalString(props.amount);
    this.track({ type: `agent_${kind}` as EventType, properties: { ...props } });
  }

  /** Observe an information input by reference (never its content). */
  information(params: {
    kind: 'information_retrieved' | 'source_consulted' | 'context_received';
    sourceRef: string;
    decisionId?: string;
    trust?: 'trusted' | 'untrusted' | 'external';
    runId?: string;
  }): void {
    const { kind, ...props } = params;
    this.track({ type: `agent_${kind}` as EventType, properties: { ...props } });
  }

  /** Observe a memory lifecycle step by reference (never its content). */
  memory(params: {
    memoryId: string;
    op: 'created' | 'retrieved' | 'updated' | 'invalidated' | 'expired';
    decisionId?: string;
    runId?: string;
  }): void {
    const { op, ...props } = params;
    this.track({ type: `agent_memory_${op}` as EventType, properties: { ...props } });
  }

  /** Observe this agent spawning a sub-agent. */
  spawned(params: { childAgentId: string; runId: string; rootAgentId?: string; taskId?: string }): void {
    this.track({
      type: 'agent_subagent_spawned',
      properties: { parentAgentId: this.deployment.agentId, ...params },
    });
  }

  /** Observe this agent instance terminating. */
  terminated(params: { runId?: string; reason?: string } = {}): void {
    this.track({ type: 'agent_terminated', properties: { ...params } });
  }
}

function assertDecimalString(amount: unknown): void {
  if (amount === undefined) return;
  if (typeof amount !== 'string' || !/^-?\d+(\.\d+)?$/.test(amount)) {
    throw new TypeError('amount must be a decimal string such as "12.50"');
  }
}
