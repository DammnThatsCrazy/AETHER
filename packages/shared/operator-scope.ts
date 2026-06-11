// Operator scope types for Kyber internal operator console
export type GraphScope = 'global' | 'tenant' | 'entity' | 'case' | 'break_glass';

export interface ScopeContext {
  scope: GraphScope;
  tenant_id?: string;        // required for tenant/entity scope
  entity_id?: string;        // required for entity scope
  case_id?: string;          // required for case scope
  break_glass_approval_id?: string; // required for break_glass scope
  operator_id: string;
  reason: string;
  audit_request_id: string;
  requested_at: string;
}

export interface ScopedGraphQuery extends ScopeContext {
  query_type: 'traversal' | 'neighbors' | 'path' | 'search' | 'health';
  depth?: number;
  direction?: 'inbound' | 'outbound' | 'both';
  filters?: Record<string, unknown>;
}

export interface ProvenanceEnvelope {
  source: string;
  source_tag?: string;
  pulled_at: string;
  query_id?: string;
  execution_id?: string;
  row_hash?: string;
  freshness_timestamp: string;
  quality_score?: number;
  promotion_status: 'bronze' | 'silver' | 'gold' | 'rejected';
}

export interface FreshnessEnvelope {
  computed_at: string;
  data_as_of: string;
  max_age_seconds: number;
  is_stale: boolean;
  staleness_seconds?: number;
}

export interface ConfidenceEnvelope {
  score: number;           // 0.0-1.0
  method: string;
  evidence_count: number;
  low_confidence_reason?: string;
}

export interface RedactionMetadata {
  field_name: string;
  reason: string;
  policy: string;
  redacted_by: string;
}

export interface AuditEnvelope {
  audit_request_id: string;
  operator_id: string;
  scope: GraphScope;
  tenant_id?: string;
  action: string;
  reason: string;
  timestamp: string;
  ip_address?: string;
  session_id?: string;
}

export interface ScopedGraphResponse<T = unknown> {
  data: T;
  scope: GraphScope;
  tenant_id?: string;
  provenance: ProvenanceEnvelope;
  freshness: FreshnessEnvelope;
  confidence: ConfidenceEnvelope;
  audit: AuditEnvelope;
  redacted_fields?: RedactionMetadata[];
  permission_summary?: Record<string, boolean>;
}
