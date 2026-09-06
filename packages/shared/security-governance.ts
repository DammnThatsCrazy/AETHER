// =============================================================================
// Security, Compliance & Governance — Shared Contracts
//
// Canonical contracts for the Aether/Kyber governance control plane. These are
// security-review evidence primitives, NOT compliance certifications. No field
// in these contracts should ever carry a secret value (API keys, tokens,
// passwords, signing secrets) — backends sanitize metadata before persistence.
// =============================================================================

export type AccessRole =
  | 'tenant_owner'
  | 'tenant_admin'
  | 'tenant_operator'
  | 'tenant_analyst'
  | 'tenant_viewer'
  | 'tenant_billing_admin'
  | 'tenant_security_admin'
  | 'olympus_operator'
  | 'olympus_support'
  | 'olympus_admin'
  | 'olympus_security'
  | 'olympus_revops'
  | 'auditor'
  // Olympus workforce roles (Kyber workforce identity). Bound to a workforce
  // principal via olympus_role_bindings — never to an Aether tenant.
  | 'olympus_founder'
  | 'olympus_engineering'
  | 'olympus_product'
  | 'olympus_observer';

export type GovernanceDomain =
  | 'profile'
  | 'graph'
  | 'recommendations'
  | 'decisions'
  | 'actions'
  | 'dispatches'
  | 'outcomes'
  | 'playbooks'
  | 'integrations'
  | 'audit_exports'
  | 'billing'
  | 'onboarding'
  | 'customer_success'
  | 'kyber_admin'
  | 'security'
  | 'governance'
  | 'reliability'
  | 'data_quality'
  | 'data_exchange'
  // Kyber operating-plane domains. `kyber_workforce` covers operator identity,
  // devices and role administration; `kyber_tenant` covers scoped tenant
  // inspection (Tenant Mirror + raw tenant reads); `kyber_command` covers the
  // governed command plane. Kept distinct from `kyber_admin` (fleet/platform
  // aggregates) so read authority never implies workforce or command authority.
  | 'kyber_workforce'
  | 'kyber_tenant'
  | 'kyber_command';

export type PermissionAction =
  | 'read'
  | 'write'
  | 'approve'
  | 'dispatch'
  | 'export'
  | 'configure'
  | 'delete'
  | 'admin';

export type PermissionScope =
  | 'own_tenant'
  | 'assigned_tenant'
  | 'all_tenants_aggregate'
  | 'all_tenants_admin';

export interface PermissionGrant {
  permission_id: string;
  role: AccessRole;
  domain: GovernanceDomain;
  action: PermissionAction;
  scope: PermissionScope;
  created_at: string;
}

export type ActorType = 'tenant_user' | 'olympus_operator' | 'system' | 'agent';
export type PolicySeverity = 'info' | 'warning' | 'block';

export interface PolicyDecision {
  decision_id: string;
  tenant_id?: string | null;
  actor_id: string;
  actor_type: ActorType;
  policy_key: string;
  resource_type: string;
  resource_id?: string | null;
  action: string;
  allowed: boolean;
  reason: string;
  severity: PolicySeverity;
  required_action?: string | null;
  evaluated_at: string;
}

export type SecurityAuditOutcome = 'allowed' | 'blocked' | 'failed';

export interface SecurityAuditEvent {
  audit_event_id: string;
  tenant_id?: string | null;
  actor_id: string;
  actor_type: ActorType;
  event_type: string;
  resource_type: string;
  resource_id?: string | null;
  action: string;
  outcome: SecurityAuditOutcome;
  policy_decision_id?: string | null;
  ip_address?: string | null;
  user_agent?: string | null;
  metadata?: Record<string, unknown> | null;
  integrity_hash?: string | null;
  created_at: string;
}

export type BreakGlassStatus =
  | 'requested'
  | 'approved'
  | 'denied'
  | 'revoked'
  | 'expired';

export interface BreakGlassRequest {
  request_id: string;
  tenant_id: string;
  requested_by: string;
  approved_by?: string | null;
  reason: string;
  requested_scope: string;
  status: BreakGlassStatus;
  starts_at?: string | null;
  expires_at?: string | null;
  created_at: string;
  updated_at: string;
}

export type RetentionResourceType =
  | 'event'
  | 'profile'
  | 'recommendation'
  | 'decision'
  | 'action'
  | 'dispatch'
  | 'outcome'
  | 'audit_export'
  | 'billing_record'
  | 'audit_log';

export type RetentionDeleteBehavior =
  | 'hard_delete'
  | 'soft_delete'
  | 'anonymize'
  | 'preserve_audit_stub';

export interface DataRetentionPolicy {
  policy_id: string;
  tenant_id?: string | null;
  resource_type: RetentionResourceType;
  retention_days: number;
  legal_hold_supported: boolean;
  delete_behavior: RetentionDeleteBehavior;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export type DataRequestType =
  | 'export'
  | 'delete_entity'
  | 'delete_tenant'
  | 'retention_review'
  | 'access_review';

export type DataRequestStatus =
  | 'requested'
  | 'in_progress'
  | 'completed'
  | 'denied'
  | 'failed';

export interface DataRequest {
  data_request_id: string;
  tenant_id: string;
  request_type: DataRequestType;
  requested_by: string;
  status: DataRequestStatus;
  target_resource_type?: string | null;
  target_resource_id?: string | null;
  result_summary?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export type EvidencePackType =
  | 'access_control'
  | 'tenant_isolation'
  | 'audit_logging'
  | 'data_retention'
  | 'integration_security'
  | 'ai_recommendation_governance'
  | 'operator_access';

export type EvidencePackStatus = 'queued' | 'generated' | 'failed' | 'expired';

export interface GovernanceEvidencePack {
  evidence_pack_id: string;
  tenant_id?: string | null;
  pack_type: EvidencePackType;
  status: EvidencePackStatus;
  included_controls: string[];
  known_gaps: string[];
  file_ref?: string | null;
  integrity_hash?: string | null;
  requested_by: string;
  generated_at?: string | null;
  expires_at?: string | null;
}
