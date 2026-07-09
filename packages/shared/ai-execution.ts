// =============================================================================
// AI Outcome Efficiency — canonical AI execution contracts
// =============================================================================
// Semantic contract for the canonical `ai_invocation_observed` event and the
// `ai_execution_facts` read model. Records carry identity, version, hash,
// configuration, usage, model, provider, cost, latency, quality, and outcome
// correlation — never raw prompt or completion content, chain of thought,
// API keys, or retrieved document content.
// =============================================================================

export const AI_EXECUTION_SCHEMA_VERSION = 'ai.execution.v1' as const;

/** How the selected cost for an invocation was determined. */
export const costBases = [
  'billed',
  'provider_reported',
  'calculated',
  'estimated',
  'unknown',
] as const;
export type CostBasis = typeof costBases[number];

export const aiInvocationStatuses = [
  'succeeded',
  'failed',
  'cancelled',
  'timeout',
] as const;
export type AIInvocationStatus = typeof aiInvocationStatuses[number];

export interface AIInvocationProvenance {
  /** Emitting source, e.g. 'noesis', 'sdk', 'internal_recorder'. */
  source: string;
  provider_request_id?: string;
  /** Hash of the normalized source payload; used for idempotent replay. */
  raw_event_hash: string;
  schema_version: string;
}

/**
 * Canonical `ai_invocation_observed` event payload.
 *
 * Required: invocation_id, tenant_id, observed_at, task_type, provider,
 * model, status, currency, provenance. Usage, cost, and latency values must
 * be non-negative; quality_score must be within 0..1. `contains_*_content`
 * flags default to false — payloads carrying raw prompt/completion content
 * are rejected or redacted at ingestion.
 */
export interface AIInvocationObserved {
  invocation_id: string;
  tenant_id: string;
  observed_at: string;

  trace_id?: string;
  workflow_run_id?: string;
  task_id?: string;
  action_id?: string;
  recommendation_id?: string;
  suggestion_id?: string;
  outcome_id?: string;
  entity_id?: string;
  agent_id?: string;
  campaign_id?: string;

  task_type: string;
  use_case?: string;
  business_unit?: string;
  environment?: 'development' | 'staging' | 'production';

  provider: string;
  model: string;
  model_version?: string;
  deployment_id?: string;
  region?: string;

  prompt_id?: string;
  prompt_version?: string;
  prompt_hash?: string;
  configuration_hash?: string;

  input_tokens?: number;
  output_tokens?: number;
  cached_input_tokens?: number;
  reasoning_tokens?: number;
  embedding_tokens?: number;
  image_units?: number;
  audio_seconds?: number;
  video_seconds?: number;
  tool_call_count?: number;
  retrieval_count?: number;

  latency_ms?: number;
  time_to_first_token_ms?: number;
  retry_count?: number;

  status: AIInvocationStatus;
  error_code?: string;

  estimated_cost?: number;
  actual_cost?: number;
  billed_cost?: number;
  currency: string;
  pricing_version?: string;
  customer_managed_key?: boolean;

  quality_score?: number;
  evaluation_id?: string;
  human_reviewed?: boolean;
  human_corrected?: boolean;

  contains_prompt_content: boolean;
  contains_completion_content: boolean;
  data_classification?: string;

  provenance: AIInvocationProvenance;
}

export const aiDataQualityStatuses = [
  'complete',
  'partial',
  'estimated',
  'suspect',
] as const;
export type AIDataQualityStatus = typeof aiDataQualityStatuses[number];

/**
 * Canonical AI execution fact (silver projection `ai_execution_facts`).
 * One row per (tenant_id, invocation_id). Cost selection hierarchy:
 * billed → provider_reported → calculated (price card) → estimated → unknown.
 * Unknown cost stays unknown — it never silently becomes zero.
 */
export interface AIExecutionFact extends AIInvocationObserved {
  /** Cost chosen by the selection hierarchy, in `currency`. Null when unknown. */
  selected_cost?: number | null;
  cost_basis: CostBasis;
  received_at: string;
  computed_at: string;
  data_quality_status: AIDataQualityStatus;
}

/** Usage dimensions priced by an AI price card. */
export interface AIPriceCardRates {
  input_tokens_per_1k?: number;
  output_tokens_per_1k?: number;
  cached_input_tokens_per_1k?: number;
  reasoning_tokens_per_1k?: number;
  embedding_tokens_per_1k?: number;
  image_unit?: number;
  audio_second?: number;
  video_second?: number;
  tool_call?: number;
  retrieval?: number;
}

/** Effective-dated price card for provider/model/region/service tier. */
export interface AIPriceCard {
  id: string;
  provider: string;
  model: string;
  region?: string;
  service_tier?: string;
  currency: string;
  pricing_version: string;
  rates: AIPriceCardRates;
  effective_from: string;
  effective_to?: string;
  source: string;
  created_at: string;
}

/**
 * Workflow-level economics aggregated by (tenant_id, workflow_run_id).
 * Workflow IDs are never fabricated — invocations without a workflow_run_id
 * are excluded from workflow aggregation.
 */
export interface AIWorkflowEconomics {
  tenant_id: string;
  workflow_run_id: string;

  total_invocations: number;
  successful_invocations: number;
  failed_invocations: number;
  total_retries: number;
  total_latency_ms: number;

  total_model_cost?: number | null;
  tool_cost?: number | null;
  retrieval_cost?: number | null;
  fully_loaded_cost?: number | null;
  currency: string;
  /** Share of invocations whose cost_basis is not 'unknown' (0..1). */
  cost_coverage: number;

  quality_score?: number;
  human_reviewed: boolean;
  human_corrected: boolean;
  technical_success: boolean;

  qualified_outcome_count: number;
  attributed_value?: number | null;

  first_observed_at: string;
  last_observed_at: string;
  computed_at: string;
}

/** Deterministic AI efficiency detector families (governed proposals only). */
export const aiEfficiencyDetectors = [
  'retry_waste',
  'model_overqualification',
  'deterministic_replacement_candidate',
  'cache_opportunity',
  'failed_workflow_concentration',
] as const;
export type AIEfficiencyDetector = typeof aiEfficiencyDetectors[number];

/** Recommendation family key for AI outcome efficiency. */
export const AI_OUTCOME_EFFICIENCY_FAMILY = 'ai_outcome_efficiency' as const;
