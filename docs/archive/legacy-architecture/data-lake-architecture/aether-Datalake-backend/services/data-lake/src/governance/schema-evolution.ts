// =============================================================================
// Aether DATA LAKE — SCHEMA EVOLUTION MANAGER
// Manages backward-compatible schema changes, migration tracking,
// column additions/deprecations, and type promotions across medallion tiers
// =============================================================================

import { randomUUID } from 'node:crypto';
import { createLogger } from '@aether/logger';
import type { ColumnDefinition, ColumnType, MedallionTier, TableDefinition } from '../schema/types.js';

const logger = createLogger('aether.datalake.schema-evolution');

// =============================================================================
// MIGRATION TYPES
// =============================================================================

export type MigrationAction =
  | 'add_column'
  | 'deprecate_column'
  | 'rename_column'
  | 'widen_type'
  | 'add_index'
  | 'modify_ttl'
  | 'add_materialized_view'
  | 'drop_materialized_view'
  | 'modify_settings';

export type MigrationStatus = 'pending' | 'applied' | 'rolled_back' | 'failed';

export interface Migration {
  id: string;
  version: number;
  name: string;
  description: string;
  table: string;
  tier: MedallionTier;
  action: MigrationAction;
  /** The DDL or change specification */
  upSql: string;
  /** Rollback DDL (null if irreversible) */
  downSql: string | null;
  /** Whether this migration is backward-compatible */
  isBackwardCompatible: boolean;
  status: MigrationStatus;
  createdAt: string;
  appliedAt?: string;
  appliedBy?: string;
  checksum: string;
}

/** Safe type widening rules — source type can be promoted to target type */
const SAFE_TYPE_PROMOTIONS: Map<ColumnType, ColumnType[]> = new Map([
  ['UInt8',   ['UInt16', 'UInt32', 'UInt64', 'Int16', 'Int32', 'Int64', 'Float32', 'Float64']],
  ['UInt16',  ['UInt32', 'UInt64', 'Int32', 'Int64', 'Float32', 'Float64']],
  ['UInt32',  ['UInt64', 'Int64', 'Float64']],
  ['Int8',    ['Int16', 'Int32', 'Int64', 'Float32', 'Float64']],
  ['Int16',   ['Int32', 'Int64', 'Float32', 'Float64']],
  ['Int32',   ['Int64', 'Float64']],
  ['Float32', ['Float64']],
  ['String',  []], // String is terminal — no widening
  ['Date',    ['DateTime', 'DateTime64']],
  ['DateTime', ['DateTime64']],
]);

// =============================================================================
// MIGRATION BUILDER
// =============================================================================

export class MigrationBuilder {
  private migrations: Migration[] = [];
  private version: number;
  private database: string;

  constructor(startVersion: number = 1, database: string = 'aether') {
    this.version = startVersion;
    this.database = database;
  }

  /** Add a nullable column (always backward-compatible) */
  addColumn(
    table: string,
    tier: MedallionTier,
    column: ColumnDefinition,
    description: string,
  ): this {
    const fqTable = `${this.database}.${table}`;
    const colType = column.nullable && !column.type.startsWith('Nullable')
      ? `Nullable(${column.type})`
      : column.type;

    const defaultClause = column.defaultExpr
      ? ` DEFAULT ${column.defaultExpr}`
      : '';

    const upSql = `ALTER TABLE ${fqTable} ADD COLUMN IF NOT EXISTS ${column.name} ${colType}${defaultClause} COMMENT '${column.description.replace(/'/g, "''")}';`;
    const downSql = `ALTER TABLE ${fqTable} DROP COLUMN IF EXISTS ${column.name};`;

    this.migrations.push(this.createMigration({
      name: `add_${table}_${column.name}`,
      description,
      table,
      tier,
      action: 'add_column',
      upSql,
      downSql,
      isBackwardCompatible: true,
    }));

    return this;
  }

  /** Deprecate a column (marks it with a comment, does not drop) */
  deprecateColumn(
    table: string,
    tier: MedallionTier,
    columnName: string,
    reason: string,
  ): this {
    const fqTable = `${this.database}.${table}`;
    const upSql = `ALTER TABLE ${fqTable} COMMENT COLUMN ${columnName} 'DEPRECATED: ${reason.replace(/'/g, "''")} — scheduled for removal';`;
    const downSql = `ALTER TABLE ${fqTable} COMMENT COLUMN ${columnName} '';`;

    this.migrations.push(this.createMigration({
      name: `deprecate_${table}_${columnName}`,
      description: `Deprecate ${columnName}: ${reason}`,
      table,
      tier,
      action: 'deprecate_column',
      upSql,
      downSql,
      isBackwardCompatible: true,
    }));

    return this;
  }

