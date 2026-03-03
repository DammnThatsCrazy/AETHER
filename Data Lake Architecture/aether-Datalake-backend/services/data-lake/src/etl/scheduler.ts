// =============================================================================
// AETHER DATA LAKE — ETL SCHEDULER
// Cron-based orchestration: discovers unprocessed partitions and runs
// Bronze→Silver and Silver→Gold pipelines on schedule
// =============================================================================

import { createLogger } from '@aether/logger';
import type { PartitionKey, MedallionTier } from '../schema/types.js';
import { timestampToPartition } from '../schema/types.js';
import type { DataLakeStorage } from '../storage/s3-storage.js';
import { BronzeToSilverPipeline, SilverToGoldPipeline, EtlJobTracker } from './pipelines.js';

const logger = createLogger('aether.datalake.scheduler');

export interface SchedulerConfig {
  /** How often to check for new partitions (ms) */
  pollIntervalMs: number;
  /** Maximum concurrent ETL jobs */
  maxConcurrency: number;
  /** Project IDs to process (empty = all) */
  projectIds: string[];
  /** Enable Bronze→Silver pipeline */
  bronzeToSilver: boolean;
  /** Enable Silver→Gold daily metrics */
  silverToGoldMetrics: boolean;
  /** Enable Silver→Gold user features */
  silverToGoldFeatures: boolean;
  /** Hours of lookback for unprocessed partitions */
  lookbackHours: number;
}

const DEFAULT_CONFIG: SchedulerConfig = {
  pollIntervalMs: 300_000,  // 5 minutes
  maxConcurrency: 4,
  projectIds: [],
  bronzeToSilver: true,
  silverToGoldMetrics: true,
  silverToGoldFeatures: true,
  lookbackHours: 48,
};

export class EtlScheduler {
  private config: SchedulerConfig;
  private storage: DataLakeStorage;
  private tracker: EtlJobTracker;
  private bronzePipeline: BronzeToSilverPipeline;
  private goldPipeline: SilverToGoldPipeline;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private isRunning = false;
  private activeJobs = 0;

  constructor(storage: DataLakeStorage, config?: Partial<SchedulerConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.storage = storage;
    this.tracker = new EtlJobTracker();
    this.bronzePipeline = new BronzeToSilverPipeline(storage, this.tracker);
    this.goldPipeline = new SilverToGoldPipeline(storage, this.tracker);
  }

  /** Start the scheduler */
  start(): void {
    if (this.isRunning) return;
    this.isRunning = true;

    logger.info('ETL scheduler started', {
      pollIntervalMs: this.config.pollIntervalMs,
      maxConcurrency: this.config.maxConcurrency,
      lookbackHours: this.config.lookbackHours,
    });

    // Run immediately, then on interval
    this.tick();
    this.pollTimer = setInterval(() => this.tick(), this.config.pollIntervalMs);
  }

  /** Stop the scheduler */
  stop(): void {
    this.isRunning = false;
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    logger.info('ETL scheduler stopped');
  }

  /** Get job tracker for monitoring */
  getTracker(): EtlJobTracker {
    return this.tracker;
  }

  // ===========================================================================
  // SCHEDULING LOGIC
  // ===========================================================================

  private async tick(): Promise<void> {
    if (this.activeJobs >= this.config.maxConcurrency) {
      logger.debug('Scheduler tick skipped: at max concurrency', {
        activeJobs: this.activeJobs,
        maxConcurrency: this.config.maxConcurrency,
      });
      return;
    }

    try {
      const partitions = this.generatePartitions();

      for (const partition of partitions) {
        if (this.activeJobs >= this.config.maxConcurrency) break;
        if (!this.isRunning) break;

        // For each project, run the pipeline chain
        const projects = this.config.projectIds.length > 0
          ? this.config.projectIds
          : await this.discoverProjects(partition);

        for (const projectId of projects) {
          if (this.activeJobs >= this.config.maxConcurrency) break;

          this.activeJobs++;
          this.processPartition(projectId, partition)
            .catch(err => logger.error('Partition processing failed', err))
            .finally(() => { this.activeJobs--; });
        }
      }
    } catch (error) {
      logger.error('Scheduler tick failed', error as Error);
    }
  }

  private async processPartition(projectId: string, partition: PartitionKey): Promise<void> {
    logger.info('Processing partition', { projectId, partition });

    // Step 1: Bronze → Silver
    if (this.config.bronzeToSilver) {
      await this.bronzePipeline.processPartition(projectId, partition);
    }

    // Step 2: Silver → Gold daily metrics (runs on day partitions)
    if (this.config.silverToGoldMetrics && partition.hour === undefined) {
      const metricDate = `${partition.year}-${String(partition.month).padStart(2, '0')}-${String(partition.day).padStart(2, '0')}`;
      // Would load silver sessions and events from storage
      await this.goldPipeline.computeDailyMetrics(projectId, metricDate, [], []);
    }

    // Step 3: Silver → Gold user features (runs daily)
    if (this.config.silverToGoldFeatures && partition.hour === undefined) {
      const computeDate = `${partition.year}-${String(partition.month).padStart(2, '0')}-${String(partition.day).padStart(2, '0')}`;
      await this.goldPipeline.computeUserFeatures(projectId, [], computeDate);
    }
  }

  /** Generate partition keys for the lookback window */
  private generatePartitions(): PartitionKey[] {
    const partitions: PartitionKey[] = [];
    const now = new Date();

    for (let h = 0; h < this.config.lookbackHours; h++) {
      const ts = new Date(now.getTime() - h * 3600000);
      partitions.push(timestampToPartition(ts.toISOString(), 'hour'));
    }

    return partitions;
  }

  /** Discover projects that have data in a given partition */
  private async discoverProjects(_partition: PartitionKey): Promise<string[]> {
    // In production: list S3 prefixes or query a project registry
    return this.config.projectIds;
  }
}

// =============================================================================
// ETL CLI (manual partition processing)
// =============================================================================

export interface EtlCliCommand {
  command: 'process' | 'backfill' | 'status' | 'retry-failed';
  tier?: MedallionTier;
  projectId?: string;
  startDate?: string;
  endDate?: string;
  jobId?: string;
}

export function parseEtlCommand(args: string[]): EtlCliCommand {
  const cmd = args[0] as EtlCliCommand['command'];

  switch (cmd) {
    case 'process':
      return {
        command: 'process',
        tier: args[1] as MedallionTier,
        projectId: args[2],
        startDate: args[3],
      };

    case 'backfill':
      return {
        command: 'backfill',
        projectId: args[1],
        startDate: args[2],
        endDate: args[3],
      };

    case 'status':
      return { command: 'status', jobId: args[1] };

    case 'retry-failed':
      return { command: 'retry-failed' };

    default:
      throw new Error(`Unknown command: ${cmd}. Use: process, backfill, status, retry-failed`);
  }
}
