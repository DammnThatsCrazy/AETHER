/**
 * Agent Access Intelligence — tenant read surface.
 *
 * Wire shapes mirror `services/agent_access_intelligence/*` on the backend. The
 * one property every schema here exists to preserve: **a count the backend could
 * not compute arrives as `null`, and `null` is not zero.** Each response that can
 * be partially computed carries a `*_known` flag plus a `missing_inputs` list, and
 * every bounded read that truncated is disclosed (`truncated` / `sampled` /
 * `counts.scope`). Schemas therefore type counts as nullable rather than
 * defaulting them, so a missing count can never be silently coerced to 0 before
 * it reaches the UI.
 *
 * `authorized` on a reach edge is tri-state: `true` / `false` / `null`, where
 * `null` means the authorization read was unavailable — never "unauthorized".
 */
import { z } from 'zod';
import { useQuery } from '@aether/ui';
import { restClient } from '@aether-app/lib/api/rest/client';

const STALE = 60_000;
const KEY = 'agent-access';

const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });

const buildQS = (params: Record<string, string | number | undefined>): string => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
};

// ── Honesty primitives ───────────────────────────────────────────────────────

/**
 * A count that may be unknown. `null`/absent means "could not be computed";
 * it is NEVER defaulted to 0 — that would be an assertion about reality the
 * backend deliberately declined to make.
 */
const unknownableCount = z.number().nullish();

const missingInputs = z.array(z.string());

// ── Capability catalog ───────────────────────────────────────────────────────

export const capabilitySchema = z.object({
  capability_id: z.string(),
  capability_kind: z.string().nullish(),
  provider: z.string().nullish(),
  server_name: z.string().nullish(),
  server_url: z.string().nullish(),
  tool_name: z.string().nullish(),
  latest_risk_level: z.string().nullish(),
  discovery_state: z.string().nullish(),
  publisher_label: z.string().nullish(),
  first_seen_at: z.string().nullish(),
  last_seen_at: z.string().nullish(),
  observation_count: unknownableCount,
}).passthrough();

export const capabilityListSchema = z.object({
  items: z.array(capabilitySchema),
  count: unknownableCount,
}).passthrough();

// ── Access graph summary (the tenant inventory headline) ─────────────────────

export const accessGraphSummarySchema = z.object({
  tenant_id: z.string().nullish(),
  summary_known: z.boolean(),
  missing_inputs: missingInputs,
  basis: z.string().nullish(),
  complete: z.boolean().nullish(),
  counts: z.object({
    nodes: unknownableCount,
    edges: unknownableCount,
    agents: unknownableCount,
    servers: unknownableCount,
    capabilities: unknownableCount,
    edges_connects_to: unknownableCount,
    edges_exposes: unknownableCount,
    edges_authorized_for: unknownableCount,
    authorizations_active: unknownableCount,
  }).passthrough(),
  limits: z.record(z.number()).nullish(),
  /** False = nothing observed yet (a real empty tenant), not "unknown". */
  observed_any: z.boolean().nullish(),
  summary: z.string().nullish(),
}).passthrough();

// ── Risk findings ────────────────────────────────────────────────────────────

export const riskFindingSchema = z.object({
  code: z.string(),
  risk_level: z.string().nullish(),
  summary: z.string().nullish(),
  evidence: z.string().nullish(),
  capability_id: z.string().nullish(),
  source: z.string().nullish(),
}).passthrough();

export const riskFindingsSchema = z.object({
  items: z.array(riskFindingSchema),
  count: unknownableCount,
  limit: unknownableCount,
  offset: unknownableCount,
  counts: z.object({
    total: unknownableCount,
    /** "all_matching_findings" | "scanned_window_only" — a partial total must be labelled. */
    scope: z.string().nullish(),
    by_risk_level: z.record(z.number()),
    by_code: z.record(z.number()),
  }).passthrough(),
  identity: z.object({
    capabilities_examined: unknownableCount,
    declarations_read: unknownableCount,
    declarations_truncated: z.boolean().nullish(),
    declared: unknownableCount,
    drifted: unknownableCount,
    observed_only: unknownableCount,
    drift_detection_complete: z.boolean().nullish(),
  }).passthrough().nullish(),
  coverage: z.object({
    capabilities_examined: unknownableCount,
    scan_limit: unknownableCount,
    sampled: z.boolean().nullish(),
    catalog_truncated: z.boolean().nullish(),
    declarations_truncated: z.boolean().nullish(),
    complete: z.boolean().nullish(),
  }).passthrough().nullish(),
}).passthrough();

// ── Blast radius ─────────────────────────────────────────────────────────────

