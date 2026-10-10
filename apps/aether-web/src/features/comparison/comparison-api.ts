import { z } from 'zod';
import type {
  ComparisonDefinition,
  ComparisonFinding,
  ComparisonRun,
} from '@aether/shared/comparison-contract';
import { restClient } from '@aether-app/lib/api/rest/client';

const wrap = <T extends z.ZodTypeAny>(data: T) =>
  z.object({ data, status: z.string(), timestamp: z.string() });
const unknownRecord = z.record(z.string(), z.unknown());

export interface DataTruthEntry {
  dimension: string;
  subject_state: string;
  baseline_state: string;
  subject_observations: number;
  baseline_observations: number;
  subject_fact_linkage: string;
  baseline_fact_linkage: string;
  decision: 'compare' | 'refuse';
  refusal_reason?: string | null;
}

export interface AlignmentPair {
  name: string;
  unit: string;
  subject_value: number;
  baseline_value: number;
  converted?: boolean;
  conversion?: string | null;
}

export interface AlignmentDecision {
  dimension: string;
  outcome: string;
  reason?: string | null;
  pairs: AlignmentPair[];
  subject_only_metrics: string[];
  baseline_only_metrics: string[];
}

export interface ComparisonRunDetail extends ComparisonRun {
  data_truth?: DataTruthEntry[];
  alignment_decisions?: AlignmentDecision[];
  baseline_version?: string | null;
}

export interface ComparisonFindingDetail extends ComparisonFinding {
  causal_claim?: string | null;
  evidence_basis?: string | null;
  fact_linkage?: string | null;
  disposition?: string | null;
}

export interface CreateComparisonDefinitionRequest {
  name?: string;
  mode: string;
  subject: {
    subject_type: string;
    subject_id: string;
    tenant_id: string;
    as_of?: string | null;
  };
  baseline: {
    baseline_type: string;
    subject?: {
      subject_type: string;
      subject_id: string;
      tenant_id: string;
      as_of?: string | null;
    } | null;
    window_start?: string | null;
    window_end?: string | null;
  };
  dimensions: string[];
  temporal_mode: string;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : '';
}

export const comparisonApi = {
  listDefinitions: async (): Promise<ComparisonDefinition[]> => {
    const response = await restClient.get(
      '/v1/intelligence/comparisons',
      wrap(z.object({ definitions: z.array(unknownRecord) })),
    );
    return response.data.definitions as unknown as ComparisonDefinition[];
  },
  createDefinition: async (
    request: CreateComparisonDefinitionRequest,
  ): Promise<ComparisonDefinition> => {
    const response = await restClient.post(
      '/v1/intelligence/comparisons',
      wrap(z.object({ definition: unknownRecord })),
      request,
    );
    return response.data.definition as unknown as ComparisonDefinition;
  },
  triggerRun: async (definitionId: string, asOf?: string): Promise<ComparisonRunDetail> => {
    const response = await restClient.post(
      `/v1/intelligence/comparisons/${encodeURIComponent(definitionId)}/runs`,
      wrap(z.object({ run: unknownRecord, job_id: z.string() })),
      asOf ? { as_of: asOf } : {},
    );
    return response.data.run as unknown as ComparisonRunDetail;
  },
  getRun: async (runId: string): Promise<ComparisonRunDetail> => {
    const response = await restClient.get(
      `/v1/intelligence/comparisons/runs/${encodeURIComponent(runId)}`,
      wrap(z.object({ run: unknownRecord })),
    );
    return response.data.run as unknown as ComparisonRunDetail;
  },
  listFindings: async (runId: string): Promise<ComparisonFindingDetail[]> => {
    const response = await restClient.get(
      `/v1/intelligence/comparisons/findings${query({ run_id: runId, limit: 200 })}`,
      wrap(z.object({ findings: z.array(unknownRecord) })),
    );
    return response.data.findings as unknown as ComparisonFindingDetail[];
  },
};
