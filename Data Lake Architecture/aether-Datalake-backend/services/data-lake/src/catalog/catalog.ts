// =============================================================================
// AETHER DATA LAKE — DATA CATALOG
// Schema registry, lineage graph, metadata management, and discovery
// Central source of truth for all tables, columns, and data lineage
// =============================================================================

import { createLogger } from '@aether/logger';
import type { CatalogEntry, LineageInfo, ColumnDefinition, MedallionTier } from '../schema/types.js';
import { ALL_TABLES } from '../schema/tables.js';

const logger = createLogger('aether.datalake.catalog');

// =============================================================================
// CATALOG SERVICE
// =============================================================================

export class DataCatalog {
  private entries = new Map<string, CatalogEntry>();

  constructor() {
    this.bootstrapFromDefinitions();
  }

  // ===========================================================================
  // REGISTRATION
  // ===========================================================================

  /** Register or update a table in the catalog */
  register(entry: CatalogEntry): void {
    const key = `${entry.database}.${entry.table}`;
    const existing = this.entries.get(key);

    if (existing) {
      // Schema evolution: bump version if columns changed
      const columnsChanged = JSON.stringify(existing.columns) !== JSON.stringify(entry.columns);
      entry.schemaVersion = columnsChanged ? existing.schemaVersion + 1 : existing.schemaVersion;
      entry.createdAt = existing.createdAt;
    }

    entry.updatedAt = new Date().toISOString();
    this.entries.set(key, entry);

    logger.info('Catalog entry registered', {
      table: key,
      tier: entry.tier,
      schemaVersion: entry.schemaVersion,
      columns: entry.columns.length,
    });
  }

  /** Deregister a table */
  deregister(database: string, table: string): boolean {
    return this.entries.delete(`${database}.${table}`);
  }

  // ===========================================================================
  // DISCOVERY
  // ===========================================================================

  /** Get a specific table entry */
  getTable(database: string, table: string): CatalogEntry | undefined {
    return this.entries.get(`${database}.${table}`);
  }

  /** List all tables */
  listTables(): CatalogEntry[] {
    return Array.from(this.entries.values());
  }

  /** List tables by medallion tier */
  listByTier(tier: MedallionTier): CatalogEntry[] {
    return this.listTables().filter(e => e.tier === tier);
  }

  /** Search tables by name or description */
  search(query: string): CatalogEntry[] {
    const q = query.toLowerCase();
    return this.listTables().filter(e =>
      e.table.toLowerCase().includes(q) ||
      e.description.toLowerCase().includes(q) ||
      e.tags.some(t => t.toLowerCase().includes(q)),
    );
  }

  /** Find tables containing a specific column */
  findByColumn(columnName: string): CatalogEntry[] {
    return this.listTables().filter(e =>
      e.columns.some(c => c.name === columnName),
    );
  }

  /** Get column definition across all tables */
  getColumnUsage(columnName: string): Array<{ table: string; column: ColumnDefinition }> {
    const usage: Array<{ table: string; column: ColumnDefinition }> = [];
    for (const entry of this.entries.values()) {
      const col = entry.columns.find(c => c.name === columnName);
      if (col) usage.push({ table: `${entry.database}.${entry.table}`, column: col });
    }
    return usage;
  }

  // ===========================================================================
  // LINEAGE
  // ===========================================================================

  /** Get the full upstream lineage graph for a table */
  getUpstreamLineage(database: string, table: string): string[] {
    const visited = new Set<string>();
    const queue = [`${database}.${table}`];

    while (queue.length > 0) {
      const current = queue.shift()!;
      if (visited.has(current)) continue;
      visited.add(current);

      const entry = this.entries.get(current);
      if (entry?.lineage.upstream) {
        for (const upstream of entry.lineage.upstream) {
          if (!visited.has(upstream)) queue.push(upstream);
        }
      }
    }

    visited.delete(`${database}.${table}`); // Exclude self
    return Array.from(visited);
  }

  /** Get the full downstream lineage graph for a table */
  getDownstreamLineage(database: string, table: string): string[] {
    const visited = new Set<string>();
    const queue = [`${database}.${table}`];

    while (queue.length > 0) {
      const current = queue.shift()!;
      if (visited.has(current)) continue;
      visited.add(current);

      const entry = this.entries.get(current);
      if (entry?.lineage.downstream) {
        for (const downstream of entry.lineage.downstream) {
          if (!visited.has(downstream)) queue.push(downstream);
        }
      }
    }

    visited.delete(`${database}.${table}`);
    return Array.from(visited);
  }

  /** Get the complete lineage graph as an adjacency list */
  getLineageGraph(): Record<string, { upstream: string[]; downstream: string[] }> {
    const graph: Record<string, { upstream: string[]; downstream: string[] }> = {};
    for (const [key, entry] of this.entries) {
      graph[key] = {
        upstream: entry.lineage.upstream,
        downstream: entry.lineage.downstream,
      };
    }
    return graph;
  }

  // ===========================================================================
  // STATISTICS
  // ===========================================================================

  /** Update row count and size for a table */
  updateStats(database: string, table: string, rowCount: number, sizeBytes: number): void {
    const entry = this.entries.get(`${database}.${table}`);
    if (entry) {
      entry.rowCount = rowCount;
      entry.sizeBytes = sizeBytes;
      entry.updatedAt = new Date().toISOString();
    }
  }

