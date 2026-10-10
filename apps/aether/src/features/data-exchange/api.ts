import { z } from 'zod';
import { restClient } from '@aether-app/lib/api/rest/client';
import {
  dataArtifactStatuses,
  dataExchangeDirections,
  dataExchangeClassifications,
  type DataArtifactStatus,
  type DataExchangeDirection,
  type ExportSpecContract,
  type ReportSpecContract,
} from '@aether/shared';

/**
 * Data Exchange Plane — tenant-facing typed client.
 *
 * M6 of the Data Exchange program builds the Settings → Data Exchange surface
 * against the frozen `/v1/data-exchange/*` contract in
 * `docs/plans/data-exchange-api.md`. These zod schemas are the trust boundary
 * between the backend read adapters and the typed UI: field names match the
 * freeze tables exactly, and status / direction / classification values are
 * pinned to the M0 shared tuples (`packages/shared/data-exchange.ts`).
 *
 * The wire transport follows the canonical Aether envelope — canonical route
 * handlers are wrapped by the backend `@api_response` decorator into
 * `{ data, status, timestamp }`, and sibling feature modules (e.g. the tenant
 * Import Engine) parse that same envelope. `wrap()` below mirrors it.
 */

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

// ── Shared leaf schemas ──────────────────────────────────────────────────────

/** Structured exchange formats are M0 tuple members; report PDF artifacts may
 * carry a `pdf` artifact format even though PDF is never a structured egress
 * format — so the format field is validated loosely at the artifact edge. */
const artifactFormatSchema = z
  .enum(['csv', 'json', 'ndjson', 'jsonl', 'parquet', 'pdf'])
  .nullish();

// ── Settings read adapter (GET /v1/data-exchange/settings) ──────────────────

/** One per-surface settings block from the settings adapter. */
const dataExchangeSettingsBlockSchema = z
  .object({
    enabled: z.boolean().optional(),
  })
  .passthrough();

const dataExchangeSettingsSchema = z
  .object({
    imports: dataExchangeSettingsBlockSchema,
    exports: dataExchangeSettingsBlockSchema,
    reports: dataExchangeSettingsBlockSchema,
    transfers: dataExchangeSettingsBlockSchema,
    capabilities: z.record(z.unknown()).optional(),
  })
  .passthrough();

export type DataExchangeSettings = z.infer<typeof dataExchangeSettingsSchema>;
export type DataExchangeSettingsBlock = z.infer<typeof dataExchangeSettingsBlockSchema>;

// ── Capabilities read adapter (GET /v1/data-exchange/capabilities) ──────────

const dataExchangeCapabilitiesSchema = z
  .object({
    data_exchange: z
      .object({
        enabled: z.boolean(),
        flags: z.record(z.boolean()).optional(),
      })
      .passthrough(),
    available_formats: z.array(z.string()).optional(),
    available_sources: z.array(z.string()).optional(),
    blocked_classifications: z.array(z.string()).optional(),
  })
  .passthrough();

export type DataExchangeCapabilities = z.infer<typeof dataExchangeCapabilitiesSchema>;

export type DataExchangeSurface = 'imports' | 'exports' | 'reports' | 'transfers';

/** Candidate flag keys per surface — tolerant of backend key spelling. A
 * surface defaults ON once `data_exchange.enabled` is true and no candidate
 * flag is present, so controls never over-hide when the adapter omits flags. */
const SURFACE_FLAG_KEYS: Record<DataExchangeSurface, readonly string[]> = {
  imports: ['imports', 'imports_enabled', 'data_exchange_enabled'],
  exports: ['exports', 'exports_enabled', 'data_exchange_enabled'],
  reports: ['reports', 'reports_enabled', 'data_exchange_reports_enabled'],
  transfers: [
    'transfers',
    'signed_transfers',
    'signed_transfers_enabled',
    'object_store',
    'object_store_enabled',
  ],
};

/** Whether a data-exchange surface (imports / exports / reports / transfers)
 * is available for the calling tenant. Fails closed when capabilities are
 * absent. */
