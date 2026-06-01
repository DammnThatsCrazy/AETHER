// =============================================================================
// Aether Shared — Decision & Outcome Intelligence Contracts
// =============================================================================

export type RecommendationType =
  | 'retention'
  | 'growth'
  | 'expansion'
  | 'risk_mitigation'
  | 'attribution_optimization'
  | 'agent_governance'
  | 'rewards_optimization'
  | 'operational_failure'
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
  readonly trigger_snapshot?: Record<string, unknown>;
  readonly generated_recommendation_ids: string[];
  readonly decision_ids: string[];
  readonly action_ids: string[];
  readonly outcome_ids: string[];
  readonly started_at: string;
  readonly completed_at?: string;
  readonly summary?: Record<string, unknown>;
}

export interface PlaybookTemplate {
  readonly template_id: string;
  readonly name: string;
  readonly description: string;
  readonly category: RecommendationType | string;
  readonly trigger_schema: Record<string, unknown>;
  readonly default_candidate_actions: CandidateAction[];
  readonly default_approval_level: ApprovalLevel;
  readonly expected_outcome_types: string[];
  readonly recommended_integrations: string[];
  readonly created_at: string;
}

export interface PlaybookPerformance {
  readonly playbook_id: string;
  readonly tenant_id: string;
  readonly runs_total: number;
  readonly runs_completed: number;
  readonly recommendations_generated: number;
  readonly decisions_recorded: number;
  readonly actions_logged: number;
  readonly outcomes_observed: number;
  readonly success_count: number;
  readonly failure_count: number;
  readonly neutral_count: number;
  readonly expected_value_total: number;
  readonly observed_value_total: number;
  readonly pending_value_total: number;
  readonly outcome_capture_rate: number;
  readonly success_rate: number;
  readonly average_confidence_delta: number;
  readonly stale_run_count: number;
  readonly incomplete_run_count: number;
}

export interface PlaybookEvaluationResult {
  readonly playbook_id: string;
  readonly tenant_id: string;
  readonly matched: boolean;
  readonly trigger_matches: Record<string, boolean>;
  readonly generated_recommendation_ids: string[];
  readonly skipped_reason?: string;
  readonly evaluated_at: string;
}

export interface ActionTarget {
  readonly target_type: string;
  readonly label: string;
  readonly description?: string;
  readonly supported_action_types: string[];
  readonly requires_configuration: boolean;
  readonly supports_delivery_receipts: boolean;
  readonly supports_retries: boolean;
  readonly supports_cancellation: boolean;
  readonly approval_policy_notes?: string;
}

export interface ActionIntegrationConfig {
  readonly integration_config_id: string;
  readonly tenant_id: string;
  readonly target_type: string;
  readonly display_name: string;
  readonly enabled: boolean;
  readonly auth_type: 'oauth' | 'api_key' | 'webhook_secret' | 'none';
  readonly scopes: string[];
  readonly default_destination?: string;
  readonly policy_flags: string[];
  readonly created_at: string;
  readonly updated_at?: string;
}

export interface ActionDispatch {
  readonly dispatch_id: string;
  readonly tenant_id: string;
  readonly action_id: string;
  readonly decision_id: string;
  readonly recommendation_id: string;
  readonly target_type: string;
  readonly integration_config_id?: string;
  readonly status: 'queued' | 'sent' | 'delivered' | 'failed' | 'cancelled';
  readonly payload: Record<string, unknown>;
  readonly idempotency_key: string;
  readonly created_at: string;
  readonly updated_at?: string;
}

export interface ActionDeliveryReceipt {
  readonly receipt_id: string;
  readonly dispatch_id: string;
  readonly target_type: string;
  readonly external_id?: string;
  readonly external_url?: string;
  readonly delivered_at?: string;
  readonly failed_at?: string;
  readonly error_code?: string;
  readonly error_message?: string;
  readonly retry_count: number;
}

export interface RevenueMeteringEvent {
  readonly metering_event_id: string;
  readonly tenant_id: string;
  readonly event_type: 'action_dispatched' | 'integration_delivery' | 'integration_retry' | 'premium_connector_used' | 'managed_workflow_triggered';
  readonly action_id?: string;
  readonly dispatch_id?: string;
  readonly playbook_id?: string;
  readonly recommendation_id?: string;
  readonly quantity: number;
  readonly estimated_billable_value?: number;
  readonly created_at: string;
}

