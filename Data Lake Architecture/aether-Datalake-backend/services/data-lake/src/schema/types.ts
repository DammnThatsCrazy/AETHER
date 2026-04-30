// =============================================================================
// Aether DATA LAKE — TYPE DEFINITIONS
// Medallion architecture types: Bronze (raw) → Silver (clean) → Gold (aggregated)
// =============================================================================

// =============================================================================
// MEDALLION TIERS
// =============================================================================

export type MedallionTier = 'bronze' | 'silver' | 'gold';

export type FileFormat = 'jsonl' | 'parquet' | 'orc' | 'avro' | 'csv';
export type CompressionCodec = 'gzip' | 'snappy' | 'zstd' | 'lz4' | 'none';

export interface TierConfig {
  tier: MedallionTier;
  bucket: string;
  prefix: string;
  format: FileFormat;
  compression: CompressionCodec;
  partitionScheme: PartitionScheme;
  retentionDays: number;
  compactionEnabled: boolean;
  compactionTargetSizeMb: number;
  qualityChecksEnabled: boolean;
}

// =============================================================================
// PARTITIONING
// =============================================================================

export type PartitionGranularity = 'hour' | 'day' | 'month';

export interface PartitionScheme {
  /** Time-based partition column */
  timeColumn: string;
  granularity: PartitionGranularity;
  /** Additional partition columns (e.g. project_id, event_type) */
  extraColumns: string[];
}

export interface PartitionKey {
  year: number;
  month: number;
  day: number;
  hour?: number;
  extraValues: Record<string, string>;
}

/** Generate an S3 prefix from a partition key */
export function partitionPath(tier: MedallionTier, prefix: string, key: PartitionKey): string {
  const parts = [
    prefix,
    tier,
    `year=${key.year}`,
    `month=${String(key.month).padStart(2, '0')}`,
    `day=${String(key.day).padStart(2, '0')}`,
  ];

  if (key.hour !== undefined) {
    parts.push(`hour=${String(key.hour).padStart(2, '0')}`);
  }

  for (const [col, val] of Object.entries(key.extraValues)) {
    parts.push(`${col}=${val}`);
  }

  return parts.join('/');
}

/** Parse a timestamp into a partition key */
export function timestampToPartition(
  timestamp: string,
  granularity: PartitionGranularity,
  extraValues: Record<string, string> = {},
): PartitionKey {
  const dt = new Date(timestamp);
  return {
    year: dt.getUTCFullYear(),
    month: dt.getUTCMonth() + 1,
    day: dt.getUTCDate(),
    hour: granularity === 'hour' ? dt.getUTCHours() : undefined,
    extraValues,
  };
}

// =============================================================================
// TABLE DEFINITIONS
// =============================================================================

export type ColumnType =
  | 'String' | 'UInt8' | 'UInt16' | 'UInt32' | 'UInt64'
  | 'Int8' | 'Int16' | 'Int32' | 'Int64'
  | 'Float32' | 'Float64'
  | 'DateTime' | 'DateTime64' | 'Date'
  | 'Bool' | 'UUID'
  | 'JSON' | 'Map(String, String)'
  | 'Array(String)' | 'LowCardinality(String)'
  | 'Nullable(String)' | 'Nullable(Float64)' | 'Nullable(Float32)'
  | 'Nullable(UInt16)' | 'Nullable(UInt32)' | 'Nullable(DateTime64)'
  | 'Nullable(Bool)';

export interface ColumnDefinition {
  name: string;
  type: ColumnType;
  description: string;
  nullable: boolean;
  /** Default value expression */
  defaultExpr?: string;
  /** Used as partition key */
  isPartitionKey?: boolean;
  /** Included in sort/order key */
  isSortKey?: boolean;
  /** Sort key position (1-based) */
  sortKeyOrder?: number;
}

export interface TableDefinition {
  name: string;
  tier: MedallionTier;
  description: string;
  columns: ColumnDefinition[];
  engine: ClickHouseEngine;
  partitionBy: string;
  orderBy: string[];
  ttlDays?: number;
  settings?: Record<string, string | number>;
}

export type ClickHouseEngine =
  | 'MergeTree'
  | 'ReplacingMergeTree'
  | 'SummingMergeTree'
  | 'AggregatingMergeTree'
  | 'CollapsingMergeTree'
  | 'VersionedCollapsingMergeTree';

// =============================================================================
// DATA LAKE FILE METADATA
// =============================================================================

