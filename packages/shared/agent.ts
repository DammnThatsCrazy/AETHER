// =============================================================================
// Aether SDK — Shared Agent Contract
// Feeds the L2 (agent behavioral) and A2H (agent-to-human) graph layers.
// See docs/source-of-truth/ENTITY_MODEL.md §Agent and backend
// services/agent/routes.py for downstream topics.
// =============================================================================

import type { EntityRef } from './entities';

/** Agent task lifecycle status. */
export type AgentTaskStatus = 'started' | 'running' | 'completed' | 'failed' | 'cancelled';

/** A2H interaction type. */
export type A2HInteraction =
  | 'notify'
  | 'recommend'
  | 'deliver'
  | 'escalate';

/** Canonical agent-task properties. */
export interface AgentTaskProperties {
  taskId: string;
  agent: EntityRef;
  status: AgentTaskStatus;
  workerType?: string;
  /** State snapshot hash or summary — backend decides what to persist. */
  stateRef?: string;
  confidenceDelta?: number;
  durationMs?: number;
  [key: string]: unknown;
}

/** Canonical agent-decision properties (roads-not-taken record). */
export interface AgentDecisionProperties {
  decisionId: string;
  agent: EntityRef;
  taskId?: string;
  chosen: string;
  alternatives?: string[];
  confidence?: number;
  [key: string]: unknown;
}

/** Canonical agent→human interaction properties. */
export interface A2HInteractionProperties {
  interactionId: string;
  agent: EntityRef;
  user: EntityRef;
  interaction: A2HInteraction;
  channel?: 'push' | 'email' | 'sms' | 'inapp' | 'webhook';
  [key: string]: unknown;
}

// =============================================================================
// Agent lifecycle event payload types — granular lifecycle events.
// These are emitted by the SDK and validated by the backend ingestion layer.
// All payloads share the common fields: tenant_id, agent_id, timestamp.
// =============================================================================

/** Common fields present on every agent lifecycle payload. */
export interface AgentLifecycleBase {
  /** Tenant that owns this agent. Required for all lifecycle events. */
  tenantId: string;
  /** Identifier of the agent involved. Required. */
  agentId: string;
  /** ISO 8601 timestamp of the event. Required. */
  timestamp?: string;
  /** Opaque metadata passthrough. */
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface AgentRegisteredPayload extends AgentLifecycleBase {
  ownerUserId?: string;
  ownerOrgId?: string;
  agentName?: string;
  agentVersion?: string;
  capabilities?: string[];
}

export interface AgentUpdatedPayload extends AgentLifecycleBase {
  changes?: Record<string, unknown>;
}

export interface AgentAuthorizedPayload extends AgentLifecycleBase {
  authorizationId: string;
  authorizedBy?: string;
  scope?: string[];
  expiresAt?: string;
}

export interface AgentDeauthorizedPayload extends AgentLifecycleBase {
  authorizationId: string;
  revokedBy?: string;
  reason?: string;
}

export interface AgentCapabilityGrantedPayload extends AgentLifecycleBase {
  capability: string;
  grantedBy?: string;
  authorizationId?: string;
  scope?: Record<string, unknown>;
}

export interface AgentCapabilityRevokedPayload extends AgentLifecycleBase {
  capability: string;
  revokedBy?: string;
  reason?: string;
}

export interface AgentTaskCreatedPayload extends AgentLifecycleBase {
  taskId: string;
  parentTaskId?: string;
  rootAgentId?: string;
  taskType?: string;
  description?: string;
}

export interface AgentTaskDecomposedPayload extends AgentLifecycleBase {
  taskId: string;
  parentTaskId: string;
  subtaskIds: string[];
  decompositionStrategy?: string;
}

export interface AgentTaskStartedPayload extends AgentLifecycleBase {
  taskId: string;
}

export interface AgentTaskCompletedPayload extends AgentLifecycleBase {
  taskId: string;
  outcomeId?: string;
  durationMs?: number;
  result?: Record<string, unknown>;
}

export interface AgentTaskFailedPayload extends AgentLifecycleBase {
  taskId: string;
  failureReason?: string;
  durationMs?: number;
}

export interface AgentToolCalledPayload extends AgentLifecycleBase {
  toolId: string;
  taskId?: string;
  inputSummary?: string;
  durationMs?: number;
  success?: boolean;
  failureReason?: string;
}

export interface AgentResourceRequestedPayload extends AgentLifecycleBase {
  resourceId: string;
  taskId?: string;
  resourceType?: string;
  provider?: string;
  protocol?: string;
}

export interface AgentDelegatedTaskPayload extends AgentLifecycleBase {
  delegationId: string;
  taskId: string;
  delegateeAgentId: string;
  capabilityScope?: string[];
  budgetScope?: Record<string, unknown>;
}

export interface AgentSubagentSpawnedPayload extends AgentLifecycleBase {
  childAgentId: string;
  parentAgentId: string;
  rootAgentId?: string;
  delegationId?: string;
  taskId?: string;
}

export interface AgentPolicyEvaluatedPayload extends AgentLifecycleBase {
  policyId: string;
  taskId?: string;
  decision: string;
  reasoning?: string;
  confidence?: number;
}

export interface AgentHandoffPayload extends AgentLifecycleBase {
  targetAgentId?: string;
  targetUserId?: string;
  taskId?: string;
  reason?: string;
}

export interface AgentEscalatedToHumanPayload extends AgentLifecycleBase {
  targetUserId: string;
  taskId?: string;
  escalationReason?: string;
  channel?: string;
}

export interface AgentOutcomeRecordedPayload extends AgentLifecycleBase {
  outcomeId: string;
  taskId?: string;
  outcomeType?: string;
  success?: boolean;
  value?: Record<string, unknown>;
  beneficiaryActorId?: string;
}