export function dataExchangeSurfaceEnabled(
  capabilities: DataExchangeCapabilities | null | undefined,
  surface: DataExchangeSurface,
): boolean {
  const dx = capabilities?.data_exchange;
  if (!dx || dx.enabled !== true) return false;
  const flags = dx.flags ?? {};
  const present = SURFACE_FLAG_KEYS[surface].filter(key => key in flags);
  if (present.length === 0) return true;
  return present.some(key => flags[key] === true);
}

// ── Usage read adapter (GET /v1/data-exchange/usage) ────────────────────────

const usageCounterSchema = z.record(z.unknown());

const dataExchangeUsageSchema = z
  .object({
    tenant_id: z.string().optional(),
    imports: usageCounterSchema.optional(),
    exports: usageCounterSchema.optional(),
    reports: usageCounterSchema.optional(),
    quotas: z.record(z.unknown()).optional(),
  })
  .passthrough();

export type DataExchangeUsage = z.infer<typeof dataExchangeUsageSchema>;

// ── Unified artifact history (GET /v1/data-exchange/artifacts) ──────────────

export const dataExchangeArtifactSchema = z
  .object({
    artifact_id: z.string(),
    tenant_id: z.string().optional(),
    direction: z.enum(dataExchangeDirections),
    artifact_type: z.string(),
    job_id: z.string().nullish(),
    object_key: z.string().nullish(),
    filename: z.string().nullish(),
    format: artifactFormatSchema,
    content_type: z.string().nullish(),
    size_bytes: z.number().nullish(),
    sha256: z.string().nullish(),
    classification: z.enum(dataExchangeClassifications),
    status: z.enum(dataArtifactStatuses),
    created_by: z.string().nullish(),
    created_at: z.string(),
    expires_at: z.string().nullish(),
  })
  .passthrough();

export type DataExchangeArtifact = z.infer<typeof dataExchangeArtifactSchema>;

const dataExchangeArtifactsListSchema = z
  .object({
    artifacts: z.array(dataExchangeArtifactSchema),
    count: z.number().int().nonnegative(),
  })
  .passthrough();

// ── Export history (GET /v1/data-exchange/exports) ──────────────────────────

const dataExchangeExportsListSchema = z
  .object({
    artifacts: z.array(dataExchangeArtifactSchema),
    count: z.number().int().nonnegative(),
  })
  .passthrough();

// ── Import history (GET /v1/data-exchange/imports) ──────────────────────────

const dataExchangeImportsListSchema = z
  .object({
    imports: z.array(dataExchangeArtifactSchema.passthrough()),
    count: z.number().int().nonnegative(),
  })
  .passthrough();

// ── Report history (GET /v1/data-exchange/reports) ──────────────────────────

const dataExchangeReportsListSchema = z
  .object({
    artifacts: z.array(dataExchangeArtifactSchema),
    count: z.number().int().nonnegative(),
  })
  .passthrough();

// ── Export creation (POST /v1/data-exchange/exports) ────────────────────────

const createDataExchangeExportSchema = z
  .object({
    export_id: z.string(),
    artifact_id: z.string().nullish(),
    job_id: z.string().nullish(),
    status: z.literal('generating'),
  })
  .passthrough();

export type DataExchangeExportResult = z.infer<typeof createDataExchangeExportSchema>;

/** POST body for the export envelope. The shared `ExportSpecContract` includes
 * server-populated `export_id`/`tenant_id`; the create verb omits them and the
 * backend assigns them (they come back on the response). */
export interface CreateDataExchangeExportInput
  extends Omit<ExportSpecContract, 'export_id' | 'tenant_id'> {}

// ── Report creation (POST /v1/data-exchange/reports) ────────────────────────

const createDataExchangeReportSchema = z
  .object({
    report_id: z.string(),
    artifact_id: z.string().nullish(),
    job_id: z.string().nullish(),
    status: z.literal('generating'),
  })
  .passthrough();

export type DataExchangeReportResult = z.infer<typeof createDataExchangeReportSchema>;

export interface CreateDataExchangeReportInput
  extends Omit<ReportSpecContract, 'report_id' | 'tenant_id'> {}

// ── Download URL (GET /v1/data-exchange/transfers/{id}/download-url) ────────

const dataExchangeDownloadUrlSchema = z
  .object({
    artifact_id: z.string(),
    download_url: z.string(),
    download_headers: z.record(z.string()).optional(),
    expires_at: z.string().nullish(),
    checksum_sha256: z.string().nullish(),
  })
  .passthrough();

