export type CustomerLifecycleStage =
  | 'signed'
  | 'implementing'
  | 'activated'
  | 'value_proven'
  | 'adopting'
  | 'expanding'
  | 'renewal_ready'
  | 'at_risk'
  | 'churned';

export type CustomerSuccessTriggerType =
  | 'value_proven'
  | 'expansion_ready'
  | 'renewal_risk'
  | 'playbook_underused'
  | 'integration_gap'
  | 'outcome_gap'
  | 'executive_proof_ready'
  | 'package_fit_detected'
  | 'implementation_intervention_needed';

export type CustomerSuccessSeverity = 'low' | 'medium' | 'high' | 'critical';
export type CustomerSuccessStatus = 'open' | 'in_progress' | 'resolved' | 'dismissed';

export interface CustomerSuccessAccount {
  readonly account_id: string;
  readonly tenant_id: string;
  readonly account_name?: string;
  readonly lifecycle_stage: CustomerLifecycleStage;
  readonly assigned_csm_id?: string;
  readonly assigned_account_exec_id?: string;
  readonly package_id?: string;
  readonly plan_tier?: string;
  readonly renewal_date?: string;
  readonly health_score: number;
  readonly expansion_score: number;
  readonly renewal_risk_score: number;
  readonly observed_value_total: number;
  readonly pending_value_total: number;
  readonly outcome_capture_rate: number;
  readonly playbook_adoption_rate: number;
  readonly integration_adoption_rate: number;
  readonly last_value_review_at?: string;
  readonly next_recommended_action?: string;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface CustomerSuccessTrigger {
  readonly trigger_id: string;
  readonly tenant_id: string;
  readonly trigger_type: CustomerSuccessTriggerType;
  readonly severity: CustomerSuccessSeverity;
  readonly reason: string;
  readonly supporting_metrics: Record<string, unknown>;
  readonly recommended_action: string;
  readonly owner_id?: string;
  readonly status: CustomerSuccessStatus;
  readonly created_at: string;
  readonly resolved_at?: string;
}

export type ExpansionOpportunityType =
  | 'module_expansion'
  | 'usage_expansion'
  | 'integration_expansion'
  | 'services_expansion'
  | 'deployment_expansion'
  | 'audit_export_expansion'
  | 'enterprise_upgrade'
  | 'government_planning_path';
export type ExpansionOpportunityStatus = 'open' | 'in_progress' | 'won' | 'lost' | 'dismissed';

export interface ExpansionOpportunity {
  readonly opportunity_id: string;
  readonly tenant_id: string;
  readonly opportunity_type: ExpansionOpportunityType;
  readonly recommended_package_id?: string;
  readonly recommended_module?: string;
  readonly supporting_metrics: Record<string, unknown>;
  readonly estimated_revenue_potential?: number;
  readonly confidence: number;
  readonly recommended_sales_motion: string;
  readonly next_step: string;
  readonly status: ExpansionOpportunityStatus;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface RenewalRisk {
  readonly renewal_risk_id: string;
  readonly tenant_id: string;
  readonly risk_score: number;
  readonly primary_failure_mode: string;
  readonly supporting_metrics: Record<string, unknown>;
  readonly recommended_intervention: string;
  readonly owner_id?: string;
  readonly renewal_date?: string;
  readonly status: CustomerSuccessStatus;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface ExecutiveBusinessReview {
  readonly ebr_id: string;
  readonly tenant_id: string;
  readonly time_window: Record<string, string>;
  readonly account_summary: Record<string, unknown>;
  readonly package_summary: Record<string, unknown>;
  readonly implementation_summary: Record<string, unknown>;
  readonly usage_summary: Record<string, unknown>;
  readonly outcome_ledger_summary: Record<string, unknown>;
  readonly playbook_roi_summary: Record<string, unknown>;
  readonly recommendation_family_summary: Record<string, unknown>;
  readonly integration_summary: Record<string, unknown>;
  readonly value_created_summary: Record<string, unknown>;
  readonly open_gaps: readonly string[];
  readonly recommended_next_modules: readonly string[];
  readonly expansion_opportunities: readonly ExpansionOpportunity[];
  readonly next_90_day_plan: readonly string[];
  readonly generated_at: string;
}

export interface AccountPlan {
  readonly account_plan_id: string;
  readonly tenant_id: string;
  readonly current_package_id?: string;
  readonly target_package_id?: string;
  readonly current_arr_estimate?: number;
  readonly expansion_arr_estimate?: number;
  readonly renewal_date?: string;
  readonly strategic_objectives: readonly string[];
  readonly success_criteria: readonly string[];
  readonly risks: readonly string[];
  readonly opportunities: readonly string[];
  readonly next_actions: readonly AccountNextAction[];
  readonly created_at: string;
  readonly updated_at: string;
}

export type AccountNextActionOwnerType = 'olympus' | 'tenant' | 'shared';
export type AccountNextActionStatus = 'open' | 'in_progress' | 'completed' | 'dismissed';
export type AccountNextActionSource =
  | 'onboarding'
  | 'outcome_ledger'
  | 'playbook_roi'
  | 'integration_health'
  | 'package_fit'
  | 'renewal_risk'
  | 'expansion_opportunity'
  | 'manual';

export interface AccountNextAction {
  readonly action_id: string;
  readonly tenant_id: string;
  readonly title: string;
  readonly description: string;
  readonly owner_type: AccountNextActionOwnerType;
  readonly owner_id?: string;
  readonly due_date?: string;
  readonly status: AccountNextActionStatus;
  readonly source: AccountNextActionSource;
  readonly created_at: string;
  readonly completed_at?: string;
}
