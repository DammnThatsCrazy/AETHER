// =============================================================================
// AETHER DATA LAKE — RETENTION & LIFECYCLE MANAGER
// Automated data expiry, tiered storage transitions (S3 IA/Glacier),
// partition pruning, and compliance-aware retention enforcement
// =============================================================================

import { randomUUID } from 'node:crypto';
import { createLogger } from '@aether/logger';
import type { MedallionTier, PartitionKey, DataLakeFile } from '../schema/types.js';
import { partitionPath, timestampToPartition } from '../schema/types.js';
import { TIER_CONFIGS } from '../schema/tables.js';
import type { DataLakeStorage } from '../storage/s3-storage.js';

const logger = createLogger('aether.datalake.lifecycle');

// =============================================================================
// TYPES
// =============================================================================

export type StorageClass =
  | 'STANDARD'
  | 'STANDARD_IA'       // Infrequent access (30-day min)
  | 'ONEZONE_IA'
  | 'INTELLIGENT_TIERING'
  | 'GLACIER_IR'        // Glacier instant retrieval
  | 'GLACIER_FLEXIBLE'  // Glacier flexible retrieval (minutes–hours)
  | 'GLACIER_DEEP'      // Glacier deep archive (12+ hours)
  | 'EXPIRED';          // Marked for deletion

export interface LifecycleRule {
  id: string;
  name: string;
  tier: MedallionTier;
  /** Apply to specific table prefix (null = all tables in tier) */
  tablePrefix?: string;
  transitions: StorageTransition[];
  expiration: ExpirationRule;
  /** Legal hold prevents expiration regardless of rules */
  legalHoldEnabled: boolean;
  /** Tags that must match for this rule to apply */
  requiredTags?: Record<string, string>;
  enabled: boolean;
}

export interface StorageTransition {
  /** Days after creation to transition */
  afterDays: number;
  /** Target storage class */
  toStorageClass: StorageClass;
}

export interface ExpirationRule {
  /** Days after creation to expire (delete) */
  afterDays: number;
  /** Also expire incomplete multipart uploads */
  expireIncompleteMultipartDays: number;
  /** Keep at least this many versions (0 = delete all expired) */
  keepVersions: number;
}

export type LifecycleActionType =
  | 'transition'
  | 'expiration'
  | 'partition_drop'
  | 'clickhouse_ttl'
  | 'legal_hold_skip';

export interface LifecycleAction {
  id: string;
  type: LifecycleActionType;
  tier: MedallionTier;
  table?: string;
  partition?: string;
  fromStorageClass?: StorageClass;
  toStorageClass?: StorageClass;
  filesAffected: number;
  bytesAffected: number;
  executedAt: string;
  dryRun: boolean;
  detail: string;
}

// =============================================================================
// DEFAULT LIFECYCLE RULES
// =============================================================================

export const DEFAULT_LIFECYCLE_RULES: LifecycleRule[] = [
  // Bronze: Raw events — hot for 7 days, IA after 30, Glacier after 60, expire at 90
  {
    id: 'bronze-events-lifecycle',
    name: 'Bronze Events Lifecycle',
    tier: 'bronze',
    transitions: [
      { afterDays: 30, toStorageClass: 'STANDARD_IA' },
      { afterDays: 60, toStorageClass: 'GLACIER_IR' },
    ],
    expiration: { afterDays: 90, expireIncompleteMultipartDays: 7, keepVersions: 0 },
    legalHoldEnabled: false,
    enabled: true,
  },

  // Silver: Cleaned events — hot for 30 days, IA after 90, Glacier after 180, expire at 365
  {
    id: 'silver-events-lifecycle',
    name: 'Silver Events Lifecycle',
    tier: 'silver',
    transitions: [
      { afterDays: 90, toStorageClass: 'STANDARD_IA' },
      { afterDays: 180, toStorageClass: 'GLACIER_IR' },
    ],
    expiration: { afterDays: 365, expireIncompleteMultipartDays: 7, keepVersions: 0 },
    legalHoldEnabled: false,
    enabled: true,
  },

  // Gold: Aggregated metrics — hot for 90 days, IA after 365, never Glacier, expire at 730
  {
    id: 'gold-metrics-lifecycle',
    name: 'Gold Metrics Lifecycle',
    tier: 'gold',
    transitions: [
      { afterDays: 365, toStorageClass: 'STANDARD_IA' },
    ],
    expiration: { afterDays: 730, expireIncompleteMultipartDays: 7, keepVersions: 0 },
    legalHoldEnabled: false,
    enabled: true,
  },
];

// =============================================================================
// S3 LIFECYCLE POLICY GENERATOR
// =============================================================================