export type DataExchangeDownloadUrl = z.infer<typeof dataExchangeDownloadUrlSchema>;

// ── Query param + result types ──────────────────────────────────────────────

export interface DataExchangeListParams {
  readonly limit?: number;
  readonly offset?: number;
}

export interface DataExchangeArtifactsParams extends DataExchangeListParams {
  readonly direction?: DataExchangeDirection;
  readonly artifact_type?: string;
  readonly status_filter?: DataArtifactStatus;
}

export interface DataExchangeArtifactsResult {
  readonly artifacts: DataExchangeArtifact[];
  readonly count: number;
}

export interface DataExchangeExportsResult {
  readonly artifacts: DataExchangeArtifact[];
  readonly count: number;
}

export interface DataExchangeImportsResult {
  readonly imports: DataExchangeArtifact[];
  readonly count: number;
}

export interface DataExchangeReportsResult {
  readonly artifacts: DataExchangeArtifact[];
  readonly count: number;
}

// ── Fetchers ─────────────────────────────────────────────────────────────────

export function fetchDataExchangeSettings(): Promise<DataExchangeSettings> {
  return restClient
    .get('/v1/data-exchange/settings', wrap(dataExchangeSettingsSchema))
    .then(r => r.data);
}

export function fetchDataExchangeCapabilities(): Promise<DataExchangeCapabilities> {
  return restClient
    .get('/v1/data-exchange/capabilities', wrap(dataExchangeCapabilitiesSchema))
    .then(r => r.data);
}

export function fetchDataExchangeUsage(): Promise<DataExchangeUsage> {
  return restClient
    .get('/v1/data-exchange/usage', wrap(dataExchangeUsageSchema))
    .then(r => r.data);
}

export function fetchDataExchangeArtifacts(
  params?: DataExchangeArtifactsParams,
): Promise<DataExchangeArtifactsResult> {
  return restClient
    .get(
      `/v1/data-exchange/artifacts${buildQS({
        limit: params?.limit,
        offset: params?.offset,
        direction: params?.direction,
        artifact_type: params?.artifact_type,
        status_filter: params?.status_filter,
      })}`,
      wrap(dataExchangeArtifactsListSchema),
    )
    .then(r => r.data);
}

export function fetchDataExchangeExports(
  params?: DataExchangeListParams,
): Promise<DataExchangeExportsResult> {
  return restClient
    .get(
      `/v1/data-exchange/exports${buildQS({ limit: params?.limit, offset: params?.offset })}`,
      wrap(dataExchangeExportsListSchema),
    )
    .then(r => r.data);
}

export function fetchDataExchangeImports(
  params?: DataExchangeListParams,
): Promise<DataExchangeImportsResult> {
  return restClient
    .get(
      `/v1/data-exchange/imports${buildQS({ limit: params?.limit, offset: params?.offset })}`,
      wrap(dataExchangeImportsListSchema),
    )
    .then(r => r.data);
}

export function fetchDataExchangeReports(
  params?: DataExchangeListParams,
): Promise<DataExchangeReportsResult> {
  return restClient
    .get(
      `/v1/data-exchange/reports${buildQS({ limit: params?.limit, offset: params?.offset })}`,
      wrap(dataExchangeReportsListSchema),
    )
    .then(r => r.data);
}

export function createDataExchangeExport(
  input: CreateDataExchangeExportInput,
): Promise<DataExchangeExportResult> {
  return restClient
    .post('/v1/data-exchange/exports', wrap(createDataExchangeExportSchema), input)
    .then(r => r.data);
}

export function createDataExchangeReport(
  input: CreateDataExchangeReportInput,
): Promise<DataExchangeReportResult> {
  return restClient
    .post('/v1/data-exchange/reports', wrap(createDataExchangeReportSchema), input)
    .then(r => r.data);
}

export function fetchDataExchangeDownloadUrl(artifact_id: string): Promise<DataExchangeDownloadUrl> {
  return restClient
    .get(
      `/v1/data-exchange/transfers/${encodeURIComponent(artifact_id)}/download-url`,
      wrap(dataExchangeDownloadUrlSchema),
    )
    .then(r => r.data);
}