  /** Get summary statistics */
  getSummary(): {
    totalTables: number;
    byTier: Record<string, number>;
    totalColumns: number;
    totalSizeBytes: number;
    totalRows: number;
  } {
    const tables = this.listTables();
    const byTier: Record<string, number> = {};
    let totalColumns = 0;
    let totalSizeBytes = 0;
    let totalRows = 0;

    for (const t of tables) {
      byTier[t.tier] = (byTier[t.tier] ?? 0) + 1;
      totalColumns += t.columns.length;
      totalSizeBytes += t.sizeBytes;
      totalRows += t.rowCount;
    }

    return { totalTables: tables.length, byTier, totalColumns, totalSizeBytes, totalRows };
  }

  // ===========================================================================
  // SCHEMA VALIDATION
  // ===========================================================================

  /** Validate that a record matches the expected schema */
  validateRecord(
    database: string,
    table: string,
    record: Record<string, unknown>,
  ): { valid: boolean; errors: string[] } {
    const entry = this.entries.get(`${database}.${table}`);
    if (!entry) return { valid: false, errors: [`Table ${database}.${table} not found in catalog`] };

    const errors: string[] = [];

    for (const col of entry.columns) {
      const value = record[col.name];

      // Check required fields
      if (!col.nullable && value === undefined && !col.defaultExpr) {
        errors.push(`Missing required column: ${col.name}`);
      }

      // Basic type validation
      if (value !== undefined && value !== null) {
        const type = col.type.replace(/^Nullable\(|\)$/g, '').replace(/^LowCardinality\(|\)$/g, '');
        if (type.startsWith('UInt') || type.startsWith('Int') || type.startsWith('Float')) {
          if (typeof value !== 'number') {
            errors.push(`Column ${col.name}: expected number, got ${typeof value}`);
          }
        } else if (type === 'String') {
          if (typeof value !== 'string') {
            errors.push(`Column ${col.name}: expected string, got ${typeof value}`);
          }
        } else if (type === 'Bool') {
          if (typeof value !== 'boolean') {
            errors.push(`Column ${col.name}: expected boolean, got ${typeof value}`);
          }
        }
      }
    }

    return { valid: errors.length === 0, errors };
  }

  // ===========================================================================
  // BOOTSTRAP
  // ===========================================================================

  /** Initialize catalog from table definitions */
  private bootstrapFromDefinitions(): void {
    const db = process.env.CLICKHOUSE_DB ?? 'aether';

    // Define lineage relationships
    const lineageMap: Record<string, LineageInfo> = {
      bronze_events: {
        upstream: [],
        downstream: [`${db}.silver_events`],
        etlJobName: 'ingestion_pipeline',
        schedule: 'continuous',
      },
      silver_events: {
        upstream: [`${db}.bronze_events`],
        downstream: [`${db}.silver_sessions`, `${db}.gold_daily_metrics`, `${db}.gold_funnel_metrics`],
        etlJobName: 'bronze_to_silver',
        schedule: '*/5 * * * *',
      },
      silver_sessions: {
        upstream: [`${db}.silver_events`],
        downstream: [`${db}.gold_daily_metrics`, `${db}.gold_user_features`, `${db}.gold_attribution`],
        etlJobName: 'bronze_to_silver',
        schedule: '*/5 * * * *',
      },
      gold_daily_metrics: {
        upstream: [`${db}.silver_events`, `${db}.silver_sessions`],
        downstream: [],
        etlJobName: 'silver_to_gold_daily_metrics',
        schedule: '0 1 * * *',
      },
      gold_funnel_metrics: {
        upstream: [`${db}.silver_events`],
        downstream: [],
        etlJobName: 'silver_to_gold_funnels',
        schedule: '0 2 * * *',
      },
      gold_attribution: {
        upstream: [`${db}.silver_sessions`],
        downstream: [],
        etlJobName: 'silver_to_gold_attribution',
        schedule: '0 3 * * *',
      },
      gold_user_features: {
        upstream: [`${db}.silver_sessions`],
        downstream: [],
        etlJobName: 'silver_to_gold_user_features',
        schedule: '0 4 * * *',
      },
    };

    const tierTags: Record<string, string[]> = {
      bronze: ['raw', 'append-only', 'source-of-truth'],
      silver: ['cleaned', 'deduplicated', 'queryable'],
      gold: ['aggregated', 'dashboard', 'ml-features'],
    };

    for (const table of ALL_TABLES) {
      this.register({
        database: db,
        table: table.name,
        tier: table.tier,
        description: table.description,
        owner: 'data-platform',
        schemaVersion: 1,
        columns: table.columns,
        partitionKeys: table.columns.filter(c => c.isPartitionKey).map(c => c.name),
        sortKeys: table.columns.filter(c => c.isSortKey).sort((a, b) => (a.sortKeyOrder ?? 99) - (b.sortKeyOrder ?? 99)).map(c => c.name),
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        rowCount: 0,
        sizeBytes: 0,
        tags: tierTags[table.tier] ?? [],
        lineage: lineageMap[table.name] ?? { upstream: [], downstream: [] },
      });
    }

    logger.info('Catalog bootstrapped', { tables: this.entries.size });
  }
}
