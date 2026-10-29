import { useQuery } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@aether-app/lib/api/rest/client';
import { useGraphContext } from '@aether/ui/exploration';
import { fetchAgentDeployments } from '@aether-app/features/deployments';

const runEvidenceSchema = z.object({
  tenant_id: z.string().optional(),
  deployment_id: z.string(),
  run_id: z.string(),
  source_status: z.enum(['available', 'empty', 'unavailable']),
  evidence_count: z.number().optional(),
  evidence_truncated: z.boolean().optional(),
  evidence: z.array(z.record(z.unknown())).default([]),
  coverage: z.record(z.enum(['observed', 'not_observed'])).optional(),
  explanation_boundary: z.string().optional(),
}).passthrough();

const runEvidenceEnvelopeSchema = z.object({
  data: runEvidenceSchema,
  status: z.string(),
  timestamp: z.string(),
}).passthrough();

const agentRunIndexEnvelopeSchema = z.object({
  data: z.object({
    deployment_id: z.string(),
    source_status: z.enum(['available', 'empty', 'unavailable']),
    runs: z.array(z.object({
      run_id: z.string(),
      first_event_at: z.string().optional(),
      last_event_at: z.string().optional(),
      event_count: z.number().optional(),
      event_types: z.array(z.string()).optional(),
      run_correlation_source: z.string().nullable().optional(),
    }).passthrough()).default([]),
    source_rows_scanned: z.number().optional(),
    runs_truncated: z.boolean().optional(),
  }).passthrough(),
  status: z.string(),
  timestamp: z.string(),
}).passthrough();

const marketplaceCatalogEnvelopeSchema = z.object({
  data: z.object({
    listings: z.array(z.record(z.unknown())).default([]),
    observed_at: z.string().nullable().optional(),
    last_success_at: z.string().nullable().optional(),
    source_status: z.string(),
  }).passthrough(),
  status: z.string(),
  timestamp: z.string(),
}).passthrough();

export type AgentRunEvidence = z.infer<typeof runEvidenceSchema>;
export type AgentRunIndex = z.infer<typeof agentRunIndexEnvelopeSchema>['data'];
export type AgentMarketplaceCatalog = z.infer<typeof marketplaceCatalogEnvelopeSchema>['data'];

const responseSchema = z.object({
  data: z.record(z.unknown()),
  status: z.string(),
  timestamp: z.string(),
}).passthrough();

export type Agent360Profile = z.infer<typeof responseSchema>['data'];

export function useAgent360(agentId: string) {
  return useQuery({
    key: `agent-360:${agentId}`,
    fetcher: () => restClient
      .get(`/v1/profile/${encodeURIComponent(agentId)}/agent`, responseSchema)
      .then(response => response.data),
    enabled: Boolean(agentId),
    staleTime: 30_000,
  });
}

/** Tenant-scoped deployments registered for the Agent 360 source reference. */
export function useAgent360Deployments(agentId: string) {
  const { scope } = useGraphContext();
  return useQuery({
    key: `agent-360-deployments:${encodeURIComponent(scope.tenant_id)}:${encodeURIComponent(agentId)}`,
    fetcher: () => fetchAgentDeployments({ agent_id: agentId }),
    enabled: Boolean(agentId),
    staleTime: 30_000,
  });
}

/** Fetches one source-reported run timeline using the authenticated tenant scope. */
export function useAgentRunEvidence(deploymentId: string, runId: string) {
  const { scope } = useGraphContext();
  const tenantId = scope.tenant_id;
  return useQuery({
    key: `agent-360-run:${encodeURIComponent(tenantId)}:${encodeURIComponent(deploymentId)}:${encodeURIComponent(runId)}`,
    fetcher: () => restClient
      .get(
        `/v1/agent/deployments/${encodeURIComponent(deploymentId)}/runs/${encodeURIComponent(runId)}/explanation`,
        runEvidenceEnvelopeSchema,
      )
      .then(response => response.data),
    enabled: Boolean(tenantId && deploymentId && runId),
    staleTime: 15_000,
  });
}

/** Recent source-reported run IDs for a tenant-owned external deployment. */
export function useAgentRecentRuns(deploymentId: string) {
  const { scope } = useGraphContext();
  const tenantId = scope.tenant_id;
  return useQuery({
    key: `agent-360-runs:${encodeURIComponent(tenantId)}:${encodeURIComponent(deploymentId)}`,
    fetcher: () => restClient
      .get(
        `/v1/agent/deployments/${encodeURIComponent(deploymentId)}/runs`,
        agentRunIndexEnvelopeSchema,
      )
      .then(response => response.data),
    enabled: Boolean(tenantId && deploymentId),
    staleTime: 15_000,
  });
}

/** Read-only public catalog observation, partitioned by the active tenant cache scope. */
export function useAgentMarketplaceCatalog() {
  const { scope } = useGraphContext();
  const tenantId = scope.tenant_id;
  return useQuery({
    key: `agent-marketplace-catalog:${encodeURIComponent(tenantId)}`,
    fetcher: () => restClient
      .get('/v1/agent/deployments/marketplace/catalog', marketplaceCatalogEnvelopeSchema)
      .then(response => response.data),
    enabled: Boolean(tenantId),
    staleTime: 5 * 60_000,
  });
}

const behaviorSectionSchema = z.object({
  state: z.enum(['available', 'partial', 'unavailable']),
  data: z.unknown(),
  reason: z.string().optional(),
}).passthrough();

const agentBehaviorEnvelopeSchema = z.object({
  data: z.object({
    agent_ref: z.string(),
    source_truncated: z.boolean().optional(),
    source_status: z.string().optional(),
    sections: z.record(behaviorSectionSchema).nullable(),
  }).passthrough(),
  status: z.string(),
  timestamp: z.string(),
}).passthrough();

export type AgentBehaviorReadModel = z.infer<typeof agentBehaviorEnvelopeSchema>['data'];

/** Backend-owned Agent360 behavior read model (WO-110/111). Rendered, never recomputed. */
export function useAgentBehavior(agentRef: string) {
  const { scope } = useGraphContext();
  const tenantId = scope.tenant_id;
  return useQuery({
    key: `agent-360-behavior:${encodeURIComponent(tenantId)}:${encodeURIComponent(agentRef)}`,
    fetcher: () => restClient
      .get(`/v1/agent/agents/${encodeURIComponent(agentRef)}/behavior`, agentBehaviorEnvelopeSchema)
      .then(response => response.data),
    enabled: Boolean(tenantId && agentRef),
    staleTime: 30_000,
  });
}
