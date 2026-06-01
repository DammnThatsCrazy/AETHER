// =============================================================================
// Aether Shared — Decision & Outcome Intelligence Contracts
// =============================================================================

export type RecommendationType =
  | 'retention'
  | 'growth'
  | 'risk_mitigation'
  | 'journey_optimization'
  | 'fraud_review'
  | 'commerce'
  | 'agent_assist'
  | 'custom';

export type ApprovalLevel = 'none' | 'standard' | 'elevated' | 'critical';
export type DecisionStatus = 'approved' | 'rejected' | 'deferred' | 'escalated';
export type ActionActorType = 'human' | 'system' | 'agent';
export type OutcomeLabel = 'success' | 'failure' | 'neutral';

export interface RecommendationEvidence {
  readonly evidence_id: string;
  readonly source_type: 'event' | 'entity' | 'edge' | 'profile_signal' | 'ml_prediction' | 'attribution_path' | 'economic_state' | 'policy';
  readonly source_id: string;
  readonly summary: string;
  readonly weight?: number;
  readonly observed_at?: string;
  readonly tenant_id?: string;
}

export interface RecommendationConfidence {
  readonly overall: number;
  readonly deterministic_rule_score: number;
  readonly ml_probability_score?: number;
  readonly graph_relevance_score?: number;
  readonly attribution_confidence?: number;
  readonly economic_expected_value?: number;
  readonly risk_penalty?: number;
  readonly freshness_penalty?: number;
  readonly governance_policy_penalty?: number;
  readonly model_version?: string;
}

export interface CandidateAction {
  readonly action_key: string;
  readonly action_type: string;
  readonly label: string;
  readonly description?: string;
  readonly system?: string;
  readonly integration?: string;
  readonly expected_outcome?: string;
  readonly expected_value?: number;
  readonly currency?: string;
  readonly downside_risk?: string;
  readonly confidence?: RecommendationConfidence;
  readonly requires_approval_level: ApprovalLevel;
  readonly policy_flags?: string[];
}

export interface Recommendation {
  readonly recommendation_id: string;
  readonly tenant_id: string;
  readonly entity_id?: string;
  readonly population_id?: string;
  readonly recommendation_type: RecommendationType;
  readonly recommended_action: CandidateAction;
  readonly candidate_actions: CandidateAction[];
  readonly confidence: RecommendationConfidence;
  readonly expected_outcome: string;
  readonly expected_value?: number;
  readonly downside_risk?: string;
  readonly evidence: RecommendationEvidence[];
  readonly graph_snapshot_id?: string;
  readonly computed_at: string;
  readonly required_approval_level: ApprovalLevel;
  readonly policy_governance_flags: string[];
  readonly data_freshness: { status: 'fresh' | 'stale' | 'unknown'; max_age_seconds?: number; oldest_evidence_at?: string };
  readonly status: 'generated' | 'viewed' | 'decided' | 'expired' | 'suppressed';
}

export interface DecisionRecord {
  readonly decision_id: string;
  readonly recommendation_id: string;
  readonly actor_id: string;
  readonly selected_action?: CandidateAction;
  readonly rejected_actions: CandidateAction[];
  readonly decision_status: DecisionStatus;
  readonly reason?: string;
  readonly comment?: string;
  readonly created_at: string;
  readonly tenant_id: string;
}

export interface ActionFeedback {
  readonly action_id: string;
  readonly decision_id: string;
  readonly action_type: string;
  readonly system?: string;
  readonly integration?: string;
  readonly status: 'planned' | 'queued' | 'executed' | 'failed' | 'cancelled';
  readonly actor_type: ActionActorType;
  readonly economic_payload?: Record<string, unknown>;
  readonly authorization_metadata?: Record<string, unknown>;
  readonly created_at: string;
  readonly tenant_id: string;
}

export interface OutcomeObservation {
  readonly outcome_id: string;
  readonly action_id: string;
  readonly recommendation_id: string;
  readonly entity_id?: string;
  readonly population_id?: string;
  readonly outcome_type: string;
  readonly value?: number;
  readonly currency?: string;
  readonly label: OutcomeLabel;
  readonly observed_window: { start: string; end: string };
  readonly computed_at: string;
  readonly confidence_delta: number;
  readonly tenant_id: string;
}

export interface PlaybookDefinition {
  readonly playbook_id: string;
  readonly tenant_id: string;
  readonly name: string;
  readonly description?: string;
  readonly trigger: string;
  readonly recommendation_types: RecommendationType[];
  readonly candidate_actions: CandidateAction[];
  readonly approval_level: ApprovalLevel;
  readonly enabled: boolean;
  readonly created_at: string;
  readonly updated_at?: string;
}

export interface PlaybookRun {
  readonly run_id: string;
  readonly playbook_id: string;
  readonly tenant_id: string;
  readonly status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  readonly recommendation_ids: string[];
  readonly started_at: string;
  readonly completed_at?: string;
  readonly summary?: Record<string, unknown>;
}