  /** Widen a column type (must be in SAFE_TYPE_PROMOTIONS) */
  widenType(
    table: string,
    tier: MedallionTier,
    columnName: string,
    fromType: ColumnType,
    toType: ColumnType,
  ): this {
    const allowed = SAFE_TYPE_PROMOTIONS.get(fromType) ?? [];
    if (!allowed.includes(toType)) {
      throw new Error(
        `Unsafe type promotion: ${fromType} → ${toType} for ${table}.${columnName}. ` +
        `Allowed promotions: ${allowed.join(', ') || 'none'}`,
      );
    }

    const fqTable = `${this.database}.${table}`;
    const upSql = `ALTER TABLE ${fqTable} MODIFY COLUMN ${columnName} ${toType};`;
    const downSql = null; // Type narrowing is destructive — no rollback

    this.migrations.push(this.createMigration({
      name: `widen_${table}_${columnName}_${fromType}_to_${toType}`,
      description: `Widen ${table}.${columnName} from ${fromType} to ${toType}`,
      table,
      tier,
      action: 'widen_type',
      upSql,
      downSql,
      isBackwardCompatible: true,
    }));

    return this;
  }

  /** Modify table TTL */
  modifyTtl(
    table: string,
    tier: MedallionTier,
    ttlExpression: string,
  ): this {
    const fqTable = `${this.database}.${table}`;
    const upSql = `ALTER TABLE ${fqTable} MODIFY TTL ${ttlExpression};`;
    const downSql = null;

    this.migrations.push(this.createMigration({
      name: `ttl_${table}`,
      description: `Modify TTL for ${table}: ${ttlExpression}`,
      table,
      tier,
      action: 'modify_ttl',
      upSql,
      downSql,
      isBackwardCompatible: true,
    }));

    return this;
  }

  /** Add a materialized view */
  addMaterializedView(
    viewName: string,
    table: string,
    tier: MedallionTier,
    selectSql: string,
    engine: string,
    orderBy: string[],
  ): this {
    const fqView = `${this.database}.${viewName}`;
    const fqTable = `${this.database}.${table}`;
    const upSql = [
      `CREATE MATERIALIZED VIEW IF NOT EXISTS ${fqView}`,
      `ENGINE = ${engine}`,
      `ORDER BY (${orderBy.join(', ')})`,
      `AS ${selectSql};`,
    ].join('\n');
    const downSql = `DROP VIEW IF EXISTS ${fqView};`;

    this.migrations.push(this.createMigration({
      name: `mv_${viewName}`,
      description: `Create materialized view ${viewName} on ${table}`,
      table,
      tier,
      action: 'add_materialized_view',
      upSql,
      downSql,
      isBackwardCompatible: true,
    }));

    return this;
  }

  /** Build all migrations and reset */
  build(): Migration[] {
    const result = [...this.migrations];
    this.migrations = [];
    return result;
  }

  private createMigration(params: Omit<Migration, 'id' | 'version' | 'status' | 'createdAt' | 'checksum'>): Migration {
    const version = this.version++;
    const id = randomUUID();
    const body = `${version}:${params.name}:${params.upSql}`;
    // Simple checksum (production: use SHA-256)
    let hash = 0;
    for (let i = 0; i < body.length; i++) {
      hash = ((hash << 5) - hash + body.charCodeAt(i)) | 0;
    }
    const checksum = Math.abs(hash).toString(16).padStart(8, '0');

    return {
      id,
      version,
      createdAt: new Date().toISOString(),
      status: 'pending',
      checksum,
      ...params,
    };
  }
}

// =============================================================================
// SCHEMA EVOLUTION SERVICE
// =============================================================================

export interface MigrationStore {
  getApplied(): Promise<Migration[]>;
  save(migration: Migration): Promise<void>;
  updateStatus(id: string, status: MigrationStatus, appliedAt?: string): Promise<void>;
}

/** In-memory migration store (dev/test) */
export class InMemoryMigrationStore implements MigrationStore {
  private migrations: Migration[] = [];

  async getApplied(): Promise<Migration[]> {
    return this.migrations.filter(m => m.status === 'applied');
  }

  async save(migration: Migration): Promise<void> {
    this.migrations.push(migration);
  }

  async updateStatus(id: string, status: MigrationStatus, appliedAt?: string): Promise<void> {
    const m = this.migrations.find(m => m.id === id);
    if (m) {
      m.status = status;
      if (appliedAt) m.appliedAt = appliedAt;
    }
  }
}

export interface SchemaExecutor {
  execute(sql: string): Promise<void>;
}

export class SchemaEvolutionService {
  private store: MigrationStore;
  private executor: SchemaExecutor;