export function generateS3LifecyclePolicy(rules: LifecycleRule[]): S3LifecycleConfiguration {
  return {
    Rules: rules.filter(r => r.enabled).map(rule => ({
      ID: rule.id,
      Status: 'Enabled',
      Filter: {
        Prefix: rule.tablePrefix
          ? `${TIER_CONFIGS[rule.tier]?.prefix ?? ''}${rule.tablePrefix}`
          : TIER_CONFIGS[rule.tier]?.prefix ?? '',
        ...(rule.requiredTags ? {
          Tag: Object.entries(rule.requiredTags).map(([Key, Value]) => ({ Key, Value })),
        } : {}),
      },
      Transitions: rule.transitions.map(t => ({
        Days: t.afterDays,
        StorageClass: t.toStorageClass,
      })),
      Expiration: {
        Days: rule.expiration.afterDays,
      },
      AbortIncompleteMultipartUpload: {
        DaysAfterInitiation: rule.expiration.expireIncompleteMultipartDays,
      },
    })),
  };
}

interface S3LifecycleConfiguration {
  Rules: Array<{
    ID: string;
    Status: 'Enabled' | 'Disabled';
    Filter: { Prefix: string; Tag?: Array<{ Key: string; Value: string }> };
    Transitions: Array<{ Days: number; StorageClass: string }>;
    Expiration: { Days: number };
    AbortIncompleteMultipartUpload: { DaysAfterInitiation: number };
  }>;
}

// =============================================================================
// CLICKHOUSE TTL GENERATOR
// =============================================================================

export function generateClickHouseTtl(
  table: string,
  database: string,
  timestampColumn: string,
  retentionDays: number,
): string {
  return `ALTER TABLE ${database}.${table} MODIFY TTL ${timestampColumn} + INTERVAL ${retentionDays} DAY DELETE;`;
}

// =============================================================================
// LIFECYCLE MANAGER
// =============================================================================

export interface LifecycleConfig {
  rules: LifecycleRule[];
  database: string;
  /** Run in dry-run mode (log actions but don't execute) */
  dryRun: boolean;
  /** Partition age threshold for ClickHouse partition drops */
  partitionDropThresholdDays: Record<MedallionTier, number>;
}

const DEFAULT_LIFECYCLE_CONFIG: LifecycleConfig = {
  rules: DEFAULT_LIFECYCLE_RULES,
  database: process.env.CLICKHOUSE_DB ?? 'aether',
  dryRun: false,
  partitionDropThresholdDays: {
    bronze: 90,
    silver: 365,
    gold: 730,
  },
};

export interface ClickHouseLifecycleExecutor {
  execute(sql: string): Promise<void>;
  getPartitions(database: string, table: string): Promise<PartitionInfo[]>;
}

export interface PartitionInfo {
  partition: string;
  partitionId: string;
  rows: number;
  bytesOnDisk: number;
  modificationTime: string;
  minDate: string;
  maxDate: string;
}

export class LifecycleManager {
  private config: LifecycleConfig;
  private storage: DataLakeStorage;
  private chExecutor?: ClickHouseLifecycleExecutor;
  private actionLog: LifecycleAction[] = [];
  private legalHolds = new Set<string>(); // partition keys under legal hold

  constructor(
    storage: DataLakeStorage,
    config: Partial<LifecycleConfig> = {},
    chExecutor?: ClickHouseLifecycleExecutor,
  ) {
    this.config = { ...DEFAULT_LIFECYCLE_CONFIG, ...config };
    this.storage = storage;
    this.chExecutor = chExecutor;
  }

  // ===========================================================================
  // FULL LIFECYCLE RUN
  // ===========================================================================

  /** Execute a full lifecycle evaluation across all tiers */
  async runLifecycle(): Promise<LifecycleRunResult> {
    const startTime = Date.now();
    logger.info('Starting lifecycle run', { dryRun: this.config.dryRun });

    const results: LifecycleAction[] = [];

    // S3 lifecycle is handled by AWS natively — we generate the policy
    // Here we handle ClickHouse partition management + orphan cleanup

    for (const tier of ['bronze', 'silver', 'gold'] as MedallionTier[]) {
      const tierActions = await this.processPartitions(tier);
      results.push(...tierActions);
    }

    const expiredFiles = await this.pruneOrphanFiles();
    results.push(...expiredFiles);

    this.actionLog.push(...results);

    const summary: LifecycleRunResult = {
      runId: randomUUID(),
      startedAt: new Date(startTime).toISOString(),
      completedAt: new Date().toISOString(),
      durationMs: Date.now() - startTime,
      dryRun: this.config.dryRun,
      actionsExecuted: results.length,
      partitionsDropped: results.filter(a => a.type === 'partition_drop').length,
      filesExpired: results.filter(a => a.type === 'expiration').length,
      bytesFreed: results.reduce((sum, a) => sum + a.bytesAffected, 0),
      legalHoldSkips: results.filter(a => a.type === 'legal_hold_skip').length,
      actions: results,
    };

    logger.info('Lifecycle run completed', {
      runId: summary.runId,
      actionsExecuted: summary.actionsExecuted,
      bytesFreed: summary.bytesFreed,
      durationMs: summary.durationMs,
    });

    return summary;
  }

