// =============================================================================
// Customer Onboarding + Implementation Lifecycle Contracts
// Shared by Aether tenant UI, Kyber operator UI, and backend API payloads.
// =============================================================================

export type TenantActivationStage =
  | 'prospect'
  | 'signed'
  | 'tenant_created'
  | 'sdk_pending'
  | 'sdk_live'
  | 'event_mapping_in_progress'
  | 'graph_building'
  | 'graph_active'
  | 'recommendations_enabled'
  | 'playbooks_configured'
  | 'integrations_connected'
  | 'outcomes_capturing'
  | 'value_proven'
  | 'expansion_ready';

export type TenantImplementationStatus =
  | 'not_started'
  | 'in_progress'
  | 'blocked'
  | 'live'
  | 'value_proven'
  | 'expansion_ready';

export type ImplementationStepCategory =
  | 'contract'
  | 'tenant_setup'
  | 'sdk'
  | 'events'
  | 'identity'
  | 'graph'
  | 'intelligence'
  | 'playbooks'
  | 'integrations'
  | 'outcomes'
  | 'training'
  | 'expansion';

export type ImplementationStepStatus = 'not_started' | 'in_progress' | 'blocked' | 'completed' | 'skipped';
export type ImplementationOwnerType = 'olympus' | 'tenant' | 'shared';
export type ImplementationBlockerSeverity = 'low' | 'medium' | 'high' | 'critical';
export type ImplementationBlockerStatus = 'open' | 'in_progress' | 'resolved' | 'waived';

export interface ImplementationSuccessCriteria {
  required_events_received: string[];
  minimum_event_volume: number;
  graph_active: boolean;
  recommendations_generated: boolean;
  playbooks_configured: boolean;
  integrations_connected: boolean;
  outcomes_observed: boolean;
  value_threshold?: number | null;
  training_completed: boolean;
  go_live_approved: boolean;
}

export interface ImplementationStep {
  step_id: string;
  tenant_id: string;
  title: string;
  description: string;
  category: ImplementationStepCategory;
  status: ImplementationStepStatus;
  owner_type: ImplementationOwnerType;
  required: boolean;
  due_date?: string | null;
  completed_at?: string | null;
  evidence_refs: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
}

export interface ImplementationBlocker {
  blocker_id: string;
  tenant_id: string;
  step_id?: string | null;
  severity: ImplementationBlockerSeverity;
  title: string;
  description: string;
  owner_type: ImplementationOwnerType;
  status: ImplementationBlockerStatus;
  created_at: string;
  resolved_at?: string | null;
}

export interface TenantImplementationPlan {
  implementation_plan_id: string;
  tenant_id: string;
  package_id?: string | null;
  deployment_mode?: string | null;
  status: TenantImplementationStatus;
  onboarding_stage: TenantActivationStage;
  owner_id?: string | null;
  target_go_live_date?: string | null;
  required_steps: string[];
  blockers: string[];
  success_criteria: ImplementationSuccessCriteria;
  implementation_health_score: number;
  go_live_readiness_score: number;
  value_readiness_score: number;
  expansion_readiness_score: number;
  created_at: string;
  updated_at: string;
}

export interface OnboardingTemplate {
  template_id: string;
  package_id: string;
  name: string;
  description: string;
  default_steps: Array<Pick<ImplementationStep, 'title' | 'description' | 'category' | 'owner_type' | 'required'>>;
  default_success_criteria: ImplementationSuccessCriteria;
  recommended_playbooks: string[];
  recommended_integrations: string[];
  recommended_audit_exports: string[];
  created_at: string;
  updated_at: string;
}

export type CustomerSuccessTriggerType =
  | 'sdk_stalled'
  | 'event_mapping_stalled'
  | 'graph_not_activating'
  | 'recommendations_not_viewed'
  | 'decisions_not_recorded'
  | 'actions_not_logged'
  | 'outcomes_not_captured'
  | 'playbooks_unused'
  | 'integrations_failed'
  | 'value_proven'
  | 'expansion_ready';

export interface CustomerSuccessTrigger {
  trigger_id: string;
  tenant_id: string;
  trigger_type: CustomerSuccessTriggerType;
  severity: ImplementationBlockerSeverity;
  reason: string;
  supporting_metrics: Record<string, unknown>;
  recommended_action: string;
  created_at: string;
  resolved_at?: string | null;
}

export interface TenantOnboardingStatus {
  plan: TenantImplementationPlan;
  steps: ImplementationStep[];
  blockers: ImplementationBlocker[];
  customer_success_triggers?: CustomerSuccessTrigger[];
}
