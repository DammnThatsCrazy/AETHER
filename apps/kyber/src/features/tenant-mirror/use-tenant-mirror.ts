/**
 * KYBER operator adapter — Tenant Mirror (`/v1/kyber/tenants/{tenant_id}/mirror/...`).
 *
 * The Tenant Mirror exists to hold one invariant:
 *
 *   the tenant-visible result Aether returns for a tenant + surface + contract
 *   version is the *same* result the mirror returns.
 *
 * Kyber may add `operatorDiagnostics` on top. It may never recompute a
 * tenant-visible value differently — an operator who is debugging a second
 * implementation of the tenant's product is not debugging the tenant's product.
 *
 * ── What that means for the schemas in this file ─────────────────────────────
 *
 * Everything under `tenantVisible` is the tenant's own result and is typed
 * `.nullable()` wherever the backend can answer null. There is no `.default(0)`
 * and no `?? 0` here or at any call site. Coercing a tenant-visible null to zero
 * would make this page *lie about what the tenant sees*, which is strictly worse
 * than the page failing to load: the operator would quote a number back to a
 * customer that the customer's own screen never showed.
 *
 * The parity route is the second load-bearing shape. `comparison` is nullable by
 * construction — the backend only locates divergence when the caller supplies
 * Aether's own payload — so "the comparison did not run" is a first-class state
 * (`undetermined`) that must never collapse into "matched". See
 * `deriveParityState` below: the ordering of its branches is the safety property.
 *
 * Sources of truth:
 *   services/kyber/mirror/routes.py     — the three routes and their envelopes
 *   services/kyber/mirror/contracts.py  — MirrorEnvelope / OperatorDiagnostics /
 *                                         ParityDigest / ParityComparison / Divergence
 *   services/kyber/mirror/parity.py     — MAX_REPORTED_DIVERGENCES, divergence reasons
 *   packages/shared/contracts/kyber-feature-surface-manifest.json — the surface list
 */

import { useQuery } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@kyber/lib/api';
// The surface picker is driven by the manifest itself, never by a hand-written
// list: a surface added to (or exempted in) the manifest must appear here on the
// next build, or an operator would be offered a mirror the backend does not have
// — or, worse, silently not be offered one it does.
import rawManifest from '../../../../../packages/shared/contracts/kyber-feature-surface-manifest.json';

const KEY_PREFIX = 'kyber-tenant-mirror';
const STALE = 15_000;

/** Largest inline `compare` payload the backend accepts (`routes.MAX_COMPARE_BYTES`). */
export const MAX_COMPARE_BYTES = 8192;

/** `parity.MAX_REPORTED_DIVERGENCES` — beyond this the backend caps the list. */
export const MAX_REPORTED_DIVERGENCES = 50;

/** The five operator augmentation sections, in `contracts.DIAGNOSTIC_SECTIONS` order. */
export const DIAGNOSTIC_SECTIONS = [
  'quality',
  'lineage',
  'policy',
  'health',
  'recomputeOptions',
] as const;

export type DiagnosticSection = (typeof DIAGNOSTIC_SECTIONS)[number];

// ── Feature-surface manifest ─────────────────────────────────────────────────

const surfaceSchema = z
  .object({
    feature_id: z.string(),
    aether_route: z.string(),
    tenant_parity_required: z.boolean(),
    // Exempt surfaces carry a written reason. A null reason on an exempt surface
    // is a manifest defect and is surfaced as such, not smoothed over.
    parity_exception_reason: z.string().nullable(),
    kyber_mirror_route: z.string().nullable(),
    minimum_disclosure: z.string(),
    backend_capability: z.string().nullish(),
    operator_augmentations: z.array(z.string()).nullish(),
  })
  .passthrough();

export type MirrorSurface = z.infer<typeof surfaceSchema>;

const manifestSchema = z
  .object({
    schemaVersion: z.string(),
    surfaces: z.array(surfaceSchema),
  })
  .passthrough();

/**
 * Parsed at module load, and deliberately fatal on failure. The backend treats a
 * missing manifest the same way (`service.load_manifest`): a mirror that ran
 * without it would answer for surfaces nobody classified.
 */
const MANIFEST = manifestSchema.parse(rawManifest);

/** Every manifest surface, in manifest order. */
export const MIRROR_SURFACES: readonly MirrorSurface[] = MANIFEST.surfaces;

/** The manifest schema version — the contract version the digest is bound to. */
export const MANIFEST_SCHEMA_VERSION: string = MANIFEST.schemaVersion;

/** Shown when the manifest exempts a surface but records no reason for it. */
export const NO_EXCEPTION_REASON_RECORDED =
  'The manifest exempts this surface but records no reason. Treat the exemption as unexplained, not as justified.';

