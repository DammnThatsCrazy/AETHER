// =============================================================================
// Aether Suggestion Intelligence — OODA lifecycle contracts
//
// Canonical source of truth for the Suggestion entity and all OODA phase
// transitions. All surfaces (Kyber operator, Aether tenant, Noesis) derive
// their types from here. Adapters (notification, recommendation, data_quality,
// sdk_health, sdk_drift, graph, profile360, governance, reliability) must map
// upstream signals into these contracts before persisting.
// =============================================================================

import type { EvidenceRef, TimeRangeFilter, PageRequest } from './operational-intelligence';
import type { EntityRef } from './entities';

// ---------------------------------------------------------------------------
// Core enumerations
// ---------------------------------------------------------------------------

export type OodaPhase =
  | 'observe'
  | 'orient'
  | 'suggest'
  | 'review'
  | 'act'
  | 'measure'
  | 'learn'
  | 'closed';

export type SuggestionStatus =
  | 'detected'
  | 'oriented'
  | 'suggested'
  | 'review_required'
  | 'approved'
  | 'rejected'
  | 'suppressed'
  | 'executing'
  | 'executed'
  | 'delivered'
  | 'measured'
  | 'learned'
  | 'closed'
  | 'expired'
  | 'failed';

export type SuggestionClass =
  | 'customer_success'
  | 'data_quality'
  | 'sdk_health'
  | 'sdk_drift'
  | 'identity'
  | 'graph_health'
  | 'profile360'
  | 'campaign'
  | 'retargeting'
  | 'revenue'
  | 'reliability'
  | 'security'
  | 'governance'
  | 'agent_operations'
  | 'notification'
  | 'investigation'
  | 'general_intelligence';

export type SuggestionSource =
  | 'noesis'
  | 'model'
  | 'rule'
  | 'agent'
  | 'data_quality'
  | 'sdk_health'
  | 'sdk_drift'
  | 'graph'
  | 'profile360'
  | 'recommendation_engine'
  | 'notification_intelligence'
  | 'reliability'
  | 'governance'
  | 'operator'
  | 'system';

export type SuggestionPriority = 'P0' | 'P1' | 'P2' | 'P3' | 'info';

export type SuggestionOutcomeStatus =
  | 'accepted'
  | 'rejected'
  | 'ignored'
  | 'expired'
  | 'executed'
  | 'failed'
  | 'helpful'
  | 'not_helpful'
  | 'unknown';

// ---------------------------------------------------------------------------
// Event names (extend IntelligenceEventName in operational-intelligence.ts)
// ---------------------------------------------------------------------------

export type SuggestionEventName =
  | 'suggestion.detected'
  | 'suggestion.oriented'
  | 'suggestion.created'
  | 'suggestion.review_required'
  | 'suggestion.approved'
  | 'suggestion.rejected'
  | 'suggestion.suppressed'
  | 'suggestion.executing'
  | 'suggestion.executed'
  | 'suggestion.delivered'
  | 'suggestion.outcome_recorded'
  | 'suggestion.closed'
  | 'suggestion.failed'
  | 'suggestion.expired';

// ---------------------------------------------------------------------------
// Supporting value objects
// ---------------------------------------------------------------------------

export interface SuggestionSubject {
  kind:
    | 'entity'
    | 'tenant'
    | 'organization'
    | 'graph'
    | 'profile'
    | 'journey'
    | 'campaign'
    | 'sdk'
    | 'provider'
    | 'agent'
    | 'alert'
    | 'investigation'
    | 'system';
  id: string;
  displayName?: string;
  entityRef?: EntityRef;
}

export interface SuggestionPolicyDecision {
  decisionId: string;
  allowed: boolean;
  requiresApproval: boolean;
  policies: string[];
  obligations: string[];
  explanation?: string;
  evaluatedAt: string;
}

export interface SuggestionOutcome {
  status: SuggestionOutcomeStatus;
  measuredImpact?: Record<string, unknown>;
  operatorNotes?: string;
  tenantFeedback?: string;
  createdAt: string;
  createdBy?: string;
}