export const reachedCapabilitySchema = z.object({
  capability_id: z.string(),
  server_key: z.string().nullish(),
  provider: z.string().nullish(),
  tool_name: z.string().nullish(),
  capability_kind: z.string().nullish(),
  latest_risk_level: z.string().nullish(),
  /** "invoked" (observed using it) vs "server_reachable" (merely on a reachable server). */
  basis: z.string().nullish(),
  /** Tri-state. `null` = the authorization read was unavailable, NOT "unauthorized". */
  authorized: z.boolean().nullish(),
}).passthrough();

export const blastRadiusSchema = z.object({
  subject: z.object({ kind: z.string(), id: z.string() }).passthrough(),
  exposure_known: z.boolean(),
  missing_inputs: missingInputs,
  basis: z.string().nullish(),
  counts: z.record(unknownableCount),
  servers: z.array(z.string()),
  capabilities: z.array(reachedCapabilitySchema).nullish(),
  agents: z.array(z.object({
    agent_id: z.string(),
    authorized: z.boolean().nullish(),
  }).passthrough()).nullish(),
  summary: z.string().nullish(),
}).passthrough();

// ── Agent profiles ───────────────────────────────────────────────────────────

export const agentProfileIndexEntrySchema = z.object({
  agent_id: z.string(),
  servers_observed: unknownableCount,
  servers: z.array(z.string()),
  providers_observed: z.array(z.string()),
  capabilities_on_installations: unknownableCount,
  first_seen_at: z.string().nullish(),
  last_seen_at: z.string().nullish(),
  observations_recorded: unknownableCount,
}).passthrough();

export const agentProfileIndexSchema = z.object({
  items: z.array(agentProfileIndexEntrySchema),
  count: unknownableCount,
  basis: z.string().nullish(),
  counts: z.object({
    agents_observed: unknownableCount,
    scope: z.string().nullish(),
  }).passthrough().nullish(),
  scan_limit: unknownableCount,
  truncated: z.boolean().nullish(),
  complete: z.boolean().nullish(),
  note: z.string().nullish(),
}).passthrough();

export const agentProfileSchema = z.object({
  subject: z.object({ kind: z.string(), id: z.string() }).passthrough(),
  profile_known: z.boolean(),
  missing_inputs: missingInputs,
  basis: z.string().nullish(),
  identity: z.object({
    agent_id: z.string().nullish(),
    providers_observed: z.array(z.string()),
    servers_observed: z.array(z.string()),
    installation_ids: z.array(z.string()),
  }).passthrough(),
  observation: z.object({
    first_seen_at: z.string().nullish(),
    last_seen_at: z.string().nullish(),
    observations_recorded: unknownableCount,
    basis: z.string().nullish(),
  }).passthrough(),
  counts: z.record(unknownableCount),
  reach: z.object({
    servers: z.array(z.string()),
    capabilities: z.array(reachedCapabilitySchema),
  }).passthrough(),
  authorization: z.object({
    known: z.boolean().nullish(),
    authorizations_active: unknownableCount,
    capabilities_authorized: unknownableCount,
    capabilities_unauthorized: unknownableCount,
    scan_limit: unknownableCount,
  }).passthrough(),
  risk: z.object({
    known: z.boolean().nullish(),
    /** Counts by observed level. There is deliberately no composite score. */
    by_latest_risk_level: z.record(z.number()),
    note: z.string().nullish(),
  }).passthrough(),
  graph: z.object({
    neighborhood_known: z.boolean().nullish(),
    missing_inputs: missingInputs,
    truncated: z.boolean().nullish(),
    counts: z.record(unknownableCount),
    node_ids: z.array(z.string()),
    node_ids_sampled: z.boolean().nullish(),
  }).passthrough().nullish(),
  summary: z.string().nullish(),
}).passthrough();

// ── Authorizations ───────────────────────────────────────────────────────────

export const capabilityAuthorizationSchema = z.object({
  authorization_id: z.string().nullish(),
  agent_id: z.string().nullish(),
  capability_id: z.string().nullish(),
  server_ref: z.string().nullish(),
  scope: z.string().nullish(),
  /** Derived server-side from revoked_at/ends_at/starts_at: active|revoked|expired|pending. */
  state: z.string().nullish(),
  starts_at: z.string().nullish(),
  ends_at: z.string().nullish(),
  revoked_at: z.string().nullish(),
  created_at: z.string().nullish(),
}).passthrough();

export const capabilityAuthorizationListSchema = z.object({
  items: z.array(capabilityAuthorizationSchema),
  count: unknownableCount,
}).passthrough();

// ── Inferred types ───────────────────────────────────────────────────────────