export function findMirrorSurface(featureId: string): MirrorSurface | null {
  return MIRROR_SURFACES.find(entry => entry.feature_id === featureId) ?? null;
}

export function parityRequiredSurfaces(): readonly MirrorSurface[] {
  return MIRROR_SURFACES.filter(entry => entry.tenant_parity_required);
}

export function parityExemptSurfaces(): readonly MirrorSurface[] {
  return MIRROR_SURFACES.filter(entry => !entry.tenant_parity_required);
}

/** The manifest's written reason, or an explicit statement that none was written. */
export function exemptionReason(surface: MirrorSurface): string {
  const reason = surface.parity_exception_reason;
  return reason !== null && reason.trim() !== '' ? reason : NO_EXCEPTION_REASON_RECORDED;
}

// ── Mirror envelope ──────────────────────────────────────────────────────────

/**
 * The tenant's own result. Known keys are typed because the page renders them,
 * `.passthrough()` keeps everything else because the page also renders the raw
 * payload — the operator has to be able to see the bytes the digest was taken
 * over, not a subset this file happened to model.
 *
 * Every count is `.nullable()`. Never `.default(0)`.
 */
const tenantVisibleSchema = z
  .object({
    surface: z.string().nullish(),
    aether_route: z.string().nullish(),
    tenant_id: z.string().nullish(),
    vertex_types: z.array(z.string()).nullish(),
    entities: z.record(z.array(z.unknown()).nullable()).nullish(),
    entity_counts: z.record(z.number().nullable()).nullish(),
    entity_count: z.number().nullable().nullish(),
    truncated: z.boolean().nullish(),
  })
  .passthrough();

export type TenantVisible = z.infer<typeof tenantVisibleSchema>;

/**
 * Operator-only augmentation. Every section is nullable and an *empty* section
 * means "not computed" — never "nothing wrong". The backend states the same rule
 * on `OperatorDiagnostics`, and the page repeats it on screen: an operator who
 * cannot tell absence from health reads silence as safety.
 */
const operatorDiagnosticsSchema = z
  .object({
    quality: z.record(z.unknown()).nullish(),
    lineage: z.record(z.unknown()).nullish(),
    policy: z.record(z.unknown()).nullish(),
    health: z.record(z.unknown()).nullish(),
    recomputeOptions: z.array(z.record(z.unknown())).nullish(),
  })
  .passthrough();

export type OperatorDiagnostics = z.infer<typeof operatorDiagnosticsSchema>;

const mirrorEnvelopeSchema = z
  .object({
    surface_id: z.string(),
    aether_route: z.string().nullish(),
    tenant_id: z.string(),
    contract_version: z.string(),
    generated_at: z.string().nullish(),
    disclosure: z.string().nullish(),
    parity_comparable: z.boolean(),
    tenantVisible: tenantVisibleSchema,
    operatorDiagnostics: operatorDiagnosticsSchema,
  })
  .passthrough();

export type MirrorEnvelope = z.infer<typeof mirrorEnvelopeSchema>;

const metaSchema = z
  .object({
    granted_disclosure: z.string().nullish(),
    contract_version: z.string().nullish(),
    parity_comparable: z.boolean().nullish(),
  })
  .passthrough();

const mirrorResponseSchema = z
  .object({ data: mirrorEnvelopeSchema, meta: metaSchema.nullish() })
  .passthrough();

// ── Parity evidence ──────────────────────────────────────────────────────────

const parityDigestSchema = z
  .object({
    algorithm: z.string(),
    digest: z.string(),
    // Nullable, never defaulted: "the canonical form was 0 bytes" and "the
    // backend did not report its size" are different facts.
    canonical_bytes: z.number().nullable(),
    contract_version: z.string(),
    computed_at: z.string().nullish(),
  })
  .passthrough();

export type ParityDigest = z.infer<typeof parityDigestSchema>;

/** One located disagreement. `path` is what makes this usable during an incident. */
const divergenceSchema = z
  .object({
    path: z.string(),
    aether: z.unknown(),
    mirror: z.unknown(),
    // value_differs | type_differs | missing_in_mirror | missing_in_aether | length_differs
    reason: z.string(),
  })
  .passthrough();

export type Divergence = z.infer<typeof divergenceSchema>;

const parityComparisonSchema = z
  .object({
    matched: z.boolean(),
    contract_version: z.string(),
    aether_digest: parityDigestSchema,
    mirror_digest: parityDigestSchema,
    divergences: z.array(divergenceSchema),
    // The real total. When it exceeds `divergences.length` the list was capped.
    divergence_count: z.number().nullable(),
    truncated: z.boolean(),
    compared_at: z.string().nullish(),
  })
  .passthrough();

export type ParityComparison = z.infer<typeof parityComparisonSchema>;

