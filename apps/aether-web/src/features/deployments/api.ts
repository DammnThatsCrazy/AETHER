import { z } from 'zod';
import { restClient, RestClientError } from '@aether-app/lib/api/rest/client';
import {
  externalPlatforms,
  agentDeploymentEnvironments,
  agentDeploymentConsentModes,
  agentDeploymentStatuses,
} from '@aether/shared';
import type {
  ExternalPlatform,
  AgentDeploymentEnvironment,
  AgentDeploymentConsentMode,
} from '@aether/shared';

const unknownSchema = z.unknown();
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

// ── Wire schemas (snake_case per backend) ──────────────────────────────────────

export const agentDeploymentSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  agent_id: z.string(),
  display_name: z.string(),
  description: z.string().nullish(),
  external_platform: z.enum(externalPlatforms),
  environment: z.enum(agentDeploymentEnvironments),
  status: z.enum(agentDeploymentStatuses),
  consent_mode: z.enum(agentDeploymentConsentModes),
  allowed_event_families: z.array(z.string()),
  required_consent_purposes: z.array(z.string()),
  capability_scopes: z.array(z.string()),
  event_count_24h: z.number(),
  accepted_count_24h: z.number(),
  rejected_count_24h: z.number(),
  error_count_24h: z.number(),
  consent_blocked_count_24h: z.number(),
  health_score: z.number().nullish(),
  first_seen_at: z.string().nullish(),
  last_seen_at: z.string().nullish(),
  last_event_at: z.string().nullish(),
  created_at: z.string(),
  updated_at: z.string(),
}).passthrough();

export type AgentDeploymentRecord = z.infer<typeof agentDeploymentSchema>;

// Tolerant list shape: bare array or { deployments: [...] }.
const deploymentListSchema = z.union([
  z.array(agentDeploymentSchema),
  z.object({ deployments: z.array(agentDeploymentSchema) }).passthrough(),
]);

export const agentDeploymentHealthSchema = z.object({
  event_count_24h: z.number(),
  accepted_count_24h: z.number(),
  rejected_count_24h: z.number(),
  error_count_24h: z.number(),
  consent_blocked_count_24h: z.number(),
  health_score: z.number().nullish(),
}).passthrough();

export type AgentDeploymentHealthRecord = z.infer<typeof agentDeploymentHealthSchema>;

export const agentDeploymentActivitySchema = z.object({
  id: z.string(),
  deployment_id: z.string().optional(),
  action: z.string(),
  actor: z.string(),
  request_id: z.string().nullish(),
  detail: z.record(z.unknown()).nullish(),
  occurred_at: z.string(),
}).passthrough();

export type AgentDeploymentActivityRecord = z.infer<typeof agentDeploymentActivitySchema>;

// Tolerant activity shape: bare array or { entries: [...] } / { activity: [...] }.
const activityListSchema = z.union([
  z.array(agentDeploymentActivitySchema),
  z.object({ entries: z.array(agentDeploymentActivitySchema) }).passthrough(),
  z.object({ activity: z.array(agentDeploymentActivitySchema) }).passthrough(),
]);

// ── Fetchers ───────────────────────────────────────────────────────────────────

export interface DeploymentListParams {
  readonly status?: string;
  readonly platform?: string;
}

export interface DeploymentListResult {
  readonly deployments: AgentDeploymentRecord[];
  /** True when the backend reports agent telemetry is not enabled (404/501). */
  readonly notConfigured: boolean;
}

export async function fetchAgentDeployments(params?: DeploymentListParams): Promise<DeploymentListResult> {
  try {
    const r = await restClient.get(
      `/v1/agent/deployments${buildQS({ status: params?.status, platform: params?.platform })}`,
      wrap(deploymentListSchema),
    );
    const deployments = Array.isArray(r.data) ? r.data : r.data.deployments;
    return { deployments, notConfigured: false };
  } catch (err) {
    if (err instanceof RestClientError && (err.status === 404 || err.status === 501)) {
      return { deployments: [], notConfigured: true };
    }
    throw err;
  }
}

export function fetchAgentDeployment(id: string): Promise<AgentDeploymentRecord> {
  return restClient
    .get(`/v1/agent/deployments/${encodeURIComponent(id)}`, wrap(agentDeploymentSchema))
    .then(r => r.data);
}

export function fetchAgentDeploymentHealth(id: string): Promise<AgentDeploymentHealthRecord> {
  return restClient
    .get(`/v1/agent/deployments/${encodeURIComponent(id)}/health`, wrap(agentDeploymentHealthSchema))
    .then(r => r.data);
}

export function fetchAgentDeploymentActivity(id: string): Promise<AgentDeploymentActivityRecord[]> {
  return restClient
    .get(`/v1/agent/deployments/${encodeURIComponent(id)}/activity`, wrap(activityListSchema))
    .then(r => {
      if (Array.isArray(r.data)) return r.data;
      if ('entries' in r.data && Array.isArray(r.data.entries)) return r.data.entries;
      if ('activity' in r.data && Array.isArray(r.data.activity)) return r.data.activity;
      return [];
    });
}

export interface CreateAgentDeploymentInput {
  readonly display_name: string;
  readonly agent_id: string;
  readonly external_platform: ExternalPlatform;
  readonly environment: AgentDeploymentEnvironment;
  readonly consent_mode: AgentDeploymentConsentMode;
  readonly description?: string;
  readonly allowed_event_families?: string[];
  readonly required_consent_purposes?: string[];
  readonly capability_scopes?: string[];
}

export function createAgentDeployment(input: CreateAgentDeploymentInput): Promise<AgentDeploymentRecord> {
  return restClient
    .post('/v1/agent/deployments', wrap(agentDeploymentSchema), input)
    .then(r => r.data);
}

export function updateAgentDeployment(
  id: string,
  patch: Partial<CreateAgentDeploymentInput>,
): Promise<AgentDeploymentRecord> {
  return restClient
    .patch(`/v1/agent/deployments/${encodeURIComponent(id)}`, wrap(agentDeploymentSchema), patch)
    .then(r => r.data);
}

export type DeploymentLifecycleAction = 'pause' | 'reactivate' | 'revoke' | 'archive';

function lifecycleAction(id: string, action: DeploymentLifecycleAction): Promise<unknown> {
  return restClient
    .post(`/v1/agent/deployments/${encodeURIComponent(id)}/${action}`, wrap(unknownSchema), {})
    .then(r => r.data);
}

export function pauseAgentDeployment(id: string): Promise<unknown> {
  return lifecycleAction(id, 'pause');
}

export function reactivateAgentDeployment(id: string): Promise<unknown> {
  return lifecycleAction(id, 'reactivate');
}

export function revokeAgentDeployment(id: string): Promise<unknown> {
  return lifecycleAction(id, 'revoke');
}

export function archiveAgentDeployment(id: string): Promise<unknown> {
  return lifecycleAction(id, 'archive');
}