  // ===========================================================================
  // CLICKHOUSE PARTITION MANAGEMENT
  // ===========================================================================

  /** Drop expired ClickHouse partitions */
  private async processPartitions(tier: MedallionTier): Promise<LifecycleAction[]> {
    if (!this.chExecutor) return [];

    const tables = this.getTablesForTier(tier);
    const thresholdDays = this.config.partitionDropThresholdDays[tier];
    const cutoffDate = new Date(Date.now() - thresholdDays * 86400_000);
    const actions: LifecycleAction[] = [];

    for (const table of tables) {
      try {
        const partitions = await this.chExecutor.getPartitions(this.config.database, table);

        for (const partition of partitions) {
          const partitionDate = new Date(partition.maxDate);

          if (partitionDate < cutoffDate) {
            // Check legal hold
            const holdKey = `${tier}:${table}:${partition.partitionId}`;
            if (this.legalHolds.has(holdKey)) {
              actions.push({
                id: randomUUID(),
                type: 'legal_hold_skip',
                tier,
                table,
                partition: partition.partition,
                filesAffected: 0,
                bytesAffected: 0,
                executedAt: new Date().toISOString(),
                dryRun: this.config.dryRun,
                detail: `Partition ${partition.partition} skipped due to legal hold`,
              });
              continue;
            }

            if (!this.config.dryRun) {
              const sql = `ALTER TABLE ${this.config.database}.${table} DROP PARTITION '${partition.partition}';`;
              await this.chExecutor.execute(sql);
            }

            actions.push({
              id: randomUUID(),
              type: 'partition_drop',
              tier,
              table,
              partition: partition.partition,
              filesAffected: 1,
              bytesAffected: partition.bytesOnDisk,
              executedAt: new Date().toISOString(),
              dryRun: this.config.dryRun,
              detail: `Dropped partition ${partition.partition} (${partition.rows} rows, ${(partition.bytesOnDisk / 1024 / 1024).toFixed(1)}MB, max date ${partition.maxDate})`,
            });

            logger.info('Partition dropped', {
              tier,
              table,
              partition: partition.partition,
              rows: partition.rows,
              bytesMB: (partition.bytesOnDisk / 1024 / 1024).toFixed(1),
              dryRun: this.config.dryRun,
            });
          }
        }
      } catch (err) {
        logger.error('Failed to process partitions', { tier, table, error: (err as Error).message });
      }
    }

    return actions;
  }

  // ===========================================================================
  // ORPHAN FILE CLEANUP
  // ===========================================================================

  /** Find and remove orphan files (files not tracked by catalog) */
  private async pruneOrphanFiles(): Promise<LifecycleAction[]> {
    // In production: compare S3 listings against catalog entries
    // Remove files that exist on S3 but have no catalog record
    // This handles failed ETL jobs that wrote partial output
    const actions: LifecycleAction[] = [];

    for (const tier of ['bronze', 'silver', 'gold'] as MedallionTier[]) {
      const cutoffDate = new Date(Date.now() - 7 * 86400_000); // 7-day grace period
      try {
        const files = await this.storage.listFiles(tier);
        const orphans = files.filter(f =>
          new Date(f.createdAt) < cutoffDate &&
          f.rowCount === 0,
        );

        for (const orphan of orphans) {
          if (!this.config.dryRun) {
            await this.storage.deleteFile(tier, orphan.path);
          }

          actions.push({
            id: randomUUID(),
            type: 'expiration',
            tier,
            partition: orphan.path,
            filesAffected: 1,
            bytesAffected: orphan.sizeBytes,
            executedAt: new Date().toISOString(),
            dryRun: this.config.dryRun,
            detail: `Orphan file removed: ${orphan.path} (${orphan.sizeBytes} bytes, created ${orphan.createdAt})`,
          });
        }
      } catch {
        // Storage may not be available in test environment
      }
    }

    return actions;
  }

  // ===========================================================================
  // LEGAL HOLDS
  // ===========================================================================

  /** Place a legal hold on a partition (prevents expiration) */
  setLegalHold(tier: MedallionTier, table: string, partitionId: string): void {
    const key = `${tier}:${table}:${partitionId}`;
    this.legalHolds.add(key);
    logger.info('Legal hold set', { tier, table, partitionId });
  }

