/**
 * Aether — Connector Taxonomy (TypeScript mirror)
 *
 * Mirrors the Python enums in:
 *   Backend Architecture/aether-backend/services/integrations/connectors/base.py
 *
 * Keep in sync with the Python source. Do not add values here without
 * adding them to the Python enums first.
 */

// ── Connector class ────────────────────────────────────────────────────────────

export type ConnectorClass =
  | "olympus_provider"
  | "tenant_byod_data"
  | "byok_gateway"
  | "action_notifier"
  | "dual_role";

export const ConnectorClass = {
  OLYMPUS_PROVIDER: "olympus_provider" as const,
  TENANT_BYOD_DATA: "tenant_byod_data" as const,
  BYOK_GATEWAY: "byok_gateway" as const,
  ACTION_NOTIFIER: "action_notifier" as const,
  DUAL_ROLE: "dual_role" as const,
} satisfies Record<string, ConnectorClass>;

// ── Connector role ─────────────────────────────────────────────────────────────

export type ConnectorRole =
  | "data_ingestion"
  | "action_delivery"
  | "credential_gateway"
  | "enrichment_provider"
  | "webhook_receiver"
  | "sync_source"
  | "realtime_stream"
  | "batch_backfill"
  | "query_execution"
  | "warehouse_datashare"
  | "dual_role";

export const ConnectorRole = {
  DATA_INGESTION: "data_ingestion" as const,
  ACTION_DELIVERY: "action_delivery" as const,
  CREDENTIAL_GATEWAY: "credential_gateway" as const,
  ENRICHMENT_PROVIDER: "enrichment_provider" as const,
  WEBHOOK_RECEIVER: "webhook_receiver" as const,
  SYNC_SOURCE: "sync_source" as const,
  REALTIME_STREAM: "realtime_stream" as const,
  BATCH_BACKFILL: "batch_backfill" as const,
  QUERY_EXECUTION: "query_execution" as const,
  WAREHOUSE_DATASHARE: "warehouse_datashare" as const,
  DUAL_ROLE: "dual_role" as const,
} satisfies Record<string, ConnectorRole>;

// ── Data flow direction ────────────────────────────────────────────────────────

export type DataFlowDirection = "inbound" | "outbound" | "bidirectional" | "none";

export const DataFlowDirection = {
  INBOUND: "inbound" as const,
  OUTBOUND: "outbound" as const,
  BIDIRECTIONAL: "bidirectional" as const,
  NONE: "none" as const,
} satisfies Record<string, DataFlowDirection>;

// ── Lake write policy ──────────────────────────────────────────────────────────

export type LakeWritePolicy =
  | "never"
  | "tenant_only"
  | "olympus_baseline_eligible"
  | "olympus_baseline_allowed"
  | "quarantine_only";

export const LakeWritePolicy = {
  NEVER: "never" as const,
  TENANT_ONLY: "tenant_only" as const,
  OLYMPUS_BASELINE_ELIGIBLE: "olympus_baseline_eligible" as const,
  OLYMPUS_BASELINE_ALLOWED: "olympus_baseline_allowed" as const,
  QUARANTINE_ONLY: "quarantine_only" as const,
} satisfies Record<string, LakeWritePolicy>;

// ── Graph write policy ─────────────────────────────────────────────────────────

export type GraphWritePolicy =
  | "none"
  | "tenant_graph_only"
  | "tenant_graph_and_aggregate_eligible"
  | "olympus_graph_allowed"
  | "quarantine_only";

export const GraphWritePolicy = {
  NONE: "none" as const,
  TENANT_GRAPH_ONLY: "tenant_graph_only" as const,
  TENANT_GRAPH_AND_AGGREGATE_ELIGIBLE: "tenant_graph_and_aggregate_eligible" as const,
  OLYMPUS_GRAPH_ALLOWED: "olympus_graph_allowed" as const,
  QUARANTINE_ONLY: "quarantine_only" as const,
} satisfies Record<string, GraphWritePolicy>;

// ── Model training eligibility ─────────────────────────────────────────────────

export type ModelTrainingEligibility =
  | "never"
  | "tenant_only"
  | "aggregate_only"
  | "olympus_allowed"
  | "compliance_review_required";

export const ModelTrainingEligibility = {
  NEVER: "never" as const,
  TENANT_ONLY: "tenant_only" as const,
  AGGREGATE_ONLY: "aggregate_only" as const,
  OLYMPUS_ALLOWED: "olympus_allowed" as const,
  COMPLIANCE_REVIEW_REQUIRED: "compliance_review_required" as const,
} satisfies Record<string, ModelTrainingEligibility>;

// ── Implementation status ──────────────────────────────────────────────────────

export type ImplementationStatus =
  | "mocked_local"
  | "scaffolded"
  | "production_shaped"
  | "credential_gated"
  | "provider_live"
  | "warehouse_datashare_ready"
  | "staging_validation_required"
  | "disabled_compliance_review"
  | "deprecated";

export const ImplementationStatus = {
  MOCKED_LOCAL: "mocked_local" as const,
  SCAFFOLDED: "scaffolded" as const,
  PRODUCTION_SHAPED: "production_shaped" as const,
  CREDENTIAL_GATED: "credential_gated" as const,
  PROVIDER_LIVE: "provider_live" as const,
  WAREHOUSE_DATASHARE_READY: "warehouse_datashare_ready" as const,
  STAGING_VALIDATION_REQUIRED: "staging_validation_required" as const,
  DISABLED_COMPLIANCE_REVIEW: "disabled_compliance_review" as const,
  DEPRECATED: "deprecated" as const,
} satisfies Record<string, ImplementationStatus>;

// ── Priority phase ─────────────────────────────────────────────────────────────

export type PriorityPhase =
  | "phase_1_foundation"
  | "phase_2_enrichment"
  | "phase_3_depth"
  | "not_scheduled";

export const PriorityPhase = {
  PHASE_1_FOUNDATION: "phase_1_foundation" as const,
  PHASE_2_ENRICHMENT: "phase_2_enrichment" as const,
  PHASE_3_DEPTH: "phase_3_depth" as const,
  NOT_SCHEDULED: "not_scheduled" as const,
} satisfies Record<string, PriorityPhase>;

// ── Risk tier ──────────────────────────────────────────────────────────────────

export type RiskTier = "low" | "medium" | "high" | "restricted";

export const RiskTier = {
  LOW: "low" as const,
  MEDIUM: "medium" as const,
  HIGH: "high" as const,
  RESTRICTED: "restricted" as const,
} satisfies Record<string, RiskTier>;

// ── Intelligence source coverage ───────────────────────────────────────────────

export type IntelligenceSourceMode =
  | "baseline_only"
  | "baseline_plus_tenant_connector"
  | "baseline_plus_sdk_live"
  | "baseline_plus_tenant_connector_plus_sdk_live";

export interface IntelligenceSourceCoverage {
  source_mode: IntelligenceSourceMode;
  baseline_coverage: number;
  connector_coverage: number;
  sdk_live_coverage: number;
  identity_confidence: number;
  data_freshness_score: number;
  model_confidence: number;
  last_refreshed_at: string | null;
}