/**
 * `comparison` is null whenever no Aether payload was supplied. That is a
 * digest-only answer and it is NOT parity — see `deriveParityState`.
 */
const parityReportSchema = z
  .object({
    surface: z.string(),
    tenant_id: z.string(),
    contract_version: z.string(),
    parity_comparable: z.boolean(),
    mirror_digest: parityDigestSchema,
    comparison: parityComparisonSchema.nullable(),
  })
  .passthrough();

export type ParityReport = z.infer<typeof parityReportSchema>;

const parityResponseSchema = z
  .object({ data: parityReportSchema, meta: metaSchema.nullish() })
  .passthrough();

// ── Access outcome ───────────────────────────────────────────────────────────

/**
 * The mirror routes are D3 reads and require an *active tenant access scope*. A
 * 403 is therefore an expected, explainable state — not a failure of the page —
 * so it is modelled as a value rather than thrown into a generic error banner.
 * Routing is not a grant: reaching the URL says nothing about the scope.
 */
export type MirrorAccess<T> =
  | { readonly kind: 'granted'; readonly value: T; readonly grantedDisclosure: string | null }
  | { readonly kind: 'forbidden'; readonly status: number; readonly reason: string };

export const NO_REASON_REPORTED =
  'The API reported no reason. Treat the scope as unproven, not as granted.';

function errorStatus(err: unknown): number | null {
  if (typeof err !== 'object' || err === null) return null;
  const status = (err as { status?: unknown }).status;
  return typeof status === 'number' ? status : null;
}

/** The backend's own explanation, preferred over anything this client invents. */
export function accessDenialReason(err: unknown): string {
  if (typeof err === 'object' && err !== null) {
    const problem = (err as { problem?: { detail?: unknown; title?: unknown } }).problem;
    if (problem) {
      if (typeof problem.detail === 'string' && problem.detail.trim() !== '') return problem.detail;
      if (typeof problem.title === 'string' && problem.title.trim() !== '') return problem.title;
    }
    const message = (err as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim() !== '') return message;
  }
  return NO_REASON_REPORTED;
}

/** 403 becomes a rendered state; everything else stays an error the page reports. */
function asAccess<T>(err: unknown): MirrorAccess<T> {
  const status = errorStatus(err);
  if (status === 403) {
    return { kind: 'forbidden', status, reason: accessDenialReason(err) };
  }
  throw err;
}

// ── Fetchers ─────────────────────────────────────────────────────────────────

export interface MirrorQuery {
  readonly tenantId: string;
  readonly surface: string;
  /** Reduced-disclosure (D2) variant. Redacted values are NOT the tenant's values. */
  readonly masked?: boolean | undefined;
}

function mirrorPath(query: MirrorQuery): string {
  const base = `/v1/kyber/tenants/${encodeURIComponent(query.tenantId)}/mirror/${encodeURIComponent(query.surface)}`;
  return query.masked === true ? `${base}/masked` : base;
}

export function fetchTenantMirror(query: MirrorQuery): Promise<MirrorAccess<MirrorEnvelope>> {
  return restClient
    .get(mirrorPath(query), mirrorResponseSchema)
    .then(
      (response): MirrorAccess<MirrorEnvelope> => ({
        kind: 'granted',
        value: response.data,
        grantedDisclosure: response.meta?.granted_disclosure ?? null,
      }),
    )
    .catch((err: unknown) => asAccess<MirrorEnvelope>(err));
}

export interface ParityQuery {
  readonly tenantId: string;
  readonly surface: string;
  /**
   * Aether's own `tenantVisible` payload, JSON-encoded. Omitted → the backend
   * returns its digest only and `comparison` is null, which is *not* parity.
   */
  readonly compare?: string | undefined;
}

/** Refused client-side with the backend's own limit rather than sent and rejected. */
export function compareTooLarge(compare: string): boolean {
  return new TextEncoder().encode(compare).length > MAX_COMPARE_BYTES;
}

export function fetchTenantMirrorParity(query: ParityQuery): Promise<MirrorAccess<ParityReport>> {
  const base = `/v1/kyber/tenants/${encodeURIComponent(query.tenantId)}/mirror/${encodeURIComponent(query.surface)}/parity`;
  const compare = query.compare;
  const path =
    compare !== undefined && compare.trim() !== ''
      ? `${base}?compare=${encodeURIComponent(compare)}`
      : base;
  return restClient
    .get(path, parityResponseSchema)
    .then(
      (response): MirrorAccess<ParityReport> => ({
        kind: 'granted',
        value: response.data,
        grantedDisclosure: response.meta?.granted_disclosure ?? null,
      }),
    )
    .catch((err: unknown) => asAccess<ParityReport>(err));
}

// ── Parity state ─────────────────────────────────────────────────────────────

