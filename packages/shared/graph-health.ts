export interface GraphHealthScore {
  tenant_id?: string;           // undefined = global
  scope: 'global' | 'tenant' | 'entity';
  computed_at: string;
  score: number;                // 0.0-1.0
  grade: 'healthy' | 'degraded' | 'critical' | 'unknown';

  // Node metrics
  total_nodes: number;
  orphan_nodes: number;
  stale_nodes: number;
  node_growth_rate_24h?: number;

  // Edge metrics
  total_edges: number;
  stale_edges: number;
  low_confidence_edges: number;
  edge_growth_rate_24h?: number;

  // Identity metrics
  merge_rate_24h?: number;
  split_rate_24h?: number;
  identity_churn_score?: number;

  // Quality metrics
  contaminated_source_tags?: string[];
  schema_drift_detected?: boolean;
  mutation_failure_rate?: number;
  quarantined_mutations?: number;

  // Provenance
  provenance: {
    computed_from: string[];
    as_of: string;
    method: string;
  };
}

export interface GraphDriftEvent {
  drift_id: string;
  tenant_id?: string;
  drift_type: 'schema_drift' | 'identity_churn' | 'contamination' | 'stale_source' | 'merge_anomaly' | 'split_anomaly' | 'unusual_edge_density' | 'mutation_failure';
  severity: 'low' | 'medium' | 'high' | 'critical';
  status: 'open' | 'acknowledged' | 'investigating' | 'resolved' | 'false_positive';

  detected_at: string;
  acknowledged_at?: string;
  resolved_at?: string;

  source_tag?: string;
  affected_entity_count?: number;
  affected_edge_count?: number;

  description: string;
  evidence: Record<string, unknown>;
  recommended_remediation?: string;

  operator_notes?: string;
  linked_incident_id?: string;
}

export interface ContaminationEvent {
  contamination_id: string;
  tenant_id?: string;
  source_tag: string;
  provider: string;

  detected_at: string;
  status: 'detected' | 'quarantined' | 'rolling_back' | 'resolved';

  affected_rows: number;
  affected_entities?: number;
  contamination_type: 'schema_mismatch' | 'stale_data' | 'invalid_provenance' | 'cross_tenant_leak' | 'bad_source';

  description: string;
  rollback_source_tag?: string;
  rollback_completed_at?: string;
}

export interface TenantHealthRollup {
  tenant_id: string;
  computed_at: string;
  overall_score: number;  // 0.0-1.0
  overall_grade: 'healthy' | 'degraded' | 'critical' | 'unknown';

  graph: GraphHealthScore;
  sdk_health_score?: number;
  connector_health_score?: number;
  data_lake_health_score?: number;
  agent_health_score?: number;

  open_drift_events: number;
  open_incidents: number;
  open_review_items: number;

  deployment_readiness: 'ready' | 'not_ready' | 'unknown';
  recommended_actions?: Array<{ priority: number; action: string; area: string }>;
}
