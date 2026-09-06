/**
 * Canonical Data Exchange Plane contract.
 *
 * The Data Exchange Plane is Aether's governed, tenant-facing import/export
 * layer: *many ways in — one canonical graph — many ways out — one governed
 * portability layer*. Every ingress and egress artifact shares one contract
 * vocabulary (direction, status, format, classification, source type) plus
 * the five canonical exchange contracts.
 *
 * The Python mirror lives at
 * `Backend Architecture/aether-backend/services/data_exchange/contracts.py`;
 * the const arrays below are parity-tested against it by
 * `tests/contracts/test_data_exchange_parity.py`.
 *
 * Milestone status (M0): declared-but-dark. No route, table, or job consumes
 * these yet.
 */

export const dataExchangeDirections = ['ingress', 'egress'] as const;
export type DataExchangeDirection = (typeof dataExchangeDirections)[number];

/** One status vocabulary for every artifact regardless of direction. A status
 * is explicit — never inferred from the existence of bytes. */
export const dataArtifactStatuses = [
  'created',
  'upload_pending',
  'uploading',
  'uploaded',
  'scanning',
  'analyzing',
  'ready',
  'processing',
  'committed',
  'partially_committed',
  'generating',
  'available',
  'failed',
  'expired',
  'deleted',
  'revoked',
] as const;
export type DataArtifactStatus = (typeof dataArtifactStatuses)[number];

/** `available`/`committed` require durable bytes *and* a verified checksum. */
export const dataArtifactTerminalStatuses = [
  'committed',
  'partially_committed',
  'available',
  'failed',
  'expired',
  'deleted',
  'revoked',
] as const;
export type DataArtifactTerminalStatus = (typeof dataArtifactTerminalStatuses)[number];

/** Ingress speaks `jsonl`; egress speaks `ndjson`. PDF is never a structured
 * format — it is a ReportSpecContract artifact. */
export const dataExchangeIngressFormats = ['csv', 'json', 'jsonl', 'parquet'] as const;
export type DataExchangeIngressFormat = (typeof dataExchangeIngressFormats)[number];

export const dataExchangeEgressFormats = ['csv', 'json', 'ndjson', 'parquet'] as const;
export type DataExchangeEgressFormat = (typeof dataExchangeEgressFormats)[number];

/** Day-one UI exposes `file`; s3/api/connector/warehouse ride the same schema. */
export const dataExchangeSourceTypes = ['file', 's3', 'api', 'connector', 'warehouse'] as const;
export type DataExchangeSourceType = (typeof dataExchangeSourceTypes)[number];

export const dataExchangeClassifications = [
  'none',
  'identifier',
  'pii',
  'secret',
  'credential',
  'governance',
  'financial',
  'location',
  'temporal',
] as const;
export type DataExchangeClassification = (typeof dataExchangeClassifications)[number];

/** Classifications blocked from graph commit by default unless an elevated
 * tenant policy explicitly permits them. */
export const dataExchangeBlockedClassifications = ['secret', 'credential'] as const;
export type DataExchangeBlockedClassification = (typeof dataExchangeBlockedClassifications)[number];

// ── helpers ────────────────────────────────────────────────────────────────

export function isDataArtifactStatus(value: string): value is DataArtifactStatus {
  return (dataArtifactStatuses as readonly string[]).includes(value);
}

export function isTerminalDataArtifactStatus(value: string): value is DataArtifactTerminalStatus {
  return (dataArtifactTerminalStatuses as readonly string[]).includes(value);
}

export function isIngressFormat(value: string): value is DataExchangeIngressFormat {
  return (dataExchangeIngressFormats as readonly string[]).includes(value);
}

export function isEgressFormat(value: string): value is DataExchangeEgressFormat {
  return (dataExchangeEgressFormats as readonly string[]).includes(value);
}

/** Day-one defaults: secrets and credentials are blocked from the graph. */
export function classificationBlockedByDefault(classification: string): boolean {
  return (dataExchangeBlockedClassifications as readonly string[]).includes(classification);
}

// ── canonical exchange contracts ───────────────────────────────────────────

export interface DataArtifactContract {
  artifact_id: string;
  tenant_id: string;
  direction: DataExchangeDirection;
  artifact_type: string;
  job_id?: string | null;
  source_or_destination?: Record<string, unknown>;
  object_key: string;
  filename: string;
  format: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  schema_version?: string | null;
  classification: DataExchangeClassification;
  encryption?: Record<string, unknown>;
  manifest?: Record<string, unknown>;
  status: DataArtifactStatus;
  created_by?: string | null;
  correlation_id?: string | null;
  created_at: string;
  expires_at?: string | null;
  deleted_at?: string | null;
}

export interface ImportSourceContract {
  import_id: string;
  tenant_id: string;
  source_type: DataExchangeSourceType;
  artifact_id: string;
  format: DataExchangeIngressFormat;
  schema_version?: string | null;
  declared_timezone?: string | null;
  declared_currency?: string | null;
  ownership?: 'tenant_owned' | 'licensed' | 'unknown';
  terms_status?: string;
  provenance?: Record<string, unknown>;
}

export interface ImportMappingContract {
  import_id: string;
  tenant_id: string;
  version: number;
  fields?: Record<string, unknown>[];
  identity_policy?: Record<string, unknown>;
  temporal_policy?: Record<string, unknown>;
  currency_policy?: Record<string, unknown>;
  geographic_policy?: Record<string, unknown>;
  consent_policy?: Record<string, unknown>;
  unknown_field_policy?: 'error' | 'ignore';
  created_by?: string | null;
  created_at: string;
}

export interface ExportSpecContract {
  export_id: string;
  tenant_id: string;
  resource: string;
  scope?: Record<string, unknown>;
  fields?: string[] | null;
  include_relationships?: boolean;
  include_identifiers?: boolean;
  include_provenance?: boolean;
  include_raw_events?: boolean;
  filters?: Record<string, unknown>;
  temporal?: Record<string, unknown>;
  display_timezone?: string;
  format: DataExchangeEgressFormat;
  compression?: 'gzip' | 'snappy' | 'zstd' | null;
  destination?: Record<string, unknown>;
  requested_by?: string | null;
}

export interface ReportSpecContract {
  report_id: string;
  tenant_id: string;
  resource: string;
  scope?: Record<string, unknown>;
  temporal?: Record<string, unknown>;
  filters?: Record<string, unknown>;
  display_timezone?: string;
  template: string;
  include_methodology?: boolean;
  include_provenance_summary?: boolean;
  requested_by?: string | null;
}