export type ParityState =
  | { readonly kind: 'matched'; readonly comparison: ParityComparison }
  | { readonly kind: 'diverged'; readonly comparison: ParityComparison }
  | {
      readonly kind: 'undetermined';
      readonly reason: string;
      readonly digest: ParityDigest | null;
    }
  | {
      readonly kind: 'not_comparable';
      readonly reason: string;
      readonly digest: ParityDigest | null;
    }
  | { readonly kind: 'exempt'; readonly reason: string }
  | { readonly kind: 'forbidden'; readonly reason: string };

export const NO_COMPARISON_RAN =
  'No Aether payload was supplied, so the comparison never ran. What follows is the mirror’s own digest — it is evidence you can carry elsewhere, not evidence that parity holds.';

export const MASKED_NOT_COMPARABLE =
  'This is the masked (D2) rendering. Identifiers are redacted by design, so it is deliberately not what the tenant sees and must never be digested as if it were — comparing it would report redactions as divergence.';

export const NOT_LOADED_YET =
  'The parity read has not returned. Parity is undetermined until it does.';

export interface DeriveParityInput {
  readonly surface: MirrorSurface | null;
  readonly access: MirrorAccess<ParityReport> | null;
  readonly error: string | null;
  readonly masked: boolean;
}

/**
 * Reduce everything known about a parity read to exactly one state.
 *
 * The branch order is the safety property of this module. "Could not be
 * determined" is checked and returned *before* anything can fall through to a
 * matched-looking result, because assuming parity held on the grounds that the
 * comparison did not run is the single most misleading thing this surface could
 * do. There is deliberately no default/else that produces `matched`: `matched`
 * is returned only when the backend said `matched === true`.
 */
export function deriveParityState(input: DeriveParityInput): ParityState {
  const { surface, access, error, masked } = input;

  if (surface === null) {
    return { kind: 'undetermined', reason: 'No surface is selected.', digest: null };
  }
  if (!surface.tenant_parity_required) {
    return { kind: 'exempt', reason: exemptionReason(surface) };
  }
  if (masked) {
    return { kind: 'not_comparable', reason: MASKED_NOT_COMPARABLE, digest: null };
  }
  if (error !== null) {
    return { kind: 'undetermined', reason: error, digest: null };
  }
  if (access === null) {
    return { kind: 'undetermined', reason: NOT_LOADED_YET, digest: null };
  }
  if (access.kind === 'forbidden') {
    return { kind: 'forbidden', reason: access.reason };
  }

  const report = access.value;
  if (!report.parity_comparable) {
    return { kind: 'not_comparable', reason: MASKED_NOT_COMPARABLE, digest: report.mirror_digest };
  }
  if (report.comparison === null) {
    return { kind: 'undetermined', reason: NO_COMPARISON_RAN, digest: report.mirror_digest };
  }
  if (report.comparison.matched) {
    return { kind: 'matched', comparison: report.comparison };
  }
  return { kind: 'diverged', comparison: report.comparison };
}

/** True when the backend capped the divergence list, so the page must say so. */
export function divergencesTruncated(comparison: ParityComparison): boolean {
  if (comparison.truncated) return true;
  const total = comparison.divergence_count;
  return total !== null && total > comparison.divergences.length;
}

// ── Hooks ────────────────────────────────────────────────────────────────────

export interface MirrorQueryState<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
}

/** Disabled until a tenant and a parity-required surface are both named. */
export function useTenantMirror(
  query: MirrorQuery | null,
): MirrorQueryState<MirrorAccess<MirrorEnvelope>> {
  const enabled = query !== null && query.tenantId.trim() !== '' && query.surface.trim() !== '';
  const { data, isLoading, error, refetch } = useQuery<MirrorAccess<MirrorEnvelope>>({
    key: `${KEY_PREFIX}:read:${query?.tenantId ?? ''}:${query?.surface ?? ''}:${query?.masked === true ? 'masked' : 'visible'}`,
    fetcher: () => fetchTenantMirror(query as MirrorQuery),
    staleTime: STALE,
    enabled,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}

/** Disabled for masked renderings: a masked payload is not parity-comparable. */
export function useTenantMirrorParity(
  query: ParityQuery | null,
): MirrorQueryState<MirrorAccess<ParityReport>> {
  const enabled = query !== null && query.tenantId.trim() !== '' && query.surface.trim() !== '';
  const { data, isLoading, error, refetch } = useQuery<MirrorAccess<ParityReport>>({
    key: `${KEY_PREFIX}:parity:${query?.tenantId ?? ''}:${query?.surface ?? ''}:${query?.compare ?? ''}`,
    fetcher: () => fetchTenantMirrorParity(query as ParityQuery),
    staleTime: STALE,
    enabled,
  });
  return { data, loading: isLoading, error, refresh: refetch };
}
