import { z } from 'zod';
import { restClient, RestClientError } from '@aether-app/lib/api/rest/client';
import { aiInvocationStatuses, costBases, aiEfficiencyDetectors } from '@aether/shared';

const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });

const buildQS = (params: Record<string, string | number | boolean | undefined>): string => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
};

const BASE = '/v1/economic/ai';

// ── Wire schemas (snake_case per backend; mirrors @aether/shared ai-execution) ──
// Tolerant on purpose: the backend is built in parallel. Unknown costs arrive
// as null and stay null — they are displayed as "unknown", never rendered as 0.

/** Per-currency amounts, e.g. { USD: 1240.5, EUR: 96.4 }. Never merged across currencies. */
const currencyAmountsSchema = z.record(z.number());

export type CurrencyAmounts = Record<string, number>;

export const aiEfficiencySummarySchema = z.object({
  totals_by_currency: currencyAmountsSchema.nullish(),
  invocation_count: z.number().nullish(),
  completed_workflow_count: z.number().nullish(),
  cost_per_invocation_by_currency: currencyAmountsSchema.nullish(),
  failed_execution_cost_by_currency: currencyAmountsSchema.nullish(),
  retry_waste_cost_by_currency: currencyAmountsSchema.nullish(),
  cache_utilization_rate: z.number().nullish(),
  human_correction_rate: z.number().nullish(),
  outcome_attribution_coverage: z.number().nullish(),
  cost_coverage: z.number().nullish(),
}).passthrough();

export type AIEfficiencySummaryRecord = z.infer<typeof aiEfficiencySummarySchema>;

export const aiExecutionFactSchema = z.object({
  invocation_id: z.string(),
  tenant_id: z.string().nullish(),
  observed_at: z.string(),
  trace_id: z.string().nullish(),
  workflow_run_id: z.string().nullish(),
  task_type: z.string(),
  use_case: z.string().nullish(),
  provider: z.string(),
  model: z.string(),
  model_version: z.string().nullish(),
  status: z.enum(aiInvocationStatuses),
  error_code: z.string().nullish(),
  input_tokens: z.number().nullish(),
  output_tokens: z.number().nullish(),
  cached_input_tokens: z.number().nullish(),
  latency_ms: z.number().nullish(),
  retry_count: z.number().nullish(),
  /** Cost chosen by the selection hierarchy. Null when unknown — never zeroed. */
  selected_cost: z.number().nullish(),
  cost_basis: z.enum(costBases),
  currency: z.string(),
  quality_score: z.number().nullish(),
  human_reviewed: z.boolean().nullish(),
  human_corrected: z.boolean().nullish(),
  data_quality_status: z.string().nullish(),
}).passthrough();

export type AIExecutionFactRecord = z.infer<typeof aiExecutionFactSchema>;

// Tolerant list shape: bare array or { invocations: [...] }.
const invocationListSchema = z.union([
  z.array(aiExecutionFactSchema),
  z.object({ invocations: z.array(aiExecutionFactSchema) }).passthrough(),
]);

export const aiWorkflowEconomicsSchema = z.object({
  tenant_id: z.string().nullish(),
  workflow_run_id: z.string(),
  total_invocations: z.number(),
  successful_invocations: z.number().nullish(),
  failed_invocations: z.number().nullish(),
  total_retries: z.number().nullish(),
  total_latency_ms: z.number().nullish(),
  total_model_cost: z.number().nullish(),
  tool_cost: z.number().nullish(),
  retrieval_cost: z.number().nullish(),
  fully_loaded_cost: z.number().nullish(),
  currency: z.string(),
  cost_coverage: z.number().nullish(),
  quality_score: z.number().nullish(),
  human_reviewed: z.boolean().nullish(),
  human_corrected: z.boolean().nullish(),
  technical_success: z.boolean().nullish(),
  qualified_outcome_count: z.number().nullish(),
  attributed_value: z.number().nullish(),
  first_observed_at: z.string().nullish(),
  last_observed_at: z.string().nullish(),
  computed_at: z.string().nullish(),
}).passthrough();

export type AIWorkflowEconomicsRecord = z.infer<typeof aiWorkflowEconomicsSchema>;

// Tolerant list shape: bare array or { workflows: [...] }.
const workflowListSchema = z.union([
  z.array(aiWorkflowEconomicsSchema),
  z.object({ workflows: z.array(aiWorkflowEconomicsSchema) }).passthrough(),
]);

export const aiModelUsageSchema = z.object({
  provider: z.string(),
  model: z.string(),
  invocations: z.number(),
  cost_by_currency: currencyAmountsSchema.nullish(),
  avg_latency_ms: z.number().nullish(),
  success_rate: z.number().nullish(),
  avg_quality: z.number().nullish(),
}).passthrough();

export type AIModelUsageRecord = z.infer<typeof aiModelUsageSchema>;

// Tolerant list shape: bare array or { models: [...] }.
const modelListSchema = z.union([
  z.array(aiModelUsageSchema),
  z.object({ models: z.array(aiModelUsageSchema) }).passthrough(),
]);

export const aiEfficiencyFindingSchema = z.object({
  detector: z.enum(aiEfficiencyDetectors),
  severity: z.string(),
  title: z.string(),
  description: z.string().nullish(),
  evidence_refs: z.array(z.string()).nullish(),
  /** Estimated monthly waste in `currency`. Null when unknown — never zeroed. */
  estimated_monthly_waste: z.number().nullish(),
  currency: z.string().nullish(),
  candidate_action: z.string().nullish(),
}).passthrough();

