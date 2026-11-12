import { useQuery } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@aether-app/lib/api/rest/client';
import { useGraphContext } from '@aether/ui/exploration';

const disclosureSchema = z.object({
  as_of: z.string().nullable().optional(),
  computed_at: z.string().nullable().optional(),
  completeness: z.string(),
  truncated: z.boolean().optional(),
  truncation_reasons: z.array(z.string()),
}).passthrough();

function envelope<T extends z.ZodTypeAny>(data: T) {
  return z.object({ data, status: z.string(), timestamp: z.string() }).passthrough();
}

const summarySchema = z.object({
  unique_agent_definitions: z.number().nullable().optional(),
  agent_instances: z.number().nullable().optional(),
  agent_runs: z.number().nullable().optional(),
  active_agents: z.number().nullable().optional(),
  historical_agents: z.number().nullable().optional(),
  direct_agents: z.number().nullable().optional(),
  indirect_agents: z.number().nullable().optional(),
  probabilistic_agents: z.number().nullable().optional(),
  unresolved_agents: z.number().nullable().optional(),
  revoked_agents: z.number().nullable().optional(),
  out_of_scope_agents: z.number().nullable().optional(),
  risk_flagged_agents: z.number().nullable().optional(),
  max_delegation_depth: z.number().nullable().optional(),
  tools_used: z.number().nullable().optional(),
  services_used: z.number().nullable().optional(),
  verified_links: z.number().nullable().optional(),
  inferred_links: z.number().nullable().optional(),
  disclosure: disclosureSchema,
}).passthrough();

const rowSchema = z.object({
  agent_entity_id: z.string(),
  attribution_class: z.string(),
  evidence_class: z.string().optional(),
  relationship_type: z.string().optional(),
  depth: z.number().optional(),
  active_state: z.string().optional(),
  lineage_status: z.string().optional(),
  authority_resolution_status: z.string().nullable().optional(),
  principal_entity_id: z.string().optional(),
  competing_principal_ids: z.array(z.string()).optional(),
}).passthrough();

const clusterSchema = z.object({
  cluster_id: z.string(),
  kind: z.string(),
  member_count: z.number(),
  attribution_class: z.string(),
  implies_common_control: z.boolean().optional(),
  bases: z.array(z.object({ basis: z.string(), detail: z.string().nullable().optional() }).passthrough()),
}).passthrough();

const treeNodeSchema = z.object({
  agent_entity_id: z.string(),
  depth: z.number(),
  descendant_count: z.number().nullable().optional(),
  collapsed: z.boolean().optional(),
  lineage_status: z.string().optional(),
  attribution_class: z.string().optional(),
}).passthrough();

function pageSchema<T extends z.ZodTypeAny>(item: T) {
  return z.object({
    items: z.array(item),
    next_cursor: z.string().nullable().optional(),
    page_size: z.number().optional(),
    disclosure: disclosureSchema,
  }).passthrough();
}

const agentDetailSchema = z.object({
  agent_entity_id: z.string(),
  node: z.record(z.unknown()).nullable(),
  principals: z.array(rowSchema),
  ancestors: z.array(z.record(z.unknown())),
  counts: z.record(z.unknown()),
  disclosure: disclosureSchema,
}).passthrough();

export type LineageDisclosure = z.infer<typeof disclosureSchema>;
export type LineageSummaryView = z.infer<typeof summarySchema>;
export type LineageRowView = z.infer<typeof rowSchema>;
export type LineageClusterView = z.infer<typeof clusterSchema>;
export type LineageTreeNodeView = z.infer<typeof treeNodeSchema>;
export type AgentLineageDetail = z.infer<typeof agentDetailSchema>;

function principalPath(principalId: string, leaf: string): string {
  return `/v1/agent-lineage/principals/${encodeURIComponent(principalId)}/${leaf}`;
}

export function useLineageSummary(principalId: string) {
  const { scope } = useGraphContext();
  return useQuery({
    key: `agent-lineage-summary:${encodeURIComponent(scope.tenant_id)}:${encodeURIComponent(principalId)}`,
    fetcher: () => restClient
      .get(principalPath(principalId, 'summary'), envelope(summarySchema))
      .then(response => response.data),
    enabled: Boolean(scope.tenant_id && principalId),
    staleTime: 30_000,
  });
}

export function useLineageClusters(principalId: string) {
  const { scope } = useGraphContext();
  return useQuery({
    key: `agent-lineage-clusters:${encodeURIComponent(scope.tenant_id)}:${encodeURIComponent(principalId)}`,
    fetcher: () => restClient
      .get(`${principalPath(principalId, 'clusters')}?page_size=8`, envelope(pageSchema(clusterSchema)))
      .then(response => response.data),
    enabled: Boolean(scope.tenant_id && principalId),
    staleTime: 30_000,
  });
}

export function fetchLineageAgents(principalId: string, query: Record<string, string>, cursor?: string | null) {
  const params = new URLSearchParams({ ...query, page_size: '25' });
  if (cursor) params.set('cursor', cursor);
  return restClient
    .get(`${principalPath(principalId, 'agents')}?${params.toString()}`, envelope(pageSchema(rowSchema)))
    .then(response => response.data);
}

export function fetchLineageTree(principalId: string, parent?: string | null) {
  const params = new URLSearchParams({ page_size: '25' });
  if (parent) params.set('parent', parent);
  return restClient
    .get(`${principalPath(principalId, 'tree')}?${params.toString()}`, envelope(pageSchema(treeNodeSchema)))
    .then(response => response.data);
}

export function useAgentLineageDetail(agentId: string) {
  const { scope } = useGraphContext();
  return useQuery({
    key: `agent-lineage-agent:${encodeURIComponent(scope.tenant_id)}:${encodeURIComponent(agentId)}`,
    fetcher: () => restClient
      .get(`/v1/agent-lineage/agents/${encodeURIComponent(agentId)}`, envelope(agentDetailSchema))
      .then(response => response.data),
    enabled: Boolean(scope.tenant_id && agentId),
    staleTime: 30_000,
  });
}

export function fetchAgentDescendants(agentId: string, cursor?: string | null) {
  const params = new URLSearchParams({ page_size: '25' });
  if (cursor) params.set('cursor', cursor);
  return restClient
    .get(`/v1/agent-lineage/agents/${encodeURIComponent(agentId)}/descendants?${params.toString()}`,
      envelope(pageSchema(z.record(z.unknown()))))
    .then(response => response.data);
}
