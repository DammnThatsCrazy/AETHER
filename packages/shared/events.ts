// =============================================================================
// Aether SDK — Shared Event Envelope & Registry
// Canonical shapes every SDK emits and every ingestion validator accepts.
// See docs/source-of-truth/EVENT_REGISTRY.md and INGESTION_CONTRACT.md.
// =============================================================================

import type { ConsentState } from './consent';
import type { ActorKind, Provenance } from './provenance';

// ---------------------------------------------------------------------------
// Event families
// ---------------------------------------------------------------------------

/** The canonical event-type string union the backend validates. */
export type EventType =
  // Core analytics
  | 'track'
  | 'page'
  | 'screen'
  | 'heartbeat'
  | 'error'
  | 'performance'
  | 'experiment'
  // Journey lifecycle
  | 'journey_started'
  | 'journey_paused'
  | 'journey_resumed'
  | 'journey_continued'
  | 'journey_completed'
  | 'journey_abandoned'
  | 'journey_checkpoint'
  // Identity
  | 'identify'
  | 'consent'
  // Commerce / access (Web2 + Web3 unified)
  | 'conversion'
  | 'payment_initiated'
  | 'payment_completed'
  | 'payment_failed'
  | 'approval_requested'
  | 'approval_resolved'
  | 'entitlement_granted'
  | 'entitlement_revoked'
  | 'access_granted'
  | 'access_denied'
  // Wallet / on-chain (optional)
  | 'wallet'
  | 'transaction'
  | 'contract_action'
  // Agent lifecycle (optional) — legacy aliases kept for backward compatibility
  | 'agent_task'
  | 'agent_decision'
  | 'a2h_interaction'
  // Agent lifecycle — granular events
  | 'agent_registered'
  | 'agent_updated'
  | 'agent_authorized'
  | 'agent_deauthorized'
  | 'agent_capability_granted'
  | 'agent_capability_revoked'
  | 'agent_task_created'
  | 'agent_task_decomposed'
  | 'agent_task_started'
  | 'agent_task_completed'
  | 'agent_task_failed'
  | 'agent_tool_called'
  | 'agent_resource_requested'
  | 'agent_delegated_task'
  | 'agent_subagent_spawned'
  | 'agent_policy_evaluated'
  | 'agent_handoff'
  | 'agent_escalated_to_human'
  | 'agent_outcome_recorded'
  // Reward enablement (A6) — eligibility events emitted by Aether, not the tenant
  | 'reward_action_queued'
  | 'reward_proof_generated'
  | 'reward_delivered'
  | 'reward_claim_submitted'
  // x402 (optional) — legacy alias kept for backward compatibility
  | 'x402_payment'
  // x402 lifecycle — granular events
  | 'x402_resource_requested'
  | 'x402_payment_required'
  | 'x402_quote_received'
  | 'x402_authorization_requested'
  | 'x402_authorization_resolved'
  | 'x402_payment_intent_created'
  | 'x402_payment_submitted'
  | 'x402_payment_settled'
  | 'x402_payment_failed'
  | 'x402_payment_timeout'
  | 'x402_receipt_verified'
  | 'x402_access_granted'
  | 'x402_access_denied'
  | 'x402_refund_or_reversal';

export type EventFamily =
  | 'core'
  | 'journey'
  | 'identity'
  | 'consent'
  | 'commerce'
  | 'wallet'
  | 'agent'
  | 'x402'
  | 'reward';

/** Map from each event type to the family it belongs to. */
export const EVENT_FAMILY: Record<EventType, EventFamily> = {
  track: 'core', page: 'core', screen: 'core', heartbeat: 'core',
  error: 'core', performance: 'core', experiment: 'core',
  journey_started: 'journey', journey_paused: 'journey', journey_resumed: 'journey',
  journey_continued: 'journey', journey_completed: 'journey', journey_abandoned: 'journey',
  journey_checkpoint: 'journey',
  identify: 'identity',
  consent: 'consent',
  conversion: 'commerce',
  payment_initiated: 'commerce', payment_completed: 'commerce', payment_failed: 'commerce',
  approval_requested: 'commerce', approval_resolved: 'commerce',
  entitlement_granted: 'commerce', entitlement_revoked: 'commerce',
  access_granted: 'commerce', access_denied: 'commerce',
  wallet: 'wallet', transaction: 'wallet', contract_action: 'wallet',
  // agent legacy
  agent_task: 'agent', agent_decision: 'agent', a2h_interaction: 'agent',
  // agent lifecycle
  agent_registered: 'agent', agent_updated: 'agent', agent_authorized: 'agent',
  agent_deauthorized: 'agent', agent_capability_granted: 'agent', agent_capability_revoked: 'agent',
  agent_task_created: 'agent', agent_task_decomposed: 'agent', agent_task_started: 'agent',
  agent_task_completed: 'agent', agent_task_failed: 'agent', agent_tool_called: 'agent',
  agent_resource_requested: 'agent', agent_delegated_task: 'agent', agent_subagent_spawned: 'agent',
  agent_policy_evaluated: 'agent', agent_handoff: 'agent', agent_escalated_to_human: 'agent',
  agent_outcome_recorded: 'agent',
  // reward enablement (A6)
  reward_action_queued: 'reward',
  reward_proof_generated: 'reward',
  reward_delivered: 'reward',
  reward_claim_submitted: 'reward',
  // x402 legacy
  x402_payment: 'x402',
  // x402 lifecycle
  x402_resource_requested: 'x402', x402_payment_required: 'x402', x402_quote_received: 'x402',
  x402_authorization_requested: 'x402', x402_authorization_resolved: 'x402',
  x402_payment_intent_created: 'x402', x402_payment_submitted: 'x402',
  x402_payment_settled: 'x402', x402_payment_failed: 'x402', x402_payment_timeout: 'x402',
  x402_receipt_verified: 'x402', x402_access_granted: 'x402', x402_access_denied: 'x402',
  x402_refund_or_reversal: 'x402',
};