export type AIEfficiencyFindingRecord = z.infer<typeof aiEfficiencyFindingSchema>;

// Tolerant list shapes: bare array or { findings: [...] } / { recommendations: [...] }.
const findingListSchema = z.union([
  z.array(aiEfficiencyFindingSchema),
  z.object({ findings: z.array(aiEfficiencyFindingSchema) }).passthrough(),
]);

const recommendationListSchema = z.union([
  z.array(aiEfficiencyFindingSchema),
  z.object({ recommendations: z.array(aiEfficiencyFindingSchema) }).passthrough(),
]);

// ── Fetchers ───────────────────────────────────────────────────────────────────

export interface AIEfficiencySummaryResult {
  readonly summary: AIEfficiencySummaryRecord | null;
  /** True when the backend reports AI outcome efficiency is not enabled (404/501). */
  readonly notConfigured: boolean;
}

export async function fetchAISummary(): Promise<AIEfficiencySummaryResult> {
  try {
    const r = await restClient.get(`${BASE}/summary`, wrap(aiEfficiencySummarySchema));
    return { summary: r.data, notConfigured: false };
  } catch (err) {
    if (err instanceof RestClientError && (err.status === 404 || err.status === 501)) {
      return { summary: null, notConfigured: true };
    }
    throw err;
  }
}

export interface AIInvocationListParams {
  readonly provider?: string;
  readonly model?: string;
  readonly status?: string;
  readonly task_type?: string;
  readonly workflow_run_id?: string;
}

export interface AIInvocationListResult {
  readonly invocations: AIExecutionFactRecord[];
  /** True when the backend reports AI outcome efficiency is not enabled (404/501). */
  readonly notConfigured: boolean;
}

export async function fetchAIInvocations(params?: AIInvocationListParams): Promise<AIInvocationListResult> {
  try {
    const r = await restClient.get(
      `${BASE}/invocations${buildQS({
        provider: params?.provider,
        model: params?.model,
        status: params?.status,
        task_type: params?.task_type,
        workflow_run_id: params?.workflow_run_id,
      })}`,
      wrap(invocationListSchema),
    );
    const invocations = Array.isArray(r.data) ? r.data : r.data.invocations;
    return { invocations, notConfigured: false };
  } catch (err) {
    if (err instanceof RestClientError && (err.status === 404 || err.status === 501)) {
      return { invocations: [], notConfigured: true };
    }
    throw err;
  }
}

export interface AIWorkflowListResult {
  readonly workflows: AIWorkflowEconomicsRecord[];
  /** True when the backend reports AI outcome efficiency is not enabled (404/501). */
  readonly notConfigured: boolean;
}

export async function fetchAIWorkflows(): Promise<AIWorkflowListResult> {
  try {
    const r = await restClient.get(`${BASE}/workflows`, wrap(workflowListSchema));
    const workflows = Array.isArray(r.data) ? r.data : r.data.workflows;
    return { workflows, notConfigured: false };
  } catch (err) {
    if (err instanceof RestClientError && (err.status === 404 || err.status === 501)) {
      return { workflows: [], notConfigured: true };
    }
    throw err;
  }
}

export interface AIModelListResult {
  readonly models: AIModelUsageRecord[];
  /** True when the backend reports AI outcome efficiency is not enabled (404/501). */
  readonly notConfigured: boolean;
}

export async function fetchAIModels(): Promise<AIModelListResult> {
  try {
    const r = await restClient.get(`${BASE}/models`, wrap(modelListSchema));
    const models = Array.isArray(r.data) ? r.data : r.data.models;
    return { models, notConfigured: false };
  } catch (err) {
    if (err instanceof RestClientError && (err.status === 404 || err.status === 501)) {
      return { models: [], notConfigured: true };
    }
    throw err;
  }
}

export interface AIFindingListResult {
  readonly findings: AIEfficiencyFindingRecord[];
  /** True when the backend reports AI outcome efficiency is not enabled (404/501). */
  readonly notConfigured: boolean;
}

export async function fetchAIWasteFindings(): Promise<AIFindingListResult> {
  try {
    const r = await restClient.get(`${BASE}/waste`, wrap(findingListSchema));
    const findings = Array.isArray(r.data) ? r.data : r.data.findings;
    return { findings, notConfigured: false };
  } catch (err) {
    if (err instanceof RestClientError && (err.status === 404 || err.status === 501)) {
      return { findings: [], notConfigured: true };
    }
    throw err;
  }
}

export interface AIRecommendationListResult {
  readonly recommendations: AIEfficiencyFindingRecord[];
  /** True when the backend reports AI outcome efficiency is not enabled (404/501). */
  readonly notConfigured: boolean;
}

export async function fetchAIRecommendations(): Promise<AIRecommendationListResult> {
  try {
    const r = await restClient.get(`${BASE}/recommendations`, wrap(recommendationListSchema));
    const recommendations = Array.isArray(r.data) ? r.data : r.data.recommendations;
    return { recommendations, notConfigured: false };
  } catch (err) {
    if (err instanceof RestClientError && (err.status === 404 || err.status === 501)) {
      return { recommendations: [], notConfigured: true };
    }
    throw err;
  }
}
