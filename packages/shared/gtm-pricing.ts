import type { DeploymentModeName, SolutionPackageMarket } from './solution-packages';

export type PricingModelStatus = 'draft' | 'internal_ready' | 'sales_ready';
export type PricingDimensionUnit =
  | 'event'
  | 'entity'
  | 'graph_operation'
  | 'recommendation'
  | 'playbook_run'
  | 'action_dispatch'
  | 'outcome_observation'
  | 'audit_export'
  | 'integration'
  | 'deployment'
  | 'service_hour'
  | 'value_created';

export type GTMMaterialType =
  | 'one_pager'
  | 'sales_deck'
  | 'technical_brief'
  | 'security_brief'
  | 'audit_brief'
  | 'pricing_sheet'
  | 'roi_calculator'
  | 'procurement_faq'
  | 'pilot_proposal'
  | 'case_study_template'
  | 'objection_handling';

export type GTMMaterialStatus = 'draft' | 'internal_ready' | 'sales_ready';
export type GTMMarket = 'commercial' | 'enterprise' | 'regulated' | 'government_planning';

export interface PricingDimension {
  readonly dimension_key: string;
  readonly label: string;
  readonly description: string;
  readonly unit: PricingDimensionUnit;
  readonly metering_source: string;
  readonly included_in_tiers: readonly string[];
  readonly billable: boolean;
  readonly notes: string;
}

export interface PricingModel {
  readonly pricing_model_id: string;
  readonly name: string;
  readonly description: string;
  readonly base_platform_fee_notes: string;
  readonly usage_dimensions: readonly PricingDimension[];
  readonly premium_modules: readonly string[];
  readonly integration_pricing: readonly string[];
  readonly deployment_pricing: readonly string[];
  readonly services_pricing: readonly string[];
  readonly value_based_pricing_notes: readonly string[];
  readonly applicable_solution_packages: readonly string[];
  readonly status: PricingModelStatus;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface GTMMaterial {
  readonly material_id: string;
  readonly title: string;
  readonly material_type: GTMMaterialType;
  readonly solution_package_ids: readonly string[];
  readonly buyer_personas: readonly string[];
  readonly market: GTMMarket;
  readonly status: GTMMaterialStatus;
  readonly file_ref?: string;
  readonly content_blocks: readonly string[];
  readonly created_at: string;
  readonly updated_at: string;
}

export interface BuyerPersona {
  readonly persona_id: string;
  readonly title: string;
  readonly market: SolutionPackageMarket | GTMMarket;
  readonly pains: readonly string[];
  readonly desired_outcomes: readonly string[];
  readonly objections: readonly string[];
  readonly buying_triggers: readonly string[];
  readonly relevant_solution_packages: readonly string[];
  readonly recommended_collateral: readonly string[];
  readonly pricing_sensitivity: string;
  readonly proof_needed: readonly string[];
}

export interface ROICalculatorDefinition {
  readonly calculator_id: string;
  readonly solution_package_id: string;
  readonly inputs: readonly string[];
  readonly formulas: readonly string[];
  readonly outputs: readonly string[];
  readonly assumptions: readonly string[];
  readonly disclaimer: string;
  readonly status: GTMMaterialStatus;
}

export interface SalesReadinessPackage {
  readonly package_id: string;
  readonly package_name: string;
  readonly readiness_status: string;
  readonly ready_to_sell: boolean;
  readonly material_count: number;
  readonly persona_count: number;
  readonly roi_calculator_count: number;
  readonly missing_collateral: boolean;
  readonly missing_roi_calculator: boolean;
  readonly missing_audit_export_support: boolean;
  readonly missing_deployment_readiness: boolean;
  readonly recommended_next_sales_actions: readonly string[];
}

export interface SalesReadinessResponse {
  readonly items: readonly SalesReadinessPackage[];
  readonly ready_to_sell_count: number;
  readonly generated_at: string;
}
