/**
 * Action runtime contracts.
 *
 * These are transport/domain contracts only. They do not grant authority,
 * perform an action, or imply production readiness. A runtime must evaluate
 * permission, policy, consent, capability, and evidence at the execution
 * boundary immediately before dispatch.
 */
import type {
  ApprovalLevel,
  CandidateAction,
  DecisionRecord as RecommendationDecisionRecord,
  RecommendationEvidence,
} from './decision-outcome-intelligence';
import type { GraphDecisionRecord, MutationRecord } from './graph-mutation';
import type { EpistemicStatus } from './epistemic-status';
import type {
  PermissionAction,
  PermissionScope,
  PolicyDecision,
  SecurityAuditEvent,
} from './security-governance';
import type { AIInvocationObserved } from './ai-execution';

export type RuntimeDecisionStatus =
  | 'proposed' | 'approval_required' | 'approved' | 'rejected'
  | 'expired' | 'executing' | 'completed' | 'cancelled';

export type ActionExecutionStatus =
  | 'queued' | 'running' | 'partial' | 'completed' | 'failed'
  | 'cancelled' | 'rollback_pending' | 'rolled_back' | 'rollback_failed';

export interface RuntimePermissionRequirement {
  readonly domain: 'actions' | 'dispatches' | 'decisions' | 'governance' | string;
  readonly action: PermissionAction;
  readonly scope: PermissionScope;
  readonly approval_level: ApprovalLevel;
  readonly reason?: string;
}

export interface ApprovalReference {
  readonly approval_id: string;
  readonly approver_id: string;
  readonly approval_level: ApprovalLevel;
  readonly approved_at: string;
  readonly decision_id: string;
  readonly expires_at?: string;
}

export interface ActionEvidenceLink {
  readonly evidence_id: string;
  readonly kind: 'recommendation' | 'graph' | 'policy' | 'consent' | 'external' | 'audit' | 'other';
  readonly ref: string;
  readonly epistemic_status: EpistemicStatus;
  readonly summary?: string;
}

export interface ImpactPreview {
  readonly summary: string;
  readonly affected_entities: number;
  readonly affected_entity_refs?: readonly string[];
  readonly estimated_value?: number;
  readonly currency?: string;
  readonly risk_level: 'low' | 'medium' | 'high' | 'unknown';
  readonly reversible: boolean;
  readonly generated_at: string;
  readonly graph_snapshot_id?: string;
  readonly limitations?: readonly string[];
}

export interface RollbackMetadata {
  readonly supported: boolean;
  readonly plan_ref?: string;
  readonly inverse_action_type?: string;
  readonly rollback_execution_id?: string;
  readonly requested_at?: string;
  readonly completed_at?: string;
  readonly repair_required?: boolean;
  readonly limitation?: string;
}

/** Constraints that must remain explicit for any external side effect. */
export interface ExternalExecutionConstraints {
  readonly external: boolean;
  readonly target_type?: string;
  readonly destination_ref?: string;
  readonly tenant_isolation_key: string;
  readonly consent_required: boolean;
  readonly consent_ref?: string;
  readonly idempotency_key: string;
  readonly environment: 'development' | 'staging' | 'production' | 'unknown';
  readonly production_ready: false;
}

export interface CapabilityState {
  readonly capability_key: string;
  readonly entitled: boolean;
  readonly permitted: boolean;
  readonly ready: boolean;
  readonly missing_requirements: readonly string[];
  readonly evaluated_at: string;
  readonly evidence_refs?: readonly string[];
}

export interface CapabilityMatrix {
  readonly tenant_id: string;
  readonly action_key: string;
  readonly states: readonly CapabilityState[];
  readonly evaluated_at: string;
}

export interface ActionRuntimeDecision {
  readonly decision_id: string;
  readonly tenant_id: string;
  readonly recommendation_id?: string;
  readonly action: CandidateAction;
  readonly status: RuntimeDecisionStatus;
  readonly actor_id: string;
  readonly required_permission: RuntimePermissionRequirement;
  readonly approval?: ApprovalReference;
  readonly evidence: readonly (RecommendationEvidence | ActionEvidenceLink)[];
  readonly impact_preview: ImpactPreview;
  readonly capability_matrix: CapabilityMatrix;
  readonly graph_decision_ref?: string;
  readonly created_at: string;
  readonly expires_at?: string;
}

export interface ActionExecutionLinks {
  readonly decision_id: string;
  readonly recommendation_id?: string;
  readonly evidence_refs: readonly string[];
  readonly audit_event_refs: readonly string[];
  readonly outcome_refs: readonly string[];
  readonly mutation_refs?: readonly string[];
  readonly ai_invocation_refs?: readonly string[];
}

export interface ActionRuntimeExecution {
  readonly execution_id: string;
  readonly action_id: string;
  readonly tenant_id: string;
  readonly decision_id: string;
  readonly status: ActionExecutionStatus;
  readonly links: ActionExecutionLinks;
  readonly external_constraints: ExternalExecutionConstraints;
  readonly rollback: RollbackMetadata;
  readonly started_at?: string;
  readonly completed_at?: string;
  readonly error_code?: string;
}

export type RuntimeTransitionErrorCode =
  | 'unauthorized' | 'approval_required' | 'invalid_transition'
  | 'fake_rollback' | 'missing_linkage';

export class ActionRuntimeTransitionError extends Error {
  readonly code: RuntimeTransitionErrorCode;
  constructor(code: RuntimeTransitionErrorCode, message: string) {
    super(message);
    this.name = 'ActionRuntimeTransitionError';
    this.code = code;
  }
}

export interface TransitionContext {
  readonly authorized: boolean;
  readonly approval_present?: boolean;
  readonly rollback_supported?: boolean;
  readonly rollback_inverse_applied?: boolean;
}

const transitions: Readonly<Record<ActionExecutionStatus, readonly ActionExecutionStatus[]>> = {
  queued: ['running', 'cancelled'], running: ['partial', 'completed', 'failed', 'cancelled', 'rollback_pending'],
  partial: ['running', 'completed', 'failed', 'cancelled', 'rollback_pending'], completed: ['rollback_pending'],
  failed: ['rollback_pending'], cancelled: [], rollback_pending: ['rolled_back', 'rollback_failed'],
  rolled_back: [], rollback_failed: ['rollback_pending'],
};

/** Pure guard: returns the next status or rejects an unsafe transition. */
export function transitionActionExecution(
  current: ActionExecutionStatus,
  next: ActionExecutionStatus,
  context: TransitionContext,
): ActionExecutionStatus {
  if (!context.authorized) throw new ActionRuntimeTransitionError('unauthorized', 'execution transition is unauthorized');
  if (next === 'running' && !context.approval_present) throw new ActionRuntimeTransitionError('approval_required', 'approval is required before execution');
  if (!transitions[current].includes(next)) throw new ActionRuntimeTransitionError('invalid_transition', `cannot transition from ${current} to ${next}`);
  if (next === 'rollback_pending' && context.rollback_supported !== true) throw new ActionRuntimeTransitionError('fake_rollback', 'rollback is not supported by the action');
  if (next === 'rolled_back' && context.rollback_inverse_applied !== true) throw new ActionRuntimeTransitionError('fake_rollback', 'rollback cannot be marked complete without applying the inverse');
  return next;
}

export type ActionRuntimeSourceLinks = {
  decision?: RecommendationDecisionRecord | GraphDecisionRecord;
  mutation?: MutationRecord;
  audit?: SecurityAuditEvent;
  policy?: PolicyDecision;
  ai_invocation?: AIInvocationObserved;
};
