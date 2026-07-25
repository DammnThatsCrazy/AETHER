/**
 * KYBER operator adapter — the Kyber Graph plane (`/v1/kyber/graph`).
 *
 * Eight backend routes across three disclosure levels, in the order the backend
 * itself puts them (`services/kyber/graph/routes.py`): platform topology (D0),
 * fleet aggregates and cohorts (D1), a bounded blast-radius review (D0), and —
 * only with an active purpose-bound scope — one tenant's own graph (D3).
 *
 * ── The three contracts that shape every type in this file ────────────────────
 *
 * 1. **`totals_known: false` means there is no total.** The fleet and platform
 *    surfaces still return `row_count` / `tenant_count` as real integers when a
 *    read was partial (unlike the agent-access plane, which nulls its counts).
 *    Those integers are a count of what was READ, not a total, so every count is
 *    typed `number | null` with `.nullable()` and the page gates on
 *    `totals_known` before it is allowed to call any of them a total. There is no
 *    `.default(0)` and no `?? 0` anywhere below.
 *
 * 2. **Stale is not healthy.** `services/kyber/graph/fleet.py` states the rule
 *    directly: a stale row rendered green converts "we do not know" into "it is
 *    fine" and an operator stops looking. So `stale`, `oldest_computed_at` and
 *    `oldest_row_age_seconds` are required fields on every fleet shape here, not
 *    optional decoration.
 *
 * 3. **A 403 is an answer, not a failure.** The D3 tenant reads run an ordered
 *    gate that denies when no active tenant scope names that tenant. That is an
 *    expected, explainable state with a backend-supplied reason, so it is mapped
 *    to a typed `AccessDenial` value rather than thrown into a generic error
 *    banner. Routing is not a grant: every surface here can come back denied and
 *    each one renders its own forbidden state.
 */

import { useMutation, useQuery } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@kyber/lib/api';

const KEY_PREFIX = 'kyber-graph';
const STALE = 30_000;

// ── Envelope ─────────────────────────────────────────────────────────────────

/** Every handler returns `APIResponse(...).to_dict()` — `{ data, meta, ... }`. */
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
 * A count the server may have been unable to compute, or that the page may not
 * be allowed to present as a total. `.nullable()` is load-bearing: `.default(0)`
 * would turn "we could not read this" into a confident zero before it ever
 * reached a component.
 */
const count = z.number().nullable();

// ── D0 — platform topology ───────────────────────────────────────────────────

const platformNodeSchema = z
  .object({
    node_key: z.string().nullable(),
    node_type: z.string().nullable(),
    display_name: z.string().nullable(),
    environment: z.string().nullable(),
    health: z.string().nullable(),
  })
  .passthrough();

export type PlatformNode = z.infer<typeof platformNodeSchema>;

const platformGraphSchema = z
  .object({
    available: z.boolean(),
    environment: z.string().nullable(),
    nodes: z.record(z.array(platformNodeSchema)),
    counts: z.record(count),
    // Absent entirely on the store-unavailable branch, so optional AND nullable:
    // "the platform has no nodes" and "we could not count them" are different
    // answers and neither may render as 0.
    node_count: count.optional(),
    by_health: z.record(count),
    state: z.string(),
    truncated: z.boolean(),
    totals_known: z.boolean(),
    missing_inputs: z.array(z.string()),
    queries_issued: z.number(),
    computed_at: z.string(),
  })
  .passthrough();

export type PlatformGraph = z.infer<typeof platformGraphSchema>;

// ── D1 — fleet ───────────────────────────────────────────────────────────────

const scoreSummarySchema = z
  .object({
    count: count,
    min: z.number().nullable(),
    mean: z.number().nullable(),
    max: z.number().nullable(),
  })
  .passthrough();

export type ScoreSummary = z.infer<typeof scoreSummarySchema>;

/**
 * One projection's fold. Freshness is required, not optional: an aggregate
 * without `stale` / `oldest_computed_at` cannot be acted on.
 */
const fleetAggregateSchema = z
  .object({
    row_count: count,
    tenant_count: count,
    by_state: z.record(count),
    by_region: z.record(count),
    by_dimension: z.record(count),
    score: scoreSummarySchema,
    state: z.string(),
    stale: z.boolean(),
    oldest_computed_at: z.string().nullable(),
    oldest_row_age_seconds: z.number().nullable(),
    max_age_seconds: z.number(),
    totals_known: z.boolean(),
    missing_inputs: z.array(z.string()),
    truncated: z.boolean(),
    computed_at: z.string(),
    // Present only on `GET /fleet/{projection}`.
    projection: z.string().nullish(),
    scan_limit: z.number().nullish(),
  })
  .passthrough();

