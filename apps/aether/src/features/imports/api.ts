import { z } from 'zod';
import { restClient, RestClientError } from '@aether-app/lib/api/rest/client';
import { getAccessToken } from '@aether-app/features/auth';
import { getEnvironment } from '@aether-app/lib/env';
import {
  importStatuses,
  importPrimitives,
  importTransforms,
  importColumnTypes,
  importSensitivities,
} from '@aether/shared';
import type { FieldMapping } from '@aether/shared';

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

export type ImportSessionRecord = z.infer<typeof importSessionSchema>;

export const importFileMetaSchema = z.object({
  id: z.string(),
  import_id: z.string(),
  filename: z.string(),
  content_type: z.string(),
  size_bytes: z.number(),
  sha256: z.string(),
  status: z.string(),
  created_at: z.string(),
}).passthrough();

export type ImportFileMetaRecord = z.infer<typeof importFileMetaSchema>;

export const columnProfileSchema = z.object({
  name: z.string(),
  inferred_type: z.enum(importColumnTypes),
  nullable: z.boolean(),
  null_count: z.number(),
  distinct_count: z.number(),
  sample_values: z.array(z.string()),
  sensitivity: z.enum(importSensitivities),
}).passthrough();

export type ColumnProfileRecord = z.infer<typeof columnProfileSchema>;

export const schemaProfileSchema = z.object({
  file_id: z.string(),
  format: z.string(),
  row_count: z.number(),
  sampled_rows: z.number(),
  columns: z.array(columnProfileSchema),
  delimiter: z.string().nullish(),
  has_header: z.boolean().nullish(),
}).passthrough();

export type SchemaProfileRecord = z.infer<typeof schemaProfileSchema>;

export const fieldMappingSchema = z.object({
  source_column: z.string(),
  primitive: z.enum(importPrimitives),
  target_field: z.string(),
  transform: z.enum(importTransforms),
  required: z.boolean(),
}).passthrough();

export type FieldMappingRecord = z.infer<typeof fieldMappingSchema>;

export const importMappingSchema = z.object({
  id: z.string(),
  import_id: z.string(),
  version: z.number(),
  fields: z.array(fieldMappingSchema),
  created_at: z.string(),
}).passthrough();

export type ImportMappingRecord = z.infer<typeof importMappingSchema>;

export const validationErrorSchema = z.object({
  row: z.number(),
  source_column: z.string().nullish(),
  primitive: z.enum(importPrimitives).nullish(),
  code: z.string(),
  message: z.string(),
}).passthrough();

export const validationResultSchema = z.object({
  import_id: z.string(),
  mapping_version: z.number(),
  ok: z.boolean(),
  rows_total: z.number(),
  rows_valid: z.number(),
  rows_invalid: z.number(),
  errors: z.array(validationErrorSchema),
  errors_truncated: z.boolean(),
  governance_review_required: z.boolean(),
  governance_reasons: z.array(z.string()),
}).passthrough();

export type ValidationResultRecord = z.infer<typeof validationResultSchema>;

export const importTemplateSchema = z.object({
  id: z.string(),
  tenant_id: z.string(),
  name: z.string(),
  header_signature: z.string(),
  fields: z.array(fieldMappingSchema),
  created_at: z.string(),
  updated_at: z.string(),
}).passthrough();

export type ImportTemplateRecord = z.infer<typeof importTemplateSchema>;

export const importCommitSchema = z.object({
  id: z.string(),
  import_id: z.string().nullish(),
  status: z.string().nullish(),
  row_count: z.number().nullish(),
  vertices_count: z.number().nullish(),
  edges_count: z.number().nullish(),
  created_at: z.string().nullish(),
  created_by: z.string().nullish(),
}).passthrough();

export type ImportCommitRecord = z.infer<typeof importCommitSchema>;

const importJobSchema = z.object({
  id: z.string().nullish(),
  status: z.string().nullish(),
}).passthrough();

// ── Composite response schemas ──────────────────────────────────────────────