/**
 * Required consent purpose for each event type. If the purpose is not
 * granted, the SDK event queue MUST drop the event before transport.
 */
export const EVENT_CONSENT_PURPOSE: Record<EventType, string> = {
  track: 'analytics', page: 'analytics', screen: 'analytics',
  heartbeat: 'analytics', error: 'analytics', performance: 'analytics',
  journey_started: 'analytics', journey_paused: 'analytics', journey_resumed: 'analytics',
  journey_continued: 'analytics', journey_completed: 'analytics', journey_abandoned: 'analytics',
  journey_checkpoint: 'analytics',
  identify: 'analytics',
  experiment: 'marketing', conversion: 'marketing',
  consent: 'analytics',
  payment_initiated: 'commerce', payment_completed: 'commerce', payment_failed: 'commerce',
  approval_requested: 'commerce', approval_resolved: 'commerce',
  entitlement_granted: 'commerce', entitlement_revoked: 'commerce',
  access_granted: 'commerce', access_denied: 'commerce',
  wallet: 'web3', transaction: 'web3', contract_action: 'web3',
  // agent legacy
  agent_task: 'agent', agent_decision: 'agent', a2h_interaction: 'agent',
  // agent lifecycle
  agent_registered: 'agent', agent_updated: 'agent', agent_authorized: 'agent',
  agent_deauthorized: 'agent', agent_capability_granted: 'agent', agent_capability_revoked: 'agent',
  agent_task_created: 'agent', agent_task_decomposed: 'agent', agent_task_started: 'agent',
  agent_task_completed: 'agent', agent_task_failed: 'agent', agent_tool_called: 'agent',
  agent_resource_requested: 'agent', agent_delegated_task: 'agent', agent_subagent_spawned: 'agent',
  agent_policy_evaluated: 'agent', agent_handoff: 'agent', agent_escalated_to_human: 'agent',
  agent_outcome_recorded: 'agent',
  // x402 legacy
  x402_payment: 'commerce',
  // x402 lifecycle
  x402_resource_requested: 'commerce', x402_payment_required: 'commerce',
  x402_quote_received: 'commerce', x402_authorization_requested: 'commerce',
  x402_authorization_resolved: 'commerce', x402_payment_intent_created: 'commerce',
  x402_payment_submitted: 'commerce', x402_payment_settled: 'commerce',
  x402_payment_failed: 'commerce', x402_payment_timeout: 'commerce',
  x402_receipt_verified: 'commerce', x402_access_granted: 'commerce',
  x402_access_denied: 'commerce', x402_refund_or_reversal: 'commerce',
  // reward enablement (A6)
  reward_action_queued: 'commerce', reward_proof_generated: 'commerce',
  reward_delivered: 'commerce', reward_claim_submitted: 'commerce',
};

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

export interface PageContext {
  url: string;
  path: string;
  title: string;
  referrer: string;
  search?: string;
  hash?: string;
}

export interface DeviceContext {
  type: 'desktop' | 'mobile' | 'tablet';
  os?: string;
  osVersion?: string;
  browser?: string;
  browserVersion?: string;
  screenWidth?: number;
  screenHeight?: number;
  viewportWidth?: number;
  viewportHeight?: number;
  pixelRatio?: number;
  language?: string;
}

export interface CampaignContext {
  source?: string;
  medium?: string;
  campaign?: string;
  content?: string;
  term?: string;
  clickId?: string;
  referrerDomain?: string;
  referrerType?: 'direct' | 'organic' | 'paid' | 'social' | 'email' | 'referral' | 'unknown';
}

export interface LibraryContext {
  name: string;
  version: string;
}

// ---------------------------------------------------------------------------
// Multi-actor journey v1 — optional event-completeness fields.
// All optional → existing SDKs keep working unchanged.
// ---------------------------------------------------------------------------

export type { ActorKind };

export interface ImpressionRecord {
  surface: string;          // e.g. 'home_feed', 'product_grid'
  itemId: string;
  position?: number;
  viewableMs?: number;
  viewportPct?: number;
  clicked?: boolean;
}