export type FleetAggregate = z.infer<typeof fleetAggregateSchema>;

const fleetSummarySchema = z
  .object({
    environment: z.string().nullable(),
    projections: z.record(fleetAggregateSchema),
    projection_count: z.number(),
    tenant_count: count,
    state: z.string(),
    by_state: z.record(count),
    stale: z.boolean(),
    oldest_computed_at: z.string().nullable(),
    oldest_row_age_seconds: z.number().nullable(),
    max_age_seconds: z.number(),
    totals_known: z.boolean(),
    missing_inputs: z.array(z.string()),
    truncated: z.boolean(),
    queries_issued: z.number(),
    scan_limit: z.number(),
    computed_at: z.string(),
  })
  .passthrough();

export type FleetSummary = z.infer<typeof fleetSummarySchema>;

/** States that are themselves an admission of missing input — never "fine". */
export const UNKNOWN_STATES: readonly string[] = ['unknown', 'no_data'];

// ── D1 — cohorts ─────────────────────────────────────────────────────────────

const cohortDefinitionSchema = z
  .object({
    cohort_id: z.string(),
    name: z.string(),
    filters: z.record(z.unknown()),
    minimum_size: z.number(),
    created_by: z.string().nullish(),
    created_at: z.string(),
  })
  .passthrough();

export type CohortDefinition = z.infer<typeof cohortDefinitionSchema>;

const cohortDefineResultSchema = z
  .object({
    cohort: cohortDefinitionSchema,
    /** True when the backend raised `minimum_size` or dropped filter keys. */
    normalised: z.boolean(),
  })
  .passthrough();

export type CohortDefineResult = z.infer<typeof cohortDefineResultSchema>;

/**
 * A cohort evaluation, suppressed or not.
 *
 * The suppressed branch deliberately omits `member_count` (it is `null`) and
 * every distribution: at size one or two the count IS the identification. The
 * page must therefore never fall back to "0 members" — the whole point of
 * `reason` is that suppression is distinguishable from absence.
 */
const cohortEvaluationSchema = z
  .object({
    cohort_id: z.string(),
    name: z.string(),
    filters: z.record(z.unknown()),
    environment: z.string().nullish(),
    minimum_size: z.number(),
    queries_issued: z.number(),
    computed_at: z.string(),
    suppressed: z.boolean(),
    reason: z.string().nullable(),
    member_count: count,
    members: z.array(z.string()).nullable(),
    state: z.string(),
    stale: z.boolean(),
    totals_known: z.boolean(),
    missing_inputs: z.array(z.string()),
    truncated: z.boolean(),
    // Disclosed branch only.
    members_disclosure_gated: z.boolean().optional(),
    row_count: count.optional(),
    by_state: z.record(count).optional(),
    by_region: z.record(count).optional(),
    by_dimension: z.record(count).optional(),
    score: scoreSummarySchema.optional(),
    oldest_computed_at: z.string().nullish(),
    oldest_row_age_seconds: z.number().nullish(),
    max_age_seconds: z.number().optional(),
  })
  .passthrough();

export type CohortEvaluation = z.infer<typeof cohortEvaluationSchema>;

/** `reason` when a cohort resolved below its minimum size. */
export const COHORT_SUPPRESSION_REASON = 'below_minimum_cohort_size';

/** Floor the backend raises any lower `minimum_size` to (`cohorts.py`). */
export const ABSOLUTE_MINIMUM_COHORT_SIZE = 3;

/** The only filter keys the backend evaluates; anything else is dropped. */
export const SUPPORTED_COHORT_FILTERS: readonly string[] = [
  'projection',
  'environment',
  'region',
  'dimension',
  'state',
  'states',
  'min_score',
  'max_score',
];

// ── D0 — blast radius ────────────────────────────────────────────────────────

