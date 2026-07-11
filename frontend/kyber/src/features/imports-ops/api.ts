/**
 * KYBER operator adapter — Tenant Import Engine ops (/v1/kyber/imports).
 * Cross-tenant, read-mostly operator surface over the Aether import pipeline:
 * a newest-first timeline of every tenant's import sessions, a single-import
 * drill-down with its commit history, and an audited requeue that recovers a
 * failed import (reset → re-enqueue commit). All responses are the standard
 * { data, status, timestamp } envelope.
 *
 * Rollup-safe imports: runtime const arrays via a plain import, types via
 * `import type`, both resolving to @aether/shared's built dist.
 */
import { z } from 'zod';
import { restClient } from '@kyber/lib/api';
import type { ImportStatus, ImportSession } from '@aether/shared';

// Runtime status tuple for `z.enum(...)`. Kyber bundles @aether/shared from its
// CJS `dist` without the CJS→ESM interop that frontend/aether configures via
// `build.commonjsOptions` — so a runtime `import { importStatuses }` cannot be
// rollup-bundled in this workspace (every other kyber file imports @aether/shared
// as `import type` only). We mirror the canonical list locally and bind it to the
// shared ImportStatus union so any drift fails typecheck in both directions.
const importStatuses = [
  'created', 'files_pending', 'uploaded', 'analyzing', 'analyzed', 'mapping',
  'mapped', 'validating', 'validated', 'review_required', 'approved',
  'committing', 'committed', 'partially_committed', 'failed', 'cancelled',
  'rolled_back',
] as const satisfies readonly ImportStatus[];

// Exhaustiveness: every ImportStatus must appear in the tuple above (→ `never`).
type _MissingStatus = Exclude<ImportStatus, (typeof importStatuses)[number]>;
const _statusExhaustive: [_MissingStatus] extends [never] ? true : false = true;
void _statusExhaustive;

// ── Envelope + query helpers ────────────────────────────────────────────────

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

// ── Wire schemas (snake_case per backend, tolerant with passthrough/nullish) ──

export const importSessionSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  status: z.enum(importStatuses),
  source_kind: z.string(),
  file_count: z.number(),
  row_count: z.number().nullish(),
  created_by: z.string().nullish(),
  created_at: z.string(),
  updated_at: z.string(),
}).passthrough();

// Satisfy the shared ImportSession contract at compile time without widening the
// zod inference: the wire schema is a superset (passthrough) of ImportSession.
// Wire record for an import session — a tolerant superset of the shared
// ImportSession contract (same fields; nullable/passthrough for forward-compat).
export type ImportSessionRecord = z.infer<typeof importSessionSchema>;

// Re-export the shared contracts this operator feature is built around so callers
// can lean on the canonical @aether/shared types.
export type { ImportStatus, ImportSession };

export const importCommitSchema = z.object({
  id: z.string().nullish(),
  commit_id: z.string().nullish(),
  import_id: z.string().nullish(),
  status: z.string().nullish(),
  row_count: z.number().nullish(),
  vertices_count: z.number().nullish(),
  edges_count: z.number().nullish(),
  rolled_back: z.boolean().nullish(),
  created_at: z.string().nullish(),
  created_by: z.string().nullish(),
}).passthrough();

export type ImportCommitRecord = z.infer<typeof importCommitSchema>;

const importJobSchema = z.object({
  id: z.string().nullish(),
  status: z.string().nullish(),
}).passthrough();

// ── Composite response schemas ──────────────────────────────────────────────

const importTimelineSchema = z.object({
  count: z.number(),
  sessions: z.array(importSessionSchema),
}).passthrough();

const importOpsDetailSchema = z.object({
  session: importSessionSchema,
  commits: z.array(importCommitSchema),
  commit_count: z.number(),
}).passthrough();

export type ImportOpsDetail = z.infer<typeof importOpsDetailSchema>;

const requeueResponseSchema = z.object({
  import_id: z.string(),
  job: importJobSchema,
}).passthrough();

export type RequeueResponse = z.infer<typeof requeueResponseSchema>;

// ── Fetchers ─────────────────────────────────────────────────────────────────

export interface ImportsTimelineParams {
  readonly limit?: number;
}

export interface ImportsTimelineResult {
  readonly sessions: ImportSessionRecord[];
  readonly count: number;
}

/** Newest-first, cross-tenant timeline of import sessions. */
export function fetchImportsTimeline(params?: ImportsTimelineParams): Promise<ImportsTimelineResult> {
  return restClient
    .get(
      `/v1/kyber/imports/timeline${buildQS({ limit: params?.limit })}`,
      wrap(importTimelineSchema),
    )
    .then(r => ({ sessions: r.data.sessions as ImportSessionRecord[], count: r.data.count }));
}

/** A single import session (any tenant) plus its commit history. */
export function fetchImportOpsDetail(id: string): Promise<ImportOpsDetail> {
  return restClient
    .get(`/v1/kyber/imports/${encodeURIComponent(id)}`, wrap(importOpsDetailSchema))
    .then(r => r.data);
}

/** Recover a failed import — reset and re-enqueue the commit job (audited). */
export function requeueImport(id: string): Promise<RequeueResponse> {
  return restClient
    .post(`/v1/kyber/imports/${encodeURIComponent(id)}/requeue`, wrap(requeueResponseSchema), {})
    .then(r => r.data);
}
