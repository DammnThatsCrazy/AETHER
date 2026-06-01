export type SolutionPackageMarket = 'enterprise' | 'government' | 'regulated' | 'commercial' | 'government_planning';
export type PackageReadinessStatus = 'draft' | 'internal_ready' | 'pilot_ready' | 'sales_ready' | 'enterprise_ready' | 'government_planning';
export type DeploymentModeName = 'standard_saas' | 'enterprise_isolated_tenant' | 'regulated_cloud' | 'government_ready_planning' | 'self_hosted_future';
export type AuditExportFormat = 'json' | 'csv' | 'pdf_summary';
export type AuditExportStatus = 'queued' | 'generated' | 'failed' | 'expired';

export interface SolutionPackage {
  readonly package_id: string;
  readonly name: string;
  readonly market: SolutionPackageMarket | readonly SolutionPackageMarket[];
  readonly description: string;
  readonly buyer_personas: readonly string[];
  readonly use_cases: readonly string[];
  readonly included_modules: readonly string[];
  readonly required_feature_flags: readonly string[];
  readonly recommended_integrations: readonly string[];
  readonly required_audit_exports: readonly string[];
  readonly pricing_levers: readonly string[];
  readonly deployment_modes: readonly DeploymentModeName[];
  readonly readiness_status: PackageReadinessStatus;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface PackageReadinessReport {
  readonly package_id: string;
  readonly readiness_status: PackageReadinessStatus;
  readonly feature_completeness: string;
  readonly documentation_completeness: string;
  readonly test_coverage_status: string;
  readonly audit_export_support: string;
  readonly access_control_status: string;
  readonly integration_support_status: string;
  readonly deployment_support_status: string;
  readonly pricing_defined: boolean;
  readonly sales_collateral_status: string;
  readonly known_gaps: readonly string[];
  readonly recommended_next_actions: readonly string[];
  readonly generated_at: string;
}

export interface DeploymentMode {
  readonly deployment_mode_id: string;
  readonly name: DeploymentModeName;
  readonly description: string;
  readonly required_controls: readonly string[];
  readonly required_docs: readonly string[];
  readonly supported_features: readonly string[];
  readonly unsupported_features: readonly string[];
  readonly readiness_status: PackageReadinessStatus;
  readonly known_gaps: readonly string[];
}

export interface AuditExportType {
  readonly export_type: string;
  readonly label: string;
  readonly description: string;
  readonly included_records: readonly string[];
  readonly supported_formats: readonly AuditExportFormat[];
  readonly required_permissions: readonly string[];
  readonly retention_policy_notes: string;
}

export interface AuditExportRequest {
  readonly export_type: string;
  readonly tenant_id: string;
  readonly time_window: { readonly start: string; readonly end: string };
  readonly entity_id?: string;
  readonly recommendation_id?: string;
  readonly playbook_id?: string;
  readonly include_evidence: boolean;
  readonly include_dispatch_receipts: boolean;
  readonly include_confidence_deltas: boolean;
  readonly format: AuditExportFormat;
}

export interface AuditExportRecord {
  readonly export_id: string;
  readonly tenant_id: string;
  readonly export_type: string;
  readonly requested_by: string;
  readonly status: AuditExportStatus;
  readonly format: AuditExportFormat;
  readonly time_window: { readonly start: string; readonly end: string };
  readonly file_ref?: string;
  readonly integrity_hash: string;
  readonly generated_at: string;
  readonly expires_at: string;
  readonly error_message?: string;
}