export interface IntentHint {
  predictedGoal: string;
  confidence: number;       // 0..1
}

export interface FrictionRecord {
  errorCode?: string;
  retryCount?: number;
  latencyMs?: number;
  [k: string]: string | number | undefined;
}

export interface EngagementRecord {
  depth?: number;
  dwellMs?: number;
  scrollPct?: number;
  [k: string]: number | undefined;
}

export interface DataQualityRecord {
  completeness?: number;    // 0..1
  freshness?: number;       // 0..1
  sourceTrust?: number;     // 0..1
  [k: string]: number | undefined;
}


// ---------------------------------------------------------------------------
// Cross-device journey continuity
// ---------------------------------------------------------------------------

export type JourneyLifecycleEventType =
  | 'journey_started'
  | 'journey_paused'
  | 'journey_resumed'
  | 'journey_continued'
  | 'journey_completed'
  | 'journey_abandoned'
  | 'journey_checkpoint';

export type JourneyStatus =
  | 'started'
  | 'paused'
  | 'resumed'
  | 'continued'
  | 'completed'
  | 'abandoned'
  | 'checkpoint';

export interface JourneyAttributionContext {
  source?: string;
  medium?: string;
  campaign?: string;
  content?: string;
  term?: string;
  clickId?: string;
  referrer?: string;
  deepLink?: string;
  [key: string]: unknown;
}

export interface JourneyPayload {
  journeyId?: string;
  journeyName?: string;
  journeyType?: string;
  stepId?: string;
  stepName?: string;
  previousStepId?: string;
  nextExpectedStepId?: string;
  journeyStatus?: JourneyStatus;
  pauseReason?: string;
  resumeReason?: string;
  completionReason?: string;
  abandonmentReason?: string;
  handoffFromSessionId?: string;
  handoffFromDeviceId?: string;
  handoffToDeviceId?: string;
  handoffLatencyMs?: number;
  confidence?: number;
  confidenceSignals?: string[];
  sourceSessionId?: string;
  sourceAnonymousId?: string;
  sourceUserId?: string;
  targetSessionId?: string;
  targetAnonymousId?: string;
  targetUserId?: string;
  campaignAttribution?: JourneyAttributionContext;
  referrerAttribution?: JourneyAttributionContext;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface JourneyLifecycleEvent extends BaseEvent {
  type: JourneyLifecycleEventType;
  properties: JourneyPayload;
}

export interface JourneyContext {
  journeyId?: string;
  journeyName?: string;
  journeyType?: string;
  currentStepId?: string;
  currentStepName?: string;
  status?: JourneyStatus;
  lastLifecycleEvent?: JourneyLifecycleEventType;
  confidence?: number;
  confidenceSignals?: string[];
}

export interface EventContext {
  library: LibraryContext;
  page?: PageContext;
  device?: DeviceContext;
  campaign?: CampaignContext;
  fingerprint?: { id: string };
  ip?: string;
  locale?: string;
  timezone?: string;
  userAgent?: string;
  consent?: ConsentState;
  provenance?: Provenance;
  journey?: JourneyContext;
  /** Optional tenant/org binding for B2B + hybrid companies. */
  tenantId?: string;
  orgId?: string;

  // -- multi-actor journey v1 ------------------------------------------------
  /** Resolved or SDK-provided actor performing the event. */
  actorId?: string;
  actorKind?: ActorKind;
  /** When an actor acts on behalf of another (e.g. agent → human owner). */
  beneficiaryActorId?: string;

  /** Active delegation grant covering this action, if any. */
  delegationId?: string;
  delegationScope?: string[];

  /** Identity-stitching metadata. */
  identityConfidence?: number;          // 0..1
  identitySignals?: string[];           // e.g. ['login','wallet_match','cookie']

  /** Impressions seen but not necessarily clicked (exposure-aware attribution). */
  impressions?: ImpressionRecord[];

  // -- A6: reward enablement -------------------------------------------------
  /** Campaign this event is attributed to for reward eligibility evaluation. */
  rewardCampaignId?: string;
  /** Rule within the campaign matched for this event. */
  rewardRuleId?: string;
  /** Idempotency key for the reward eligibility decision. */
  rewardIdempotencyKey?: string;
  /** Wallet address of the reward recipient (EVM or other VM). */
  rewardWalletAddress?: string;
  /** Attribution result ID from the attribution service. */
  attributionResultId?: string;
  /** Fraud decision ID from the fraud service. */
  fraudDecisionId?: string;
  /** Consent snapshot ID at the time of event. */
  consentSnapshotId?: string;
}

/** The canonical event envelope every SDK emits. */
export interface BaseEvent {
  id: string;
  type: EventType;
  timestamp: string;
  sessionId: string;
  anonymousId: string;
  userId?: string;
  properties?: Record<string, unknown>;
  context: EventContext;
}

/** Ingestion batch envelope POSTed to /v1/batch. */
export interface BatchPayload {
  batch: BaseEvent[];
  sentAt: string;
  context?: { library: LibraryContext };
}
