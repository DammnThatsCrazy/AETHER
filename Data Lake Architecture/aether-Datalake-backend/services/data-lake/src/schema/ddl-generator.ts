// =============================================================================
// Aether DATA LAKE — CLICKHOUSE DDL GENERATOR
// Generates CREATE TABLE, ALTER TABLE, materialized views, and migration SQL
// from the declarative TableDefinition schema
// =============================================================================

import type { TableDefinition, ColumnDefinition } from './types.js';
import { ALL_TABLES } from './tables.js';

const DATABASE = process.env.CLICKHOUSE_DB ?? 'aether';

// =============================================================================
// DDL GENERATION
// =============================================================================

/** Generate CREATE TABLE statement */
export function generateCreateTable(table: TableDefinition): string {
  const columns = table.columns.map(col => {
    const colType = col.nullable && !col.type.startsWith('Nullable')
      ? `Nullable(${col.type})`
      : col.type;

    const defaultClause = col.defaultExpr ? ` DEFAULT ${col.defaultExpr}` : '';
    const comment = col.description ? ` COMMENT '${escapeString(col.description)}'` : '';

    return `    ${col.name} ${colType}${defaultClause}${comment}`;
  });

  const orderBy = table.orderBy.length > 0
    ? `ORDER BY (${table.orderBy.join(', ')})`
    : 'ORDER BY tuple()';

  const ttl = table.ttlDays
    ? `\nTTL ${table.columns.find(c => c.isSortKey && c.sortKeyOrder === 2)?.name ?? 'received_at'} + INTERVAL ${table.ttlDays} DAY`
    : '';

  const settings = table.settings
    ? `\nSETTINGS ${Object.entries(table.settings).map(([k, v]) => `${k} = ${v}`).join(', ')}`
    : '';

  return `CREATE TABLE IF NOT EXISTS ${DATABASE}.${table.name}
(
${columns.join(',\n')}
)
ENGINE = ${table.engine}
PARTITION BY ${table.partitionBy}
${orderBy}${ttl}${settings};`;
}

/** Generate CREATE DATABASE */
export function generateCreateDatabase(): string {
  return `CREATE DATABASE IF NOT EXISTS ${DATABASE};`;
}

/** Generate all DDL for the full data lake */
export function generateFullDDL(): string {
  const sections: string[] = [
    '-- =============================================================================',
    '-- Aether DATA LAKE — COMPLETE CLICKHOUSE SCHEMA',
    `-- Generated: ${new Date().toISOString()}`,
    '-- =============================================================================',
    '',
    generateCreateDatabase(),
    '',
  ];

  for (const table of ALL_TABLES) {
    sections.push(
      `-- ${table.tier.toUpperCase()}: ${table.name}`,
      `-- ${table.description}`,
      generateCreateTable(table),
      '',
    );
  }

  // Add materialized views
  sections.push(
    '-- =============================================================================',
    '-- MATERIALIZED VIEWS',
    '-- =============================================================================',
    '',
    ...generateMaterializedViews(),
  );

  return sections.join('\n');
}

// =============================================================================
// MATERIALIZED VIEWS
// =============================================================================