const blastRadiusSchema = z
  .object({
    subject_type: z.string(),
    subject_id: z.string(),
    environment: z.string().nullish(),
    exposure_known: z.boolean(),
    missing_inputs: z.array(z.string()),
    affected_services: z.array(z.string()),
    affected_features: z.array(z.string()),
    affected_tenants: z.array(z.string()),
    affected_graph_domains: z.array(z.string()),
    customer_visible: z.boolean(),
    traversal_depth: z.number(),
    truncated: z.boolean(),
    confidence: z.number(),
    evidence_references: z.array(z.string()),
    computed_at: z.string(),
    /** Set when the subject is an agent/capability owned by another plane. */
    delegated_surface: z.string().nullish(),
  })
  .passthrough();

export type BlastRadius = z.infer<typeof blastRadiusSchema>;

/** Backend ceiling from `blast_radius.MAX_DEPTH`. */
export const MAX_TRAVERSAL_DEPTH = 3;

// ── D3 — one scoped tenant ───────────────────────────────────────────────────

const tenantVertexSchema = z
  .object({
    vertex_id: z.string().nullable(),
    vertex_type: z.string().nullable(),
    properties: z.record(z.unknown()),
  })
  .passthrough();

export type TenantVertex = z.infer<typeof tenantVertexSchema>;

const tenantVisibleSchema = z
  .object({
    tenant_id: z.string(),
    vertex_type: z.string().nullish(),
    vertices: z.array(tenantVertexSchema),
    vertex_count: count,
    truncated: z.boolean(),
  })
  .passthrough();

const operatorDiagnosticsSchema = z
  .object({
    surface: z.string(),
    capability: z.string(),
    granted_disclosure: z.string().nullish(),
    identifiers_masked: z.boolean(),
    scope_id: z.string().nullish(),
    purpose: z.string().nullish(),
    requested_limit: z.number(),
    budget: z.number(),
    result_count: count,
    truncated: z.boolean(),
    evidence_disclosure_gated: z.boolean(),
    evidence_reference_count: count,
    evidence_references: z.array(z.string()),
    missing_inputs: z.array(z.string()),
    exposure_known: z.boolean(),
    computed_at: z.string(),
  })
  .passthrough();

export type TenantGraphDiagnostics = z.infer<typeof operatorDiagnosticsSchema>;

/**
 * Two-keyed on purpose: `tenantVisible` is what a Tenant Mirror parity check
 * may compare against the tenant's own API, `operatorDiagnostics` is
 * operator-only metadata the tenant never sees.
 */
const tenantGraphSchema = z
  .object({
    tenantVisible: tenantVisibleSchema,
    operatorDiagnostics: operatorDiagnosticsSchema,
  })
  .passthrough();

export type TenantGraph = z.infer<typeof tenantGraphSchema>;

// ── Denials ──────────────────────────────────────────────────────────────────

/**
 * A backend refusal, kept as a value rather than an exception.
 *
 * The D3 gate denies with a named reason (`scope_missing`, `scope_expired`,
 * `scope_tenant_mismatch`, `disclosure_exceeded`, `graph_unavailable`, …). An
 * operator who sees "Request failed" learns nothing; an operator who sees
 * "requires an active tenant scope" knows exactly what to go and get.
 */
export interface AccessDenial {
  readonly denied: true;
  /** True for the D3 tenant routes, whose gate requires an active scope. */
  readonly scopeRequired: boolean;
  /** The backend's own explanation. Never invented here. */
  readonly reason: string;
  /** The gate step that refused, when the backend named one. */
  readonly denialReason: string | null;
}

/** Either the payload, or the backend's explanation of why there is none. */
export type Guarded<T> = T | AccessDenial;

export function isDenied<T>(value: Guarded<T> | null | undefined): value is AccessDenial {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as Partial<AccessDenial>).denied === true
  );
}

const FORBIDDEN_STATUS = 403;

const NO_REASON_GIVEN =
  'The backend refused this read without naming a reason. Treat it as not granted, not as empty.';

/**
 * Structural rather than `instanceof RestClientError`: the class identity is not
 * worth coupling to, and every rejection this layer sees that carries
 * `status: 403` means the same thing.
 */
function denialFrom(error: unknown, scopeRequired: boolean): AccessDenial | null {
  if (typeof error !== 'object' || error === null) return null;
  const candidate = error as { status?: unknown; message?: unknown; problem?: unknown };
  if (candidate.status !== FORBIDDEN_STATUS) return null;

  let denialReason: string | null = null;
  if (typeof candidate.problem === 'object' && candidate.problem !== null) {
    const problem = candidate.problem as Record<string, unknown>;
    const details = problem['details'];
    if (typeof details === 'object' && details !== null) {
      const named = (details as Record<string, unknown>)['denial_reason'];
      if (typeof named === 'string' && named !== '') denialReason = named;
    }
  }

  const message =
    typeof candidate.message === 'string' && candidate.message.trim() !== ''
      ? candidate.message
      : NO_REASON_GIVEN;

  return { denied: true, scopeRequired, reason: message, denialReason };
}