const importListSchema = z.object({
  imports: z.array(importSessionSchema),
  count: z.number(),
}).passthrough();

const importDetailSchema = z.object({
  session: importSessionSchema,
  files: z.array(importFileMetaSchema),
  schemas: z.array(schemaProfileSchema),
  mapping: importMappingSchema.nullish(),
  validation: validationResultSchema.nullish(),
}).passthrough();

export type ImportDetail = z.infer<typeof importDetailSchema>;

const analyzeResultSchema = z.object({
  import_id: z.string(),
  schemas: z.array(schemaProfileSchema),
  row_count: z.number(),
}).passthrough();

export type AnalyzeResult = z.infer<typeof analyzeResultSchema>;

const validateResponseSchema = z.object({
  status: z.enum(importStatuses),
  validation: validationResultSchema,
  review_reasons: z.array(z.string()).nullish(),
}).passthrough();

export type ValidateResponse = z.infer<typeof validateResponseSchema>;

const templateSuggestSchema = z.object({
  matched: importTemplateSchema.nullish(),
  candidates: z.array(importTemplateSchema),
}).passthrough();

export type TemplateSuggestResult = z.infer<typeof templateSuggestSchema>;

const templateListSchema = z.object({
  templates: z.array(importTemplateSchema),
  count: z.number(),
}).passthrough();

export type TemplateListResult = z.infer<typeof templateListSchema>;

const graphPreviewSchema = z.object({
  vertices: z.array(z.unknown()),
  edges: z.array(z.unknown()),
  counts: z.record(z.number()).nullish(),
}).passthrough();

export type GraphPreviewResult = z.infer<typeof graphPreviewSchema>;

const jobResponseSchema = z.object({
  import_id: z.string(),
  job: importJobSchema,
}).passthrough();

export type JobResponse = z.infer<typeof jobResponseSchema>;

const rollbackResultSchema = z.object({
  import_id: z.string().nullish(),
  status: z.string().nullish(),
  commit_id: z.string().nullish(),
  reason: z.string().nullish(),
  rolled_back: z.boolean().nullish(),
}).passthrough();

export type RollbackResult = z.infer<typeof rollbackResultSchema>;

const commitsListSchema = z.object({
  commits: z.array(importCommitSchema),
  count: z.number(),
}).passthrough();

export type CommitsListResult = z.infer<typeof commitsListSchema>;

// ── Fetchers ─────────────────────────────────────────────────────────────────

export interface ImportListParams {
  readonly limit?: number;
  readonly offset?: number;
}

export interface ImportListResult {
  readonly imports: ImportSessionRecord[];
  readonly count: number;
}

export function fetchImports(params?: ImportListParams): Promise<ImportListResult> {
  return restClient
    .get(
      `/v1/imports${buildQS({ limit: params?.limit, offset: params?.offset })}`,
      wrap(importListSchema),
    )
    .then(r => ({ imports: r.data.imports, count: r.data.count }));
}

export function createImport(): Promise<ImportSessionRecord> {
  return restClient
    .post('/v1/imports', wrap(importSessionSchema), {})
    .then(r => r.data);
}

export function fetchImportDetail(id: string): Promise<ImportDetail> {
  return restClient
    .get(`/v1/imports/${encodeURIComponent(id)}`, wrap(importDetailSchema))
    .then(r => r.data);
}

/**
 * Uploads raw file bytes to the import file endpoint. The backend expects the
 * request body to be the raw bytes (not JSON, not multipart) with a `filename`
 * query param — so this is a minimal manual fetch that reuses the same auth
 * headers as the shared REST client, and validates the parsed envelope.
 */
