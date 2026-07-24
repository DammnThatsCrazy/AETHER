/**
 * KYBER operator adapter — Agent Access Intelligence ops (/v1/kyber/capability-ops).
 *
 * Cross-tenant authorization posture, declared-vs-observed identity drift, and a
 * tenant-bounded blast-radius review. All three are operator-gated server-side
 * (`require_kyber_operator`); a non-operator never gets a body to render.
 *
 * ── The contract that shapes every type in this file ──────────────────────────
 *
 * These endpoints deliberately answer `null` — never `0` — for any count they could
 * not compute, alongside `totals_known` / `exposure_known: false` and a `missing_inputs`
 * list naming each absent input. `authorized` is tri-state for the same reason: `null`
 * means "we could not read the authorizations", which is NOT "denied".
 *
 * So every count below is typed `number | null` and every schema uses `.nullable()`,
 * never `.default(0)` and never `?? 0` at the call site. Coercing a null to zero here
 * would turn "we could not read this tenant's authorizations" into "this tenant has no
 * unauthorized capabilities" — the one output that makes an operator close an
 * investigation that should have stayed open.
 */

import { useQuery } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@kyber/lib/api';

const KEY_PREFIX = 'agent-access-ops';
const STALE = 30_000;

// ── Envelope ─────────────────────────────────────────────────────────────────

const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema }).passthrough();

const buildQS = (params: Record<string, string | number | undefined>): string => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
};

/**
 * A count the server may have been unable to compute. `.nullable()` is load-bearing:
 * with `.default(0)` a null would silently become a confident zero before it ever
 * reached a component.
 */
const count = z.number().nullable();

// ── Authority posture ────────────────────────────────────────────────────────

const authorityTenantSchema = z.object({
  tenant_id: z.string(),
  known: z.boolean(),
  missing_inputs: z.array(z.string()),
  counts_by_state: z.record(count),
  authorizations_scanned: z.number(),
  scan_limit: z.number(),
}).passthrough();

export type AuthorityTenantRow = z.infer<typeof authorityTenantSchema>;

const tenantDiscoverySchema = z.object({
  tenants_examined: z.number(),
  distinct_tenants_seen: z.number(),
  complete: z.boolean(),
}).passthrough();

export type TenantDiscovery = z.infer<typeof tenantDiscoverySchema>;

const authorityPostureSchema = z.object({
  scope: z.string(),
  totals_known: z.boolean(),
  missing_inputs: z.array(z.string()),
  counts_by_state: z.record(count),
  tenants: z.array(authorityTenantSchema),
  tenant_discovery: tenantDiscoverySchema,
  summary: z.string(),
}).passthrough();

export type AuthorityPosture = z.infer<typeof authorityPostureSchema>;

// ── Drift ────────────────────────────────────────────────────────────────────

const driftFindingSchema = z.object({
  tenant_id: z.string(),
  code: z.string(),
  risk_level: z.string(),
  summary: z.string(),
  evidence: z.string().nullish(),
  capability_id: z.string().nullish(),
  source: z.string().nullish(),
}).passthrough();

export type DriftFinding = z.infer<typeof driftFindingSchema>;

const driftTenantSchema = z.object({
  tenant_id: z.string(),
  known: z.boolean(),
  missing_inputs: z.array(z.string()),
  counts: z.record(count),
}).passthrough();

export type DriftTenantRow = z.infer<typeof driftTenantSchema>;

const driftPostureSchema = z.object({
  scope: z.string(),
  totals_known: z.boolean(),
  missing_inputs: z.array(z.string()),
  counts: z.record(count),
  findings: z.array(driftFindingSchema),
  findings_scope: z.string(),
  findings_page_limit: z.number(),
  tenants: z.array(driftTenantSchema),
  tenant_discovery: tenantDiscoverySchema,
  summary: z.string(),
}).passthrough();

export type DriftPosture = z.infer<typeof driftPostureSchema>;