export type Capability = z.infer<typeof capabilitySchema>;
export type AccessGraphSummary = z.infer<typeof accessGraphSummarySchema>;
export type RiskFinding = z.infer<typeof riskFindingSchema>;
export type RiskFindingsResult = z.infer<typeof riskFindingsSchema>;
export type ReachedCapability = z.infer<typeof reachedCapabilitySchema>;
export type BlastRadius = z.infer<typeof blastRadiusSchema>;
export type AgentProfileIndexEntry = z.infer<typeof agentProfileIndexEntrySchema>;
export type AgentProfileIndex = z.infer<typeof agentProfileIndexSchema>;
export type AgentProfile = z.infer<typeof agentProfileSchema>;
export type CapabilityAuthorization = z.infer<typeof capabilityAuthorizationSchema>;

// ── Fetchers (via the shared REST client — never bare fetch) ─────────────────

export const fetchCapabilityCatalog = (params?: { limit?: number; offset?: number }) =>
  restClient
    .get(`/v1/capability-catalog${buildQS({ ...params })}`, wrap(capabilityListSchema))
    .then(r => r.data);

export const fetchAccessGraphSummary = () =>
  restClient
    .get('/v1/capability-graph/summary', wrap(accessGraphSummarySchema))
    .then(r => r.data);

export const fetchRiskFindings = (params?: { code?: string; limit?: number; offset?: number }) =>
  restClient
    .get(`/v1/capability-risk/findings${buildQS({ ...params })}`, wrap(riskFindingsSchema))
    .then(r => r.data);

export const fetchAgentBlastRadius = (agentId: string) =>
  restClient
    .get(
      `/v1/capability-risk/blast-radius${buildQS({ agent_id: agentId })}`,
      wrap(blastRadiusSchema),
    )
    .then(r => r.data);

export const fetchAgentProfiles = (params?: { limit?: number; offset?: number }) =>
  restClient
    .get(`/v1/capability-profiles${buildQS({ ...params })}`, wrap(agentProfileIndexSchema))
    .then(r => r.data);

export const fetchAgentProfile = (agentId: string) =>
  restClient
    .get(
      `/v1/capability-profiles/${encodeURIComponent(agentId)}`,
      wrap(agentProfileSchema),
    )
    .then(r => r.data);

export const fetchCapabilityAuthorizations = (params?: {
  agent_id?: string;
  state?: string;
  limit?: number;
}) =>
  restClient
    .get(
      `/v1/capability-authorizations${buildQS({ ...params })}`,
      wrap(capabilityAuthorizationListSchema),
    )
    .then(r => r.data);

// ── Hooks ────────────────────────────────────────────────────────────────────

/** Tenant-wide observed access inventory (agents, servers, capabilities, reach). */
export function useAccessInventory() {
  return useQuery({
    key: `${KEY}:graph-summary`,
    fetcher: fetchAccessGraphSummary,
    staleTime: STALE,
  });
}

export function useCapabilityCatalog(params?: { limit?: number }) {
  return useQuery({
    key: `${KEY}:catalog:${params?.limit ?? 100}`,
    fetcher: () => fetchCapabilityCatalog({ limit: 100, ...params }),
    staleTime: STALE,
  });
}

export function useCapabilityRiskFindings(params?: { code?: string; limit?: number }) {
  return useQuery({
    key: `${KEY}:findings:${params?.code ?? 'all'}:${params?.limit ?? 100}`,
    fetcher: () => fetchRiskFindings({ limit: 100, ...params }),
    staleTime: 30_000,
  });
}

export function useAgentProfiles(params?: { limit?: number }) {
  return useQuery({
    key: `${KEY}:profiles:${params?.limit ?? 100}`,
    fetcher: () => fetchAgentProfiles({ limit: 100, ...params }),
    staleTime: STALE,
  });
}

export function useAgentProfile(agentId: string) {
  return useQuery({
    key: `${KEY}:profile:${agentId}`,
    fetcher: () => fetchAgentProfile(agentId),
    staleTime: 30_000,
    enabled: !!agentId,
  });
}

export function useAgentBlastRadius(agentId: string) {
  return useQuery({
    key: `${KEY}:blast-radius:${agentId}`,
    fetcher: () => fetchAgentBlastRadius(agentId),
    staleTime: 30_000,
    enabled: !!agentId,
  });
}

export function useCapabilityAuthorizations(params?: { agent_id?: string; state?: string }) {
  return useQuery({
    key: `${KEY}:authorizations:${params?.agent_id ?? 'all'}:${params?.state ?? 'all'}`,
    fetcher: () => fetchCapabilityAuthorizations({ limit: 100, ...params }),
    staleTime: STALE,
  });
}
