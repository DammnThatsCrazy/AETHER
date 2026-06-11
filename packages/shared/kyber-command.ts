export type CommandRisk = 'low' | 'medium' | 'high' | 'critical';
export type CommandStatus = 'pending' | 'pending_approval' | 'approved' | 'rejected' | 'executing' | 'completed' | 'failed' | 'rolled_back' | 'cancelled';

export interface KyberCommandEnvelope {
  command_id: string;
  command_type: string;

  // Safety
  risk_level: CommandRisk;
  blast_radius_estimate?: string;
  dry_run: boolean;
  idempotency_key: string;

  // Context
  operator_id: string;
  tenant_id?: string;
  entity_id?: string;
  reason: string;

  // Payload
  payload: Record<string, unknown>;

  // Lifecycle
  status: CommandStatus;
  submitted_at: string;

  // Approval
  requires_approval: boolean;
  approval_id?: string;
  approved_by?: string;
  approved_at?: string;

  // Execution
  executed_at?: string;
  execution_result?: Record<string, unknown>;
  post_action_verification?: Record<string, unknown>;

  // Rollback
  rollback_plan?: string;
  rolled_back_at?: string;

  // Audit
  audit_trail: Array<{
    timestamp: string;
    action: string;
    operator_id: string;
    note?: string;
  }>;
}

export interface KyberCommandReviewEnvelope {
  review_id: string;
  command: KyberCommandEnvelope;

  // Review context
  proposed_diff?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  rationale: string;

  // Risk assessment
  risk_level: CommandRisk;
  blast_radius: string;
  rollback_plan: string;
  expiry_at: string;

  // Review state
  status: 'pending' | 'approved' | 'rejected' | 'changes_requested' | 'expired';
  reviewer_id?: string;
  reviewed_at?: string;
  reviewer_notes?: string;

  // Links
  linked_incident_id?: string;
  linked_tenant_id?: string;
  linked_entity_id?: string;
}
