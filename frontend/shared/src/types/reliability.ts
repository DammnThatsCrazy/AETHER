/**
 * Shared reliability / SRE / incident-response contracts.
 *
 * These mirror the backend Pydantic models in
 * `services/reliability/models.py`. Field names are identical across layers so
 * payloads round-trip cleanly between backend and frontend (Kyber + Aether).
 */

export type ServiceHealthStatus =
  | 'healthy'
  | 'degraded'
  | 'critical'
  | 'offline'
  | 'unknown';

export type IncidentSeverity = 'sev1' | 'sev2' | 'sev3' | 'sev4';

export type IncidentStatus =
  | 'open'
  | 'investigating'
  | 'mitigating'
  | 'resolved'
  | 'postmortem_pending'
  | 'closed';

export type SLOWindow = '1h' | '24h' | '7d' | '30d' | '90d';

export type SLOStatus = 'meeting' | 'at_risk' | 'breached' | 'unknown';

export type PostmortemStatus = 'draft' | 'reviewed' | 'closed';

export interface ServiceHealthRecord {
  service_key: string;
  label: string;
  status: ServiceHealthStatus;
  latency_ms?: number | null;
  error_rate?: number | null;
  last_heartbeat_at?: string | null;
  last_successful_job_at?: string | null;
  open_incident_ids: string[];
  affected_tenant_count?: number | null;
  metadata?: Record<string, unknown> | null;
  updated_at: string;
}

export interface PipelineHealthRecord {
  pipeline_key: string;
  label: string;
  source: string;
  destination: string;
  status: ServiceHealthStatus;
  throughput_per_minute?: number | null;
  latency_ms?: number | null;
  error_rate?: number | null;
  retry_count?: number | null;
  dead_letter_count?: number | null;
  last_successful_run_at?: string | null;
  freshness_seconds?: number | null;
  affected_tenant_count?: number | null;
  updated_at: string;
}

export interface QueueHealthRecord {
  queue_key: string;
  label: string;
  status: ServiceHealthStatus;
  depth: number;
  oldest_message_age_seconds?: number | null;
  worker_count?: number | null;
  active_worker_count?: number | null;
  retry_count?: number | null;
  dead_letter_count?: number | null;
  processing_latency_ms?: number | null;
  updated_at: string;
}

export interface IncidentRecord {
  incident_id: string;
  title: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  affected_services: string[];
  affected_tenants?: string[] | null;
  affected_pipelines?: string[] | null;
  affected_modules?: string[] | null;
  started_at: string;
  detected_at?: string | null;
  resolved_at?: string | null;
  owner_id?: string | null;
  runbook_id?: string | null;
  summary?: string | null;
  root_cause?: string | null;
  mitigation_steps: string[];
  customer_impact?: string | null;
  internal_notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface OperationalRunbook {
  runbook_id: string;
  title: string;
  incident_type: string;
  severity_hint: IncidentSeverity;
  detection_signals: string[];
  diagnostic_steps: string[];
  mitigation_steps: string[];
  escalation_paths: string[];
  customer_comms_template?: string | null;
  postmortem_required: boolean;
  created_at: string;
  updated_at: string;
}

export interface ServiceLevelObjective {
  slo_id: string;
  service_key: string;
  metric_key: string;
  target: number;
  window: SLOWindow;
  current_value?: number | null;
  status: SLOStatus;
  error_budget_remaining?: number | null;
  created_at: string;
  updated_at: string;
}

export interface IncidentPostmortem {
  postmortem_id: string;
  incident_id: string;
  summary: string;
  timeline: string[];
  root_cause: string;
  contributing_factors: string[];
  customer_impact: string;
  detection_gap?: string | null;
  mitigation_gap?: string | null;
  prevention_actions: string[];
  owner_id?: string | null;
  status: PostmortemStatus;
  created_at: string;
  updated_at: string;
}

/** Tenant-safe status summary surfaced in Aether. Never includes infra internals. */
export interface TenantStatusSummary {
  tenant_id: string;
  overall_status: ServiceHealthStatus;
  data_freshness: string;
  active_incidents: number;
  integration_status: string;
  audit_export_status: string;
  recommendation_status: string;
  outcome_capture_status: string;
  updated_at: string;
}

/** Tenant-safe incident projection (whitelisted fields only). */
export interface TenantSafeIncident {
  incident_id: string;
  title: string;
  status: IncidentStatus;
  severity: IncidentSeverity;
  customer_impact?: string | null;
  started_at?: string | null;
  resolved_at?: string | null;
  updated_at?: string | null;
}
