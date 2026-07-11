/**
 * Canonical Tenant Import Engine contract.
 *
 * A tenant uploads a file (CSV / JSON / JSONL), Aether analyzes its schema, the
 * tenant maps source columns onto Aether's canonical primitives, a dry-run
 * validates the mapping, and — only after that — a commit stages the rows into
 * Bronze → Silver → the graph with full lineage. Every step is durable,
 * tenant-scoped, and auditable: nothing is reported imported until it is.
 *
 * The Python mirror lives at `services/imports/contracts.py`; the two const
 * arrays (`importStatuses`, `importPrimitives`, `importTransforms`,
 * `importColumnTypes`) are parity-tested against it.
 */

/**
 * Import session lifecycle. A session moves forward through these states; the
 * terminal states are `committed`, `partially_committed`, `failed`,
 * `cancelled`, and `rolled_back`.
 */
export const importStatuses = [
  'created',            // session created, no files yet
  'files_pending',      // one or more files registered, upload in progress
  'uploaded',           // file bytes present, ready to analyze
  'analyzing',          // schema analysis running
  'analyzed',           // schema profile available, ready to map
  'mapping',            // a mapping is being defined
  'mapped',             // mapping complete, ready to validate
  'validating',         // dry-run validation running
  'validated',          // validation passed (possibly with warnings)
  'review_required',    // governance flagged (PII / identifier / governance_fact)
  'approved',           // approved by a tenant admin, ready to commit
  'committing',         // commit job running
  'committed',          // fully staged to Bronze/Silver/graph
  'partially_committed',// some rows committed, some failed
  'failed',             // terminal failure
  'cancelled',          // cancelled by the tenant
  'rolled_back',        // committed then rolled back
] as const;

export type ImportStatus = typeof importStatuses[number];

/** Terminal states — a session in one of these accepts no further transitions. */
export const importTerminalStatuses: readonly ImportStatus[] = [
  'committed',
  'partially_committed',
  'failed',
  'cancelled',
  'rolled_back',
] as const;

/**
 * The nine canonical primitives a mapped row can become. A row that matches
 * none is preserved as an `unmapped_record` — never silently dropped.
 */
export const importPrimitives = [
  'entity',           // a node: person, org, wallet, device, …
  'identifier',       // an identifier attached to an entity (email, wallet, device id)
  'action',           // an event / action performed at a time
  'relationship',     // an edge between two entities
  'resource',         // a resource / asset: campaign, product, content
  'evidence',         // an evidence / proof observation
  'metric',           // a measured value attached to an entity
  'governance_fact',  // a consent / policy / governance fact
  'unmapped_record',  // a row that mapped to no primitive (preserved verbatim)
] as const;

export type ImportPrimitive = typeof importPrimitives[number];

/**
 * The canonical target fields for each primitive. A mapping targets
 * `primitive.field`; a field not in this registry is rejected at map time.
 */
export const importPrimitiveFields: Record<ImportPrimitive, readonly string[]> = {
  entity: ['entity_type', 'external_id', 'display_name', 'attributes'],
  identifier: ['identifier_type', 'value', 'entity_ref', 'confidence'],
  action: ['action_type', 'occurred_at', 'entity_ref', 'resource_ref', 'properties'],
  relationship: ['relationship_type', 'from_ref', 'to_ref', 'weight', 'properties'],
  resource: ['resource_type', 'external_id', 'name', 'attributes'],
  evidence: ['evidence_type', 'subject_ref', 'source', 'observed_at', 'payload'],
  metric: ['metric_name', 'entity_ref', 'value', 'unit', 'observed_at'],
  governance_fact: ['fact_type', 'subject_ref', 'basis', 'granted_at', 'expires_at', 'scope'],
  unmapped_record: ['raw'],
} as const;

/** Deterministic per-field transforms a mapping may apply to a source value. */
export const importTransforms = [
  'none',
  'trim',
  'lowercase',
  'uppercase',
  'to_timestamp',
  'to_number',
  'to_boolean',
  'hash_sha256',
  'json_parse',
  'coalesce_empty_null',
] as const;

export type ImportTransform = typeof importTransforms[number];

/** Column types the analyzer infers from sampled values. */
export const importColumnTypes = [
  'string',
  'integer',
  'float',
  'boolean',
  'datetime',
  'date',
  'json',
  'email',
  'url',
  'wallet_address',
  'phone',
  'uuid',
  'empty',
  'mixed',
] as const;

export type ImportColumnType = typeof importColumnTypes[number];

/** Sensitivity a column may carry — drives governance review gating. */
export const importSensitivities = [
  'none',
  'pii',
  'identifier',
  'secret',
  'governance',
] as const;

export type ImportSensitivity = typeof importSensitivities[number];

// ── shapes ────────────────────────────────────────────────────────────────

export interface ImportSession {
  id: string;
  tenant_id: string;
  status: ImportStatus;
  source_kind: string;         // 'file_upload'
  file_count: number;
  row_count?: number | null;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ImportFileMeta {
  id: string;
  import_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  status: string;              // 'pending' | 'stored'
  created_at: string;
}

/** Per-column profile from schema analysis. */
export interface ColumnProfile {
  name: string;
  inferred_type: ImportColumnType;
  nullable: boolean;
  null_count: number;
  distinct_count: number;
  sample_values: string[];
  sensitivity: ImportSensitivity;
}

export interface SchemaProfile {
  file_id: string;
  format: string;              // 'csv' | 'json' | 'jsonl'
  row_count: number;
  sampled_rows: number;
  columns: ColumnProfile[];
  delimiter?: string | null;
  has_header?: boolean;
}

/** One source-column → primitive-field mapping rule. */
export interface FieldMapping {
  source_column: string;
  primitive: ImportPrimitive;
  target_field: string;
  transform: ImportTransform;
  required: boolean;
}

export interface ImportMapping {
  id: string;
  import_id: string;
  version: number;
  fields: FieldMapping[];
  created_at: string;
}

export interface ValidationError {
  row: number;
  source_column?: string | null;
  primitive?: ImportPrimitive | null;
  code: string;
  message: string;
}

export interface ValidationResult {
  import_id: string;
  mapping_version: number;
  ok: boolean;
  rows_total: number;
  rows_valid: number;
  rows_invalid: number;
  errors: ValidationError[];   // capped
  errors_truncated: boolean;
  governance_review_required: boolean;
  governance_reasons: string[];
}

export interface ImportTemplate {
  id: string;
  tenant_id: string;
  name: string;
  header_signature: string;    // stable hash of the source header set
  fields: FieldMapping[];
  created_at: string;
  updated_at: string;
}

// ── helpers ─────────────────────────────────────────────────────────────

/** True when a session is in a terminal state. */
export function isTerminalImportStatus(status: ImportStatus): boolean {
  return importTerminalStatuses.includes(status);
}

/** Canonical target fields for a primitive (empty array for an unknown one). */
export function primitiveFields(primitive: ImportPrimitive): readonly string[] {
  return importPrimitiveFields[primitive] ?? [];
}