export async function uploadImportFile(id: string, file: File): Promise<ImportFileMetaRecord> {
  const text = await file.text();
  const correlationId = `aether-${Date.now()}-import-upload`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/octet-stream',
    'X-Correlation-ID': correlationId,
    'X-Aether-Environment': getEnvironment(),
  };
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const path = `/v1/imports/${encodeURIComponent(id)}/files?filename=${encodeURIComponent(file.name)}`;
  const response = await fetch(path, { method: 'POST', headers, body: text });

  if (!response.ok) {
    const problem: unknown = await response.json().catch(() => null);
    const message =
      (problem && typeof problem === 'object' && 'detail' in problem && typeof problem.detail === 'string'
        ? problem.detail
        : undefined) ?? `Upload failed (${response.status})`;
    throw new RestClientError(message, response.status, 'UPLOAD_FAILED', correlationId);
  }

  const json: unknown = await response.json();
  const parsed = wrap(importFileMetaSchema).safeParse(json);
  if (!parsed.success) {
    throw new RestClientError(
      `Upload response validation failed: ${parsed.error.issues.map(i => i.message).join(', ')}`,
      response.status,
      'VALIDATION_ERROR',
      correlationId,
    );
  }
  return parsed.data.data;
}

export function analyzeImport(id: string): Promise<AnalyzeResult> {
  return restClient
    .post(`/v1/imports/${encodeURIComponent(id)}/analyze`, wrap(analyzeResultSchema), {})
    .then(r => r.data);
}

export function putImportMapping(id: string, fields: FieldMapping[]): Promise<ImportMappingRecord> {
  return restClient
    .put(`/v1/imports/${encodeURIComponent(id)}/mapping`, wrap(importMappingSchema), { fields })
    .then(r => r.data);
}

export function validateImport(id: string): Promise<ValidateResponse> {
  return restClient
    .post(`/v1/imports/${encodeURIComponent(id)}/validate`, wrap(validateResponseSchema), {})
    .then(r => r.data);
}

export function approveImport(id: string): Promise<ImportSessionRecord> {
  return restClient
    .post(`/v1/imports/${encodeURIComponent(id)}/approve`, wrap(importSessionSchema), {})
    .then(r => r.data);
}

export function cancelImport(id: string): Promise<ImportSessionRecord> {
  return restClient
    .post(`/v1/imports/${encodeURIComponent(id)}/cancel`, wrap(importSessionSchema), {})
    .then(r => r.data);
}

export function suggestImportTemplates(id: string): Promise<TemplateSuggestResult> {
  return restClient
    .get(`/v1/imports/${encodeURIComponent(id)}/templates/suggest`, wrap(templateSuggestSchema))
    .then(r => r.data);
}

export function applyImportTemplate(id: string, templateId: string): Promise<ImportMappingRecord> {
  return restClient
    .post(`/v1/imports/${encodeURIComponent(id)}/apply-template`, wrap(importMappingSchema), {
      template_id: templateId,
    })
    .then(r => r.data);
}

export function fetchImportTemplates(): Promise<TemplateListResult> {
  return restClient
    .get('/v1/imports/templates', wrap(templateListSchema))
    .then(r => r.data);
}

export function graphPreviewImport(id: string): Promise<GraphPreviewResult> {
  return restClient
    .post(`/v1/imports/${encodeURIComponent(id)}/graph-preview`, wrap(graphPreviewSchema), {})
    .then(r => r.data);
}

export function commitImport(id: string): Promise<JobResponse> {
  return restClient
    .post(`/v1/imports/${encodeURIComponent(id)}/commit`, wrap(jobResponseSchema), {})
    .then(r => r.data);
}

export function replayImport(id: string): Promise<JobResponse> {
  return restClient
    .post(`/v1/imports/${encodeURIComponent(id)}/replay`, wrap(jobResponseSchema), {})
    .then(r => r.data);
}

export interface RollbackInput {
  readonly commit_id?: string;
  readonly reason?: string;
}

export function rollbackImport(id: string, input: RollbackInput): Promise<RollbackResult> {
  return restClient
    .post(`/v1/imports/${encodeURIComponent(id)}/rollback`, wrap(rollbackResultSchema), input)
    .then(r => r.data);
}

export function fetchImportCommits(id: string): Promise<CommitsListResult> {
  return restClient
    .get(`/v1/imports/${encodeURIComponent(id)}/commits`, wrap(commitsListSchema))
    .then(r => r.data);
}