/** Turn a 403 into a rendered explanation; let every other failure stay an error. */
function guard<T>(promise: Promise<T>, scopeRequired: boolean): Promise<Guarded<T>> {
  return promise.catch((error: unknown) => {
    const denial = denialFrom(error, scopeRequired);
    if (denial !== null) return denial;
    throw error;
  });
}

// ── Fetchers ─────────────────────────────────────────────────────────────────

export function fetchPlatformGraph(environment?: string): Promise<Guarded<PlatformGraph>> {
  return guard(
    restClient
      .get(
        `/v1/kyber/graph/platform${buildQS({ environment })}`,
        wrap(platformGraphSchema),
      )
      .then(r => r.data),
    false,
  );
}

export function fetchFleetSummary(environment?: string): Promise<Guarded<FleetSummary>> {
  return guard(
    restClient
      .get(`/v1/kyber/graph/fleet${buildQS({ environment })}`, wrap(fleetSummarySchema))
      .then(r => r.data),
    false,
  );
}

export function fetchFleetProjection(
  projection: string,
  environment?: string,
  limit?: number,
): Promise<Guarded<FleetAggregate>> {
  return guard(
    restClient
      .get(
        `/v1/kyber/graph/fleet/${encodeURIComponent(projection)}${buildQS({ environment, limit })}`,
        wrap(fleetAggregateSchema),
      )
      .then(r => r.data),
    false,
  );
}

export interface CohortDraft {
  readonly name: string;
  readonly filters: Record<string, unknown>;
  readonly minimumSize: number;
}

export function defineCohort(draft: CohortDraft): Promise<Guarded<CohortDefineResult>> {
  return guard(
    restClient
      .post('/v1/kyber/graph/cohorts', wrap(cohortDefineResultSchema), {
        name: draft.name,
        filters: draft.filters,
        minimum_size: draft.minimumSize,
      })
      .then(r => r.data),
    false,
  );
}

export function fetchCohortEvaluation(
  cohortId: string,
  environment?: string,
): Promise<Guarded<CohortEvaluation>> {
  return guard(
    restClient
      .get(
        `/v1/kyber/graph/cohorts/${encodeURIComponent(cohortId)}${buildQS({ environment })}`,
        wrap(cohortEvaluationSchema),
      )
      .then(r => r.data),
    false,
  );
}

export interface BlastRadiusRequest {
  readonly subjectType: string;
  readonly subjectId: string;
  readonly environment?: string | undefined;
  readonly maxDepth?: number | undefined;
}

export function fetchBlastRadius(request: BlastRadiusRequest): Promise<Guarded<BlastRadius>> {
  const body: Record<string, unknown> = {
    subject_type: request.subjectType,
    subject_id: request.subjectId,
    max_depth: request.maxDepth ?? MAX_TRAVERSAL_DEPTH,
  };
  if (request.environment !== undefined && request.environment !== '') {
    body['environment'] = request.environment;
  }
  return guard(
    restClient
      .post('/v1/kyber/graph/blast-radius', wrap(blastRadiusSchema), body)
      .then(r => r.data),
    false,
  );
}

export interface TenantGraphQuery {
  readonly tenantId: string;
  readonly vertexType?: string | undefined;
  readonly limit?: number | undefined;
}

/** D3. `scopeRequired` is true: a 403 here means "no active scope names this tenant". */
export function fetchTenantGraph(query: TenantGraphQuery): Promise<Guarded<TenantGraph>> {
  return guard(
    restClient
      .get(
        `/v1/kyber/graph/tenants/${encodeURIComponent(query.tenantId)}${buildQS({
          vertex_type: query.vertexType,
          limit: query.limit,
        })}`,
        wrap(tenantGraphSchema),
      )
      .then(r => r.data),
    true,
  );
}

export interface TenantEntityQuery {
  readonly tenantId: string;
  readonly vertexId: string;
  readonly depth?: number | undefined;
}

