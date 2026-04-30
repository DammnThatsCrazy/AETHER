// =============================================================================
// Aether DATA LAKE — DATA QUALITY FRAMEWORK
// Automated quality checks: completeness, freshness, volume anomalies,
// schema compliance, uniqueness, and distribution monitoring
// =============================================================================

import { createLogger } from '@aether/logger';
import type { QualityCheck, QualityResult, QualitySeverity, QualityCheckType, MedallionTier } from '../schema/types.js';

const logger = createLogger('aether.datalake.quality');

// =============================================================================
// QUALITY CHECK DEFINITIONS
// =============================================================================

/** Pre-defined quality checks for all data lake tables */
export const QUALITY_CHECKS: QualityCheck[] = [
  // ---- BRONZE ----
  {
    id: 'brz-completeness-event-id',
    name: 'Bronze event_id completeness',
    type: 'completeness',
    table: 'bronze_events',
    tier: 'bronze',
    severity: 'critical',
    expression: 'countIf(event_id IS NOT NULL) / count(*)',
    threshold: 0.999,
    description: 'Every raw event must have a unique event_id from the SDK',
  },
  {
    id: 'brz-completeness-timestamp',
    name: 'Bronze timestamp completeness',
    type: 'completeness',
    table: 'bronze_events',
    tier: 'bronze',
    severity: 'critical',
    expression: 'countIf(event_timestamp IS NOT NULL) / count(*)',
    threshold: 0.999,
    description: 'Every event must have a client-side timestamp',
  },
  {
    id: 'brz-completeness-session-id',
    name: 'Bronze session_id completeness',
    type: 'completeness',
    table: 'bronze_events',
    tier: 'bronze',
    severity: 'warning',
    expression: 'countIf(session_id IS NOT NULL AND session_id != \'\') / count(*)',
    threshold: 0.99,
    description: 'Events should have a session ID for sessionization',
  },
  {
    id: 'brz-freshness',
    name: 'Bronze data freshness',
    type: 'freshness',
    table: 'bronze_events',
    tier: 'bronze',
    severity: 'warning',
    expression: 'dateDiff(minute, max(received_at), now())',
    threshold: 15,
    description: 'Bronze should receive data within 15 minutes of real-time',
  },
  {
    id: 'brz-volume-min',
    name: 'Bronze minimum hourly volume',
    type: 'volume',
    table: 'bronze_events',
    tier: 'bronze',
    severity: 'warning',
    expression: 'count(*)',
    threshold: 100,
    description: 'Each hourly partition should have at least 100 events (anomaly detection)',
  },

  // ---- SILVER ----
  {
    id: 'slv-uniqueness-event-id',
    name: 'Silver event_id uniqueness',
    type: 'uniqueness',
    table: 'silver_events',
    tier: 'silver',
    severity: 'critical',
    expression: 'uniq(event_id) / count(*)',
    threshold: 0.9999,
    description: 'Silver events must be deduplicated — near-zero duplicate rate',
  },
  {
    id: 'slv-completeness-project-id',
    name: 'Silver project_id completeness',
    type: 'completeness',
    table: 'silver_events',
    tier: 'silver',
    severity: 'critical',
    expression: 'countIf(project_id IS NOT NULL AND project_id != \'\') / count(*)',
    threshold: 1.0,
    description: 'Every silver event must have a project_id from API key resolution',
  },
  {
    id: 'slv-freshness',
    name: 'Silver processing lag',
    type: 'freshness',
    table: 'silver_events',
    tier: 'silver',
    severity: 'warning',
    expression: 'avg(ingestion_lag_ms)',
    threshold: 60000,
    description: 'Average ingestion lag should be under 60 seconds',
  },
  {
    id: 'slv-schema-event-types',
    name: 'Silver valid event types',
    type: 'schema',
    table: 'silver_events',
    tier: 'silver',
    severity: 'critical',
    expression: "countIf(event_type IN ('track','page','screen','identify','conversion','wallet','transaction','error','performance','experiment','consent','heartbeat')) / count(*)",
    threshold: 1.0,
    description: 'All events must have a valid event_type enum value',
  },
  {
    id: 'slv-distribution-bot-rate',
    name: 'Silver bot traffic ratio',
    type: 'distribution',
    table: 'silver_events',
    tier: 'silver',
    severity: 'warning',
    expression: 'countIf(is_bot = true) / count(*)',
    threshold: 0.3,
    description: 'Bot traffic should not exceed 30% — investigate if higher',
  },
  {
    id: 'slv-completeness-page-url',
    name: 'Silver page_url completeness for page events',
    type: 'completeness',
    table: 'silver_events',
    tier: 'silver',
    severity: 'info',
    expression: "countIf(page_url IS NOT NULL AND page_url != '' AND event_type = 'page') / countIf(event_type = 'page')",
    threshold: 0.99,
    description: 'Page events should have a page URL',
  },

  // ---- SILVER SESSIONS ----
  {
    id: 'slv-session-duration',
    name: 'Session duration sanity',
    type: 'distribution',
    table: 'silver_sessions',
    tier: 'silver',
    severity: 'warning',
    expression: 'countIf(duration_seconds > 0 AND duration_seconds < 86400) / count(*)',
    threshold: 0.99,
    description: 'Sessions should be between 0 and 24 hours — outliers indicate bugs',
  },
  {
    id: 'slv-session-bounce-rate',
    name: 'Session bounce rate range',
    type: 'distribution',
    table: 'silver_sessions',
    tier: 'silver',
    severity: 'info',
    expression: 'countIf(bounce = true) / count(*)',
    threshold: 0.8,
    description: 'Bounce rate above 80% may indicate SDK misconfiguration',
  },

  // ---- GOLD ----
  {
    id: 'gld-metrics-completeness',
    name: 'Gold daily metrics coverage',
    type: 'completeness',
    table: 'gold_daily_metrics',
    tier: 'gold',
    severity: 'critical',
    expression: 'countIf(unique_visitors > 0) / count(*)',
    threshold: 0.95,
    description: 'Daily metrics should report non-zero visitors for active projects',
  },
  {
    id: 'gld-revenue-sanity',
    name: 'Gold revenue non-negative',
    type: 'distribution',
    table: 'gold_daily_metrics',
    tier: 'gold',
    severity: 'critical',
    expression: 'countIf(total_revenue >= 0) / count(*)',
    threshold: 1.0,
    description: 'Revenue values must never be negative',
  },
  {
    id: 'gld-features-freshness',
    name: 'Gold user features freshness',
    type: 'freshness',
    table: 'gold_user_features',
    tier: 'gold',
    severity: 'warning',
    expression: 'dateDiff(hour, max(computed_at), now())',
    threshold: 48,
    description: 'User features should be recomputed within 48 hours',
  },
];