/** `findings` is evidence from an incomplete scan, not the whole set, when this holds. */
export const DRIFT_FINDINGS_PARTIAL = 'evidence_only_incomplete_scan';

// ── Blast radius ─────────────────────────────────────────────────────────────

const blastCapabilitySchema = z.object({
  capability_id: z.string(),
  server_key: z.string().nullish(),
  provider: z.string().nullish(),
  tool_name: z.string().nullish(),
  latest_risk_level: z.string().nullish(),
  basis: z.string(),
  // Tri-state. `null` is "unknown", never "denied".
  authorized: z.boolean().nullable(),
}).passthrough();

export type BlastCapability = z.infer<typeof blastCapabilitySchema>;

const blastAgentSchema = z.object({
  agent_id: z.string(),
  authorized: z.boolean().nullable(),
}).passthrough();

export type BlastAgent = z.infer<typeof blastAgentSchema>;

const blastRadiusSchema = z.object({
  tenant_id: z.string(),
  subject: z.object({ kind: z.string(), id: z.string() }).passthrough(),
  exposure_known: z.boolean(),
  missing_inputs: z.array(z.string()),
  basis: z.string(),
  counts: z.record(count),
  servers: z.array(z.string()),
  capabilities: z.array(blastCapabilitySchema).optional(),
  agents: z.array(blastAgentSchema).optional(),
  summary: z.string(),
}).passthrough();

export type BlastRadius = z.infer<typeof blastRadiusSchema>;

// ── Fetchers ─────────────────────────────────────────────────────────────────

export function fetchAuthorityPosture(): Promise<AuthorityPosture> {
  return restClient
    .get('/v1/kyber/capability-ops/authority', wrap(authorityPostureSchema))
    .then(r => r.data);
}

export function fetchDriftPosture(findingsPerTenant?: number): Promise<DriftPosture> {
  return restClient
    .get(
      `/v1/kyber/capability-ops/drift${buildQS({ findings_per_tenant: findingsPerTenant })}`,
      wrap(driftPostureSchema),
    )
    .then(r => r.data);
}

export interface BlastRadiusQuery {
  readonly tenantId: string;
  readonly agentId?: string | undefined;
  readonly capabilityId?: string | undefined;
}

export function fetchBlastRadius(query: BlastRadiusQuery): Promise<BlastRadius> {
  return restClient
    .get(
      `/v1/kyber/capability-ops/blast-radius${buildQS({
        tenant_id: query.tenantId,
        agent_id: query.agentId,
        capability_id: query.capabilityId,
      })}`,
      wrap(blastRadiusSchema),
    )
    .then(r => r.data);
}

// ── Hooks ────────────────────────────────────────────────────────────────────

export interface QueryState<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
}

export function useAuthorityPosture(): QueryState<AuthorityPosture> {
  const { data, isLoading, error, refetch } = useQuery<AuthorityPosture>({
    key: `${KEY_PREFIX}:authority`,
    fetcher: fetchAuthorityPosture,
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

export function useDriftPosture(findingsPerTenant?: number): QueryState<DriftPosture> {
  const { data, isLoading, error, refetch } = useQuery<DriftPosture>({
    key: `${KEY_PREFIX}:drift:${findingsPerTenant ?? 'default'}`,
    fetcher: () => fetchDriftPosture(findingsPerTenant),
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Disabled until a tenant is named — the endpoint requires one, by design. */
export function useBlastRadius(query: BlastRadiusQuery | null): QueryState<BlastRadius> {
  const { data, isLoading, error, refetch } = useQuery<BlastRadius>({
    key: `${KEY_PREFIX}:blast:${query?.tenantId ?? 'none'}:${query?.agentId ?? ''}:${query?.capabilityId ?? ''}`,
    fetcher: () => fetchBlastRadius(query as BlastRadiusQuery),
    staleTime: STALE,
    enabled: query !== null && query.tenantId.trim() !== '',
  });
  return { data, loading: isLoading, error, refresh: refetch };
}
