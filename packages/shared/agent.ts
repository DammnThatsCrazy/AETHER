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