// =============================================================================
// QUALITY RUNNER
// =============================================================================

export class QualityRunner {
  private checks: QualityCheck[];
  private results: QualityResult[] = [];

  constructor(checks?: QualityCheck[]) {
    this.checks = checks ?? QUALITY_CHECKS;
  }

  /** Run all checks for a given tier and partition */
  async runChecks(
    tier: MedallionTier,
    partition: string,
    dataAccessor: DataAccessor,
  ): Promise<QualityResult[]> {
    const tierChecks = this.checks.filter(c => c.tier === tier);
    const results: QualityResult[] = [];

    logger.info(`Running ${tierChecks.length} quality checks for ${tier}`, { partition });

    for (const check of tierChecks) {
      try {
        const actualValue = await dataAccessor.evaluateExpression(check.table, check.expression, partition);
        const passed = this.evaluate(check, actualValue);

        const result: QualityResult = {
          checkId: check.id,
          checkName: check.name,
          passed,
          actualValue,
          threshold: check.threshold,
          severity: check.severity,
          table: check.table,
          partition,
          evaluatedAt: new Date().toISOString(),
          message: passed
            ? `PASS: ${check.name} (${actualValue.toFixed(4)} meets threshold ${check.threshold})`
            : `FAIL: ${check.name} (${actualValue.toFixed(4)} does not meet threshold ${check.threshold})`,
        };

        results.push(result);

        if (!passed) {
          const logFn = check.severity === 'critical' ? logger.error.bind(logger) : logger.warn.bind(logger);
          logFn(`Quality check failed: ${check.name}`, undefined, {
            checkId: check.id,
            actualValue,
            threshold: check.threshold,
            severity: check.severity,
          });
        }
      } catch (error) {
        results.push({
          checkId: check.id,
          checkName: check.name,
          passed: false,
          actualValue: -1,
          threshold: check.threshold,
          severity: check.severity,
          table: check.table,
          partition,
          evaluatedAt: new Date().toISOString(),
          message: `ERROR: Failed to evaluate check — ${(error as Error).message}`,
        });
      }
    }

    this.results.push(...results);

    const passed = results.filter(r => r.passed).length;
    const failed = results.filter(r => !r.passed).length;
    const critical = results.filter(r => !r.passed && r.severity === 'critical').length;

    logger.info('Quality check run complete', { tier, partition, passed, failed, critical });

    return results;
  }