export interface SuggestionAuditEvent {
  id: string;
  action: string;
  actorId?: string;
  actorKind: 'system' | 'operator' | 'tenant_user' | 'agent';
  fromStatus?: SuggestionStatus;
  toStatus?: SuggestionStatus;
  metadata?: Record<string, unknown>;
  timestamp: string;
}

export interface SourceRef {
  service: string;
  id: string;
  version?: string;
}

export interface GraphRef {
  kind: string;
  id: string;
  label?: string;
}

// ---------------------------------------------------------------------------
// Canonical Suggestion entity
// ---------------------------------------------------------------------------

export interface Suggestion {
  id: string;
  tenantId: string;
  orgId?: string;

  subject: SuggestionSubject;
  source: SuggestionSource;
  sourceRef?: SourceRef;

  oodaPhase: OodaPhase;
  class: SuggestionClass;
  priority: SuggestionPriority;
  status: SuggestionStatus;

  title: string;
  summary: string;
  what: string;
  why: string;
  impact: string;
  recommendedAction?: string;
  expectedOutcome?: string;

  confidenceScore: number;
  impactScore?: number;
  urgencyScore?: number;
  riskScore?: number;
  evidenceQualityScore?: number;
  tenantValueScore?: number;
  reversibilityScore?: number;
  priorityScore?: number;
  reversible?: boolean;

  requiresApproval: boolean;
  executionEligible: boolean;
  deliveryEligible: boolean;

  evidence: EvidenceRef[];
  lineageEventIds: string[];
  graphRefs?: GraphRef[];
  profileRefs?: EntityRef[];
  journeyRefs?: EntityRef[];

  policyDecision?: SuggestionPolicyDecision;
  auditTrail: SuggestionAuditEvent[];
  outcome?: SuggestionOutcome;

  expiresAt?: string;
  createdAt: string;
  updatedAt: string;
  reviewedAt?: string;
  reviewedBy?: string;
  closedAt?: string;
}

// ---------------------------------------------------------------------------
// Tenant-safe projection (no operator-internal fields)
// ---------------------------------------------------------------------------

export interface TenantSafeSuggestion {
  id: string;
  tenantId: string;
  subject: Pick<SuggestionSubject, 'kind' | 'id' | 'displayName'>;
  oodaPhase: OodaPhase;
  class: SuggestionClass;
  priority: SuggestionPriority;
  status: SuggestionStatus;
  title: string;
  summary: string;
  what: string;
  why: string;
  impact: string;
  recommendedAction?: string;
  expectedOutcome?: string;
  confidenceScore: number;
  deliveryEligible: boolean;
  outcome?: Pick<SuggestionOutcome, 'status' | 'tenantFeedback' | 'createdAt'>;
  expiresAt?: string;
  createdAt: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Query and summary contracts
// ---------------------------------------------------------------------------

export interface SuggestionQueryRequest {
  tenantId: string;
  orgId?: string;
  statuses?: SuggestionStatus[];
  classes?: SuggestionClass[];
  priorities?: SuggestionPriority[];
  sources?: SuggestionSource[];
  subject?: Pick<SuggestionSubject, 'kind' | 'id'>;
  time?: TimeRangeFilter;
  minPriorityScore?: number;
  includeClosed?: boolean;
  page?: PageRequest;
}

export interface SuggestionSummary {
  total: number;
  open: number;
  reviewRequired: number;
  approved: number;
  executed: number;
  failed: number;
  closed: number;
  byClass: Record<string, number>;
  byPriority: Record<string, number>;
  byStatus: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Action request payloads
// ---------------------------------------------------------------------------

export interface SuggestionApproveRequest {
  actorId?: string;
  notes?: string;
}

export interface SuggestionRejectRequest {
  actorId?: string;
  reason: string;
  notes?: string;
}

export interface SuggestionSuppressRequest {
  actorId?: string;
  reason: string;
  suppressDurationHours?: number;
  notes?: string;
}

export interface SuggestionFeedbackRequest {
  status: SuggestionOutcomeStatus;
  tenantFeedback?: string;
}

export interface SuggestionOutcomeRequest {
  status: SuggestionOutcomeStatus;
  measuredImpact?: Record<string, unknown>;
  operatorNotes?: string;
  tenantFeedback?: string;
  createdBy?: string;
}