function generateMaterializedViews(): string[] {
  const views: string[] = [];

  // MV: Real-time event counts (live dashboard)
  views.push(`-- Real-time event counters (1-minute resolution)
CREATE MATERIALIZED VIEW IF NOT EXISTS ${DATABASE}.mv_event_counts_1m
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(minute)
ORDER BY (project_id, event_type, minute)
AS SELECT
    project_id,
    event_type,
    toStartOfMinute(event_timestamp) AS minute,
    count() AS event_count,
    uniq(anonymous_id) AS unique_visitors,
    uniq(session_id) AS unique_sessions
FROM ${DATABASE}.silver_events
GROUP BY project_id, event_type, minute;
`);

  // MV: Hourly page performance
  views.push(`-- Hourly web performance aggregates
CREATE MATERIALIZED VIEW IF NOT EXISTS ${DATABASE}.mv_page_performance_hourly
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(hour)
ORDER BY (project_id, page_path, hour)
AS SELECT
    project_id,
    page_path,
    toStartOfHour(event_timestamp) AS hour,
    count() AS page_views,
    avgState(lcp_ms) AS avg_lcp,
    avgState(fid_ms) AS avg_fid,
    avgState(cls) AS avg_cls,
    avgState(ttfb_ms) AS avg_ttfb,
    quantileState(0.75)(lcp_ms) AS p75_lcp,
    quantileState(0.95)(lcp_ms) AS p95_lcp
FROM ${DATABASE}.silver_events
WHERE event_type = 'performance' AND lcp_ms IS NOT NULL
GROUP BY project_id, page_path, hour;
`);

  // MV: Session start tracking (for real-time active users)
  views.push(`-- Active session tracker
CREATE MATERIALIZED VIEW IF NOT EXISTS ${DATABASE}.mv_active_sessions
ENGINE = ReplacingMergeTree(last_activity)
PARTITION BY toYYYYMMDD(session_start)
ORDER BY (project_id, session_id)
TTL last_activity + INTERVAL 1 DAY
AS SELECT
    project_id,
    session_id,
    anonymous_id,
    user_id,
    min(event_timestamp) AS session_start,
    max(event_timestamp) AS last_activity,
    count() AS event_count,
    countIf(event_type = 'page') AS page_views,
    any(device_type) AS device_type,
    any(country_code) AS country_code,
    any(utm_source) AS utm_source,
    any(referrer_type) AS referrer_type
FROM ${DATABASE}.silver_events
GROUP BY project_id, session_id, anonymous_id, user_id;
`);

  // MV: Error aggregation
  views.push(`-- Error aggregation for monitoring
CREATE MATERIALIZED VIEW IF NOT EXISTS ${DATABASE}.mv_error_aggregates
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(hour)
ORDER BY (project_id, error_type, error_message, hour)
AS SELECT
    project_id,
    coalesce(error_type, 'unknown') AS error_type,
    coalesce(substring(error_message, 1, 200), 'unknown') AS error_message,
    toStartOfHour(event_timestamp) AS hour,
    count() AS occurrence_count,
    uniq(session_id) AS affected_sessions,
    uniq(anonymous_id) AS affected_users,
    any(page_url) AS sample_page_url,
    any(browser) AS sample_browser,
    any(os) AS sample_os
FROM ${DATABASE}.silver_events
WHERE event_type = 'error'
GROUP BY project_id, error_type, error_message, hour;
`);

  // MV: Campaign touchpoint tracking for attribution
  views.push(`-- Campaign touchpoint log for multi-touch attribution
CREATE MATERIALIZED VIEW IF NOT EXISTS ${DATABASE}.mv_campaign_touchpoints
ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_timestamp)
ORDER BY (project_id, anonymous_id, event_timestamp)
AS SELECT
    project_id,
    anonymous_id,
    user_id,
    session_id,
    event_timestamp,
    utm_source,
    utm_medium,
    utm_campaign,
    referrer_type,
    page_path AS landing_page,
    event_type,
    conversion_value
FROM ${DATABASE}.silver_events
WHERE utm_source != '' OR referrer_type NOT IN ('direct', 'unknown') OR event_type = 'conversion';
`);

  return views;
}

// =============================================================================
// MIGRATION HELPERS
// =============================================================================

/** Generate ALTER TABLE for adding a new column */
export function generateAddColumn(tableName: string, column: ColumnDefinition): string {
  const colType = column.nullable && !column.type.startsWith('Nullable')
    ? `Nullable(${column.type})`
    : column.type;

  const defaultClause = column.defaultExpr ? ` DEFAULT ${column.defaultExpr}` : '';
  const comment = column.description ? ` COMMENT '${escapeString(column.description)}'` : '';

  return `ALTER TABLE ${DATABASE}.${tableName} ADD COLUMN IF NOT EXISTS ${column.name} ${colType}${defaultClause}${comment};`;
}

/** Generate schema diff between two table definitions */
export function generateMigration(from: TableDefinition, to: TableDefinition): string[] {
  const statements: string[] = [];
  const fromCols = new Map(from.columns.map(c => [c.name, c]));
  const toCols = new Map(to.columns.map(c => [c.name, c]));

  // Added columns
  for (const [name, col] of toCols) {
    if (!fromCols.has(name)) {
      statements.push(generateAddColumn(to.name, col));
    }
  }

  // Removed columns (commented — destructive operations need manual review)
  for (const [name] of fromCols) {
    if (!toCols.has(name)) {
      statements.push(`-- REVIEW: Column removed: ALTER TABLE ${DATABASE}.${to.name} DROP COLUMN ${name};`);
    }
  }

  // Type changes (commented — need manual review for data migration)
  for (const [name, toCol] of toCols) {
    const fromCol = fromCols.get(name);
    if (fromCol && fromCol.type !== toCol.type) {
      statements.push(`-- REVIEW: Type change for ${name}: ${fromCol.type} → ${toCol.type}`);
      statements.push(`-- ALTER TABLE ${DATABASE}.${to.name} MODIFY COLUMN ${name} ${toCol.type};`);
    }
  }

  return statements;
}

/** Generate DROP TABLE (for cleanup) */
export function generateDropTable(tableName: string): string {
  return `DROP TABLE IF EXISTS ${DATABASE}.${tableName};`;
}

function escapeString(s: string): string {
  return s.replace(/'/g, "\\'");
}