  /** Get all historical results */
  getResults(): QualityResult[] {
    return this.results;
  }

  /** Get failed results only */
  getFailures(severity?: QualitySeverity): QualityResult[] {
    return this.results.filter(r =>
      !r.passed && (!severity || r.severity === severity),
    );
  }

  /** Generate a quality report */
  generateReport(): QualityReport {
    const total = this.results.length;
    const passed = this.results.filter(r => r.passed).length;
    const failed = this.results.filter(r => !r.passed);

    return {
      generatedAt: new Date().toISOString(),
      totalChecks: total,
      passed,
      failed: failed.length,
      passRate: total > 0 ? passed / total : 0,
      criticalFailures: failed.filter(r => r.severity === 'critical'),
      warningFailures: failed.filter(r => r.severity === 'warning'),
      infoFailures: failed.filter(r => r.severity === 'info'),
      byTable: this.groupByTable(),
    };
  }

  private evaluate(check: QualityCheck, actualValue: number): boolean {
    switch (check.type) {
      case 'completeness':
      case 'uniqueness':
      case 'schema':
        // Ratio checks: actual should be >= threshold
        return actualValue >= check.threshold;

      case 'freshness':
        // Lag checks: actual should be <= threshold
        return actualValue <= check.threshold;

      case 'volume':
        // Volume checks: actual should be >= threshold
        return actualValue >= check.threshold;

      case 'distribution':
        // Distribution checks: actual should be <= threshold (e.g., bot rate < 30%)
        return actualValue <= check.threshold;

      default:
        return actualValue >= check.threshold;
    }
  }

  private groupByTable(): Record<string, { passed: number; failed: number }> {
    const groups: Record<string, { passed: number; failed: number }> = {};
    for (const r of this.results) {
      if (!groups[r.table]) groups[r.table] = { passed: 0, failed: 0 };
      if (r.passed) groups[r.table].passed++;
      else groups[r.table].failed++;
    }
    return groups;
  }
}

export interface QualityReport {
  generatedAt: string;
  totalChecks: number;
  passed: number;
  failed: number;
  passRate: number;
  criticalFailures: QualityResult[];
  warningFailures: QualityResult[];
  infoFailures: QualityResult[];
  byTable: Record<string, { passed: number; failed: number }>;
}

// =============================================================================
// DATA ACCESSOR INTERFACE
// =============================================================================

export interface DataAccessor {
  /** Evaluate a SQL expression against a table/partition and return a scalar */
  evaluateExpression(table: string, expression: string, partition: string): Promise<number>;
}

/** In-memory data accessor for testing */
export class InMemoryDataAccessor implements DataAccessor {
  private data = new Map<string, Record<string, unknown>[]>();

  setData(table: string, rows: Record<string, unknown>[]): void {
    this.data.set(table, rows);
  }

  async evaluateExpression(table: string, expression: string, _partition: string): Promise<number> {
    const rows = this.data.get(table) ?? [];

    // Simple expression evaluation for testing
    if (expression.includes('count(*)')) {
      return rows.length;
    }

    if (expression.includes('countIf') && expression.includes('/ count(*)')) {
      // Simplified ratio evaluation
      return rows.length > 0 ? 1.0 : 0;
    }

    if (expression.includes('uniq(')) {
      const match = expression.match(/uniq\((\w+)\)/);
      if (match) {
        const col = match[1];
        return new Set(rows.map(r => r[col])).size;
      }
    }

    return 0;
  }
}
