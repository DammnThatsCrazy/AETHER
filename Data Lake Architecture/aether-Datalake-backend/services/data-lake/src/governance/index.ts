// =============================================================================
// AETHER DATA LAKE — GOVERNANCE MODULE
// =============================================================================

export {
  SchemaEvolutionService,
  MigrationBuilder,
  InMemoryMigrationStore,
  type Migration,
  type MigrationAction,
  type MigrationStatus,
  type MigrationStore,
  type SchemaExecutor,
  type SchemaDiff,
} from './schema-evolution.js';

export {
  GdprGovernanceService,
  DEFAULT_DELETION_STRATEGIES,
  type DataSubjectRequest,
  type DataSubjectRequestType,
  type DsrStatus,
  type SubjectIdentifier,
  type ConsentRecord,
  type DeletionStrategy,
  type GovernanceConfig,
  type GovernanceExecutor,
  type IdentityResolver,
  type ComplianceSummary,
  type AuditEntry,
} from './gdpr-governance.js';

export {
  LifecycleManager,
  DEFAULT_LIFECYCLE_RULES,
  generateS3LifecyclePolicy,
  generateClickHouseTtl,
  type LifecycleRule,
  type LifecycleConfig,
  type LifecycleRunResult,
  type StorageClass,
  type StorageCostEstimate,
  type LifecycleAction,
  type ClickHouseLifecycleExecutor,
  type PartitionInfo,
} from './lifecycle-manager.js';