/** D3. Same gate, same scope requirement. */
export function fetchTenantEntity(query: TenantEntityQuery): Promise<Guarded<TenantGraph>> {
  return guard(
    restClient
      .get(
        `/v1/kyber/graph/tenants/${encodeURIComponent(query.tenantId)}/entities/${encodeURIComponent(
          query.vertexId,
        )}${buildQS({ depth: query.depth })}`,
        wrap(tenantGraphSchema),
      )
      .then(r => r.data),
    true,
  );
}

// ── Hooks ────────────────────────────────────────────────────────────────────

export interface QueryState<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
}

export function usePlatformGraph(environment?: string): QueryState<Guarded<PlatformGraph>> {
  const { data, isLoading, error, refetch } = useQuery<Guarded<PlatformGraph>>({
    key: `${KEY_PREFIX}:platform:${environment ?? 'all'}`,
    fetcher: () => fetchPlatformGraph(environment),
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

export function useFleetSummary(environment?: string): QueryState<Guarded<FleetSummary>> {
  const { data, isLoading, error, refetch } = useQuery<Guarded<FleetSummary>>({
    key: `${KEY_PREFIX}:fleet:${environment ?? 'all'}`,
    fetcher: () => fetchFleetSummary(environment),
    staleTime: STALE,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Disabled until a projection is named — the route requires one in its path. */
export function useFleetProjection(
  projection: string | null,
  environment?: string,
): QueryState<Guarded<FleetAggregate>> {
  const { data, isLoading, error, refetch } = useQuery<Guarded<FleetAggregate>>({
    key: `${KEY_PREFIX}:fleet-projection:${projection ?? 'none'}:${environment ?? 'all'}`,
    fetcher: () => fetchFleetProjection(projection as string, environment),
    staleTime: STALE,
    enabled: projection !== null && projection.trim() !== '',
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Disabled until a cohort id is named. */
export function useCohortEvaluation(
  cohortId: string | null,
  environment?: string,
): QueryState<Guarded<CohortEvaluation>> {
  const { data, isLoading, error, refetch } = useQuery<Guarded<CohortEvaluation>>({
    key: `${KEY_PREFIX}:cohort:${cohortId ?? 'none'}:${environment ?? 'all'}`,
    fetcher: () => fetchCohortEvaluation(cohortId as string, environment),
    staleTime: STALE,
    enabled: cohortId !== null && cohortId.trim() !== '',
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

export function useDefineCohort() {
  return useMutation<CohortDraft, Guarded<CohortDefineResult>>({
    mutationFn: defineCohort,
  });
}

/** Disabled until a subject is named — a blast radius is per subject by design. */
export function useBlastRadius(
  request: BlastRadiusRequest | null,
): QueryState<Guarded<BlastRadius>> {
  const { data, isLoading, error, refetch } = useQuery<Guarded<BlastRadius>>({
    key: `${KEY_PREFIX}:blast:${request?.subjectType ?? ''}:${request?.subjectId ?? ''}:${
      request?.environment ?? ''
    }:${request?.maxDepth ?? ''}`,
    fetcher: () => fetchBlastRadius(request as BlastRadiusRequest),
    staleTime: STALE,
    enabled: request !== null && request.subjectId.trim() !== '',
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Disabled until a tenant is named. Routing is not a grant; the scope is. */
export function useTenantGraph(query: TenantGraphQuery | null): QueryState<Guarded<TenantGraph>> {
  const { data, isLoading, error, refetch } = useQuery<Guarded<TenantGraph>>({
    key: `${KEY_PREFIX}:tenant:${query?.tenantId ?? 'none'}:${query?.vertexType ?? ''}`,
    fetcher: () => fetchTenantGraph(query as TenantGraphQuery),
    staleTime: STALE,
    enabled: query !== null && query.tenantId.trim() !== '',
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Disabled until both a tenant and an entity are named. */
export function useTenantEntity(query: TenantEntityQuery | null): QueryState<Guarded<TenantGraph>> {
  const { data, isLoading, error, refetch } = useQuery<Guarded<TenantGraph>>({
    key: `${KEY_PREFIX}:tenant-entity:${query?.tenantId ?? 'none'}:${query?.vertexId ?? 'none'}:${
      query?.depth ?? ''
    }`,
    fetcher: () => fetchTenantEntity(query as TenantEntityQuery),
    staleTime: STALE,
    enabled:
      query !== null && query.tenantId.trim() !== '' && query.vertexId.trim() !== '',
  });
  return { data, loading: isLoading, error, refresh: refetch };
}