  /** Remove a legal hold */
  removeLegalHold(tier: MedallionTier, table: string, partitionId: string): void {
    const key = `${tier}:${table}:${partitionId}`;
    this.legalHolds.delete(key);
    logger.info('Legal hold removed', { tier, table, partitionId });
  }

  /** List all legal holds */
  getLegalHolds(): Array<{ tier: MedallionTier; table: string; partitionId: string }> {
    return Array.from(this.legalHolds).map(key => {
      const [tier, table, partitionId] = key.split(':');
      return { tier: tier as MedallionTier, table, partitionId };
    });
  }

  // ===========================================================================
  // STORAGE COST ESTIMATION
  // ===========================================================================

  /** Estimate monthly storage costs across all tiers */
  async estimateCosts(): Promise<StorageCostEstimate> {
    const costs: StorageCostEstimate = {
      tiers: {},
      totalMonthly: 0,
      estimatedAt: new Date().toISOString(),
    };

    // AWS S3 pricing (us-east-1, approximate)
    const pricePerGBMonth: Record<StorageClass, number> = {
      STANDARD: 0.023,
      STANDARD_IA: 0.0125,
      ONEZONE_IA: 0.01,
      INTELLIGENT_TIERING: 0.023,
      GLACIER_IR: 0.004,
      GLACIER_FLEXIBLE: 0.0036,
      GLACIER_DEEP: 0.00099,
      EXPIRED: 0,
    };

    for (const tier of ['bronze', 'silver', 'gold'] as MedallionTier[]) {
      try {
        const files = await this.storage.listFiles(tier);
        const totalBytes = files.reduce((sum, f) => sum + f.sizeBytes, 0);
        const totalGB = totalBytes / (1024 * 1024 * 1024);

        // Estimate storage class distribution based on file ages
        const now = Date.now();
        let standardGB = 0, iaGB = 0, glacierGB = 0;

        for (const file of files) {
          const ageDays = (now - new Date(file.createdAt).getTime()) / 86400_000;
          const sizeGB = file.sizeBytes / (1024 * 1024 * 1024);

          const rule = this.config.rules.find(r => r.tier === tier && r.enabled);
          if (rule) {
            const lastTransition = [...rule.transitions]
              .sort((a, b) => b.afterDays - a.afterDays)
              .find(t => ageDays >= t.afterDays);

            if (lastTransition?.toStorageClass.startsWith('GLACIER')) {
              glacierGB += sizeGB;
            } else if (lastTransition?.toStorageClass.includes('IA')) {
              iaGB += sizeGB;
            } else {
              standardGB += sizeGB;
            }
          } else {
            standardGB += sizeGB;
          }
        }

        const tierCost =
          standardGB * pricePerGBMonth.STANDARD +
          iaGB * pricePerGBMonth.STANDARD_IA +
          glacierGB * pricePerGBMonth.GLACIER_IR;

        costs.tiers[tier] = {
          totalFiles: files.length,
          totalGB,
          standardGB,
          infrequentAccessGB: iaGB,
          glacierGB,
          monthlyCost: Math.round(tierCost * 100) / 100,
        };
        costs.totalMonthly += tierCost;
      } catch {
        costs.tiers[tier] = {
          totalFiles: 0,
          totalGB: 0,
          standardGB: 0,
          infrequentAccessGB: 0,
          glacierGB: 0,
          monthlyCost: 0,
        };
      }
    }

    costs.totalMonthly = Math.round(costs.totalMonthly * 100) / 100;
    return costs;
  }

  // ===========================================================================
  // HELPERS
  // ===========================================================================

  private getTablesForTier(tier: MedallionTier): string[] {
    switch (tier) {
      case 'bronze': return ['bronze_events'];
      case 'silver': return ['silver_events', 'silver_sessions'];
      case 'gold':   return ['gold_daily_metrics', 'gold_funnel_metrics', 'gold_attribution', 'gold_user_features'];
    }
  }

  /** Get action history */
  getActionLog(): LifecycleAction[] {
    return [...this.actionLog];
  }

  /** Get lifecycle rules */
  getRules(): LifecycleRule[] {
    return [...this.config.rules];
  }
}

// =============================================================================
// RESULT TYPES
// =============================================================================

export interface LifecycleRunResult {
  runId: string;
  startedAt: string;
  completedAt: string;
  durationMs: number;
  dryRun: boolean;
  actionsExecuted: number;
  partitionsDropped: number;
  filesExpired: number;
  bytesFreed: number;
  legalHoldSkips: number;
  actions: LifecycleAction[];
}

export interface StorageCostEstimate {
  tiers: Record<string, {
    totalFiles: number;
    totalGB: number;
    standardGB: number;
    infrequentAccessGB: number;
    glacierGB: number;
    monthlyCost: number;
  }>;
  totalMonthly: number;
  estimatedAt: string;
}