  constructor(store: MigrationStore, executor: SchemaExecutor) {
    this.store = store;
    this.executor = executor;
  }

  /** Apply all pending migrations in order */
  async migrate(migrations: Migration[]): Promise<{ applied: number; skipped: number; failed: string[] }> {
    const applied = await this.store.getApplied();
    const appliedVersions = new Set(applied.map(m => m.version));

    let appliedCount = 0;
    let skippedCount = 0;
    const failed: string[] = [];

    // Sort by version
    const sorted = [...migrations].sort((a, b) => a.version - b.version);

    for (const migration of sorted) {
      if (appliedVersions.has(migration.version)) {
        // Verify checksum matches
        const existing = applied.find(m => m.version === migration.version);
        if (existing && existing.checksum !== migration.checksum) {
          logger.error('Checksum mismatch for applied migration', {
            version: migration.version,
            name: migration.name,
            expected: existing.checksum,
            actual: migration.checksum,
          });
          failed.push(`${migration.name}: checksum mismatch`);
        }
        skippedCount++;
        continue;
      }

      try {
        logger.info('Applying migration', {
          version: migration.version,
          name: migration.name,
          action: migration.action,
          table: migration.table,
        });

        await this.executor.execute(migration.upSql);

        migration.status = 'applied';
        migration.appliedAt = new Date().toISOString();
        await this.store.save(migration);
        await this.store.updateStatus(migration.id, 'applied', migration.appliedAt);

        appliedCount++;

        logger.info('Migration applied successfully', {
          version: migration.version,
          name: migration.name,
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error('Migration failed', {
          version: migration.version,
          name: migration.name,
          error: message,
        });

        migration.status = 'failed';
        await this.store.save(migration);
        await this.store.updateStatus(migration.id, 'failed');

        failed.push(`${migration.name}: ${message}`);

        // Stop on first failure unless it's backward-compatible
        if (!migration.isBackwardCompatible) {
          logger.error('Non-backward-compatible migration failed — halting');
          break;
        }
      }
    }

    return { applied: appliedCount, skipped: skippedCount, failed };
  }

  /** Rollback the most recently applied migration */
  async rollback(): Promise<{ rolledBack: string | null; error?: string }> {
    const applied = await this.store.getApplied();
    if (applied.length === 0) {
      return { rolledBack: null };
    }

    const latest = applied.sort((a, b) => b.version - a.version)[0];

    if (!latest.downSql) {
      return { rolledBack: null, error: `Migration ${latest.name} is irreversible (no down SQL)` };
    }

    try {
      logger.info('Rolling back migration', { version: latest.version, name: latest.name });
      await this.executor.execute(latest.downSql);
      await this.store.updateStatus(latest.id, 'rolled_back');
      return { rolledBack: latest.name };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      logger.error('Rollback failed', { version: latest.version, error: message });
      return { rolledBack: null, error: message };
    }
  }

  /** Diff current table definitions against applied schema */
  async diff(currentTables: TableDefinition[]): Promise<SchemaDiff[]> {
    const applied = await this.store.getApplied();
    const diffs: SchemaDiff[] = [];

    for (const table of currentTables) {
      // Check if columns were added in code but not yet migrated
      const tablesMigrations = applied.filter(m => m.table === table.name);
      const addedColumns = new Set(
        tablesMigrations
          .filter(m => m.action === 'add_column' && m.status === 'applied')
          .map(m => m.name.replace(`add_${table.name}_`, '')),
      );

      for (const col of table.columns) {
        // This is a simplified diff — production would compare against live schema
        if (!addedColumns.has(col.name)) {
          diffs.push({
            table: table.name,
            tier: table.tier,
            type: 'column_in_code_not_in_db',
            column: col.name,
            detail: `Column ${col.name} (${col.type}) exists in code but has no migration`,
          });
        }
      }
    }

    return diffs;
  }

  /** Get migration status summary */
  async status(): Promise<{
    totalApplied: number;
    latestVersion: number;
    latestName: string;
    latestAppliedAt: string;
  }> {
    const applied = await this.store.getApplied();
    const sorted = applied.sort((a, b) => b.version - a.version);
    const latest = sorted[0];

    return {
      totalApplied: applied.length,
      latestVersion: latest?.version ?? 0,
      latestName: latest?.name ?? 'none',
      latestAppliedAt: latest?.appliedAt ?? 'never',
    };
  }
}

export interface SchemaDiff {
  table: string;
  tier: MedallionTier;
  type: 'column_in_code_not_in_db' | 'column_in_db_not_in_code' | 'type_mismatch' | 'ttl_mismatch';
  column?: string;
  detail: string;
}
