export type ContractStatus = 'draft' | 'active' | 'pending_signature' | 'expired' | 'cancelled' | 'renewal_pending';
export type BillingModel = 'flat_subscription' | 'usage_based' | 'hybrid' | 'enterprise_contract' | 'value_based' | 'pilot';
export type BillingPeriod = 'monthly' | 'quarterly' | 'annual' | 'custom';
export type EntitlementResetPeriod = 'monthly' | 'quarterly' | 'annual' | 'never';
export type UsageMeteringEventType = 'event_ingested' | 'entity_resolved' | 'graph_operation' | 'profile_query' | 'recommendation_generated' | 'decision_recorded' | 'action_logged' | 'action_dispatched' | 'outcome_observed' | 'playbook_run' | 'audit_export_generated' | 'integration_delivery' | 'premium_connector_used' | 'deployment_mode_active' | 'managed_workflow_triggered' | 'value_created';
export type InvoicePreviewStatus = 'draft' | 'review_ready' | 'approved' | 'exported';
export type ValueCreatedSourceType = 'outcome' | 'playbook' | 'recommendation_family' | 'integration_action' | 'manual_adjustment';
export type ValueCreatedType = 'retained_revenue' | 'expansion_revenue' | 'avoided_loss' | 'campaign_waste_reduced' | 'operational_savings' | 'agent_failure_cost_reduced' | 'manual_review_savings';
export type RevenueLeakageType = 'overage_not_priced' | 'premium_module_unpriced' | 'connector_unpriced' | 'value_created_unmonetized' | 'deployment_underpriced' | 'services_unbilled' | 'audit_exports_unpriced';
export type RevenueLeakageSeverity = 'low' | 'medium' | 'high' | 'critical';

export interface TenantContractProfile {
  contract_profile_id: string;
  tenant_id: string;
  account_id?: string | null;
  package_id?: string | null;
  plan_tier?: string | null;
  contract_status: ContractStatus;
  billing_model: BillingModel;
  contract_start_date?: string | null;
  contract_end_date?: string | null;
  renewal_date?: string | null;
  billing_period: BillingPeriod;
  currency: string;
  payment_terms?: string | null;
  internal_notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TenantEntitlement {
  entitlement_id: string;
  tenant_id: string;
  package_id?: string | null;
  feature_key: string;
  enabled: boolean;
  included_quantity?: number | null;
  overage_allowed: boolean;
  overage_unit_price_notes?: string | null;
  reset_period: EntitlementResetPeriod;
  created_at: string;
  updated_at: string;
}

export interface UsageMeteringEvent {
  metering_event_id: string;
  tenant_id: string;
  event_type: UsageMeteringEventType;
  quantity: number;
  source_id?: string | null;
  source_type?: string | null;
  billable: boolean;
  package_id?: string | null;
  occurred_at: string;
  metadata?: Record<string, unknown> | null;
}

export interface BillableUsageSummary {
  tenant_id: string;
  billing_period_start: string;
  billing_period_end: string;
  package_id?: string | null;
  usage_by_dimension: Record<string, number>;
  included_usage_by_dimension: Record<string, number>;
  overage_by_dimension: Record<string, number>;
  billable_events_count: number;
  non_billable_events_count: number;
  estimated_charges_notes?: string | null;
  generated_at: string;
}

export interface InvoicePreviewLineItem {
  line_item_id: string;
  label: string;
  dimension_key: string;
  quantity: number;
  included_quantity?: number | null;
  overage_quantity?: number | null;
  unit_price_notes?: string | null;
  amount_notes?: string | null;
  source_event_ids?: string[] | null;
}

export interface InvoicePreview {
  invoice_preview_id: string;
  tenant_id: string;
  contract_profile_id?: string | null;
  billing_period_start: string;
  billing_period_end: string;
  line_items: InvoicePreviewLineItem[];
  subtotal_notes?: string | null;
  value_created_summary?: Record<string, unknown> | null;
  status: InvoicePreviewStatus;
  generated_at: string;
  updated_at: string;
}

export interface ValueCreatedEvent {
  value_event_id: string;
  tenant_id: string;
  source_type: ValueCreatedSourceType;
  source_id: string;
  value_type: ValueCreatedType;
  value_amount?: number | null;
  currency?: string | null;
  confidence?: number | null;
  attribution_notes?: string | null;
  billable_under_contract: boolean;
  occurred_at: string;
}

export interface RevenueLeakageSignal {
  signal_id: string;
  tenant_id: string;
  leakage_type: RevenueLeakageType;
  reason: string;
  supporting_metrics: Record<string, unknown>;
  severity: RevenueLeakageSeverity;
  recommended_action: string;
  created_at: string;
  resolved_at?: string | null;
}