export interface DataLakeFile {
  path: string;
  bucket: string;
  tier: MedallionTier;
  partition: PartitionKey;
  format: FileFormat;
  compression: CompressionCodec;
  sizeBytes: number;
  rowCount: number;
  createdAt: string;
  checksum: string;
  /** Schema version used to write this file */
  schemaVersion: number;
  /** Source file paths (for lineage) */
  sourcePaths?: string[];
}

// =============================================================================
// ETL JOB DEFINITIONS
// =============================================================================

export type EtlJobStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface EtlJob {
  id: string;
  name: string;
  sourceTier: MedallionTier;
  targetTier: MedallionTier;
  sourceTable: string;
  targetTable: string;
  status: EtlJobStatus;
  startedAt?: string;
  completedAt?: string;
  inputRows: number;
  outputRows: number;
  droppedRows: number;
  errorMessage?: string;
  durationMs?: number;
  partition: PartitionKey;
  /** Idempotency key to prevent double-processing */
  checkpointId: string;
}

// =============================================================================
// DATA QUALITY
// =============================================================================

export type QualityCheckType =
  | 'completeness'     // Non-null rate
  | 'freshness'        // Max lag from event time to arrival
  | 'uniqueness'       // Dedup ratio
  | 'volume'           // Row count within expected range
  | 'schema'           // All required columns present and typed
  | 'distribution'     // Value distribution within thresholds
  | 'referential';     // Foreign key consistency

export type QualitySeverity = 'info' | 'warning' | 'critical';

export interface QualityCheck {
  id: string;
  name: string;
  type: QualityCheckType;
  table: string;
  tier: MedallionTier;
  severity: QualitySeverity;
  /** SQL or expression to evaluate */
  expression: string;
  /** Threshold for pass/fail */
  threshold: number;
  /** Description of what this check validates */
  description: string;
}

export interface QualityResult {
  checkId: string;
  checkName: string;
  passed: boolean;
  actualValue: number;
  threshold: number;
  severity: QualitySeverity;
  table: string;
  partition: string;
  evaluatedAt: string;
  message: string;
}

// =============================================================================
// COMPACTION
// =============================================================================

export interface CompactionJob {
  id: string;
  tier: MedallionTier;
  table: string;
  partition: string;
  inputFiles: number;
  inputSizeBytes: number;
  outputFiles: number;
  outputSizeBytes: number;
  status: EtlJobStatus;
  startedAt?: string;
  completedAt?: string;
  compressionRatio?: number;
}

// =============================================================================
// CATALOG / SCHEMA REGISTRY
// =============================================================================

export interface CatalogEntry {
  database: string;
  table: string;
  tier: MedallionTier;
  description: string;
  owner: string;
  schemaVersion: number;
  columns: ColumnDefinition[];
  partitionKeys: string[];
  sortKeys: string[];
  createdAt: string;
  updatedAt: string;
  rowCount: number;
  sizeBytes: number;
  tags: string[];
  lineage: LineageInfo;
}

export interface LineageInfo {
  /** Upstream tables this table depends on */
  upstream: string[];
  /** Downstream tables that depend on this table */
  downstream: string[];
  /** ETL job that populates this table */
  etlJobName?: string;
  /** Refresh schedule (cron expression) */
  schedule?: string;
}

// =============================================================================
// ENRICHED EVENT (from ingestion pipeline → data lake)
// =============================================================================

export interface EnrichedEvent {
  id: string;
  type: string;
  timestamp: string;
  anonymousId: string;
  userId?: string;
  sessionId: string;
  projectId: string;
  receivedAt: string;
  sentAt?: string;
  properties?: Record<string, unknown>;
  context?: {
    page?: { url?: string; path?: string; title?: string; referrer?: string; search?: string };
    device?: {
      type?: string; browser?: string; browserVersion?: string;
      os?: string; osVersion?: string;
      screenWidth?: number; screenHeight?: number;
      viewportWidth?: number; viewportHeight?: number;
      pixelRatio?: number; language?: string;
    };
    campaign?: {
      source?: string; medium?: string; campaign?: string;
      content?: string; term?: string; clickId?: string;
      referrerDomain?: string; referrerType?: string;
    };
    sdk?: { name?: string; version?: string };
    consent?: { analytics?: boolean; marketing?: boolean; web3?: boolean };
    library?: { name?: string; version?: string };
    timezone?: string;
  };
  enrichment?: {
    geo?: { countryCode?: string; region?: string; city?: string; latitude?: number; longitude?: number; timezone?: string };
    parsedUA?: { browser?: string; browserVersion?: string; os?: string; osVersion?: string; device?: string };
    anonymizedIp?: string;
    botProbability?: number;
    pipelineVersion?: string;
  };
  partitionKey?: string;
}
