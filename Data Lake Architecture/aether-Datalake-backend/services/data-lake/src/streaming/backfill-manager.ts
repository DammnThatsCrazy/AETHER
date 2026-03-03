// =============================================================================
// AETHER DATA LAKE — BACKFILL & REPLAY MANAGER
// Reprocesses historical data from Bronze through Silver and Gold tiers.
// Supports partition-level replay, schema migration backfills,
// full re-ingestion from S3, and incremental catchup
// =============================================================================

import { randomUUID } from 'node:crypto';
import { createLogger } from '@aether/logger';
import type { MedallionTier, PartitionKey, EtlJobStatus } from '../schema/types.js';
import { timestampToPartition } from '../schema/types.js';
import type { DataLakeStorage } from '../storage/s3-storage.js';

const logger = createLogger('aether.datalake.backfill');

// =============================================================================
// TYPES
// =============================================================================

export type BackfillScope = 'full' | 'date_range' | 'partition' | 'project' | 'event_type';
export type BackfillPriority = 'low' | 'normal' | 'high' | 'critical';

export interface BackfillJob {
  id: string;
  name: string;
  description: string;
  /** Which pipeline to replay: bronze→silver, silver→gold, or both */
  pipeline: 'bronze_to_silver' | 'silver_to_gold' | 'full_reprocess';
  scope: BackfillScope;
  priority: BackfillPriority;
  status: EtlJobStatus;

  /** Date range for the backfill */
  startDate: string;
  endDate: string;

  /** Filters */
  projectIds?: string[];
  eventTypes?: string[];
  partitionKeys?: string[];

  /** Progress tracking */
  totalPartitions: number;
  completedPartitions: number;
  failedPartitions: number;
  skippedPartitions: number;
  totalInputRows: number;
  totalOutputRows: number;
  totalDroppedRows: number;

  /** Timing */
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  estimatedCompletionAt?: string;

  /** Resource limits */
  maxConcurrentPartitions: number;
  /** Throttle: max partitions per minute to avoid overwhelming storage */
  rateLimit: number;
  /** Pause between partitions (ms) */
  cooldownMs: number;

  /** Error handling */
  maxRetries: number;
  failedPartitionIds: string[];
  lastError?: string;

  /** Checkpoint for resume-after-failure */
  checkpoint?: BackfillCheckpoint;
}

export interface BackfillCheckpoint {
  lastCompletedPartition: string;
  lastCompletedOffset: number;
  savedAt: string;
}

export interface PartitionTask {
  partitionKey: string;
  partition: PartitionKey;
  status: EtlJobStatus;
  inputRows: number;
  outputRows: number;
  startedAt?: string;
  completedAt?: string;
  retryCount: number;
  error?: string;
}

// =============================================================================
// BACKFILL MANAGER
// =============================================================================

export interface BackfillPipelineExecutor {
  /** Process a single partition through the ETL pipeline */
  processPartition(
    sourceTier: MedallionTier,
    targetTier: MedallionTier,
    partition: PartitionKey,
    filters?: { projectIds?: string[]; eventTypes?: string[] },
  ): Promise<{ inputRows: number; outputRows: number; droppedRows: number }>;
}

export class BackfillManager {
  private storage: DataLakeStorage;
  private executor: BackfillPipelineExecutor;
  private jobs = new Map<string, BackfillJob>();
  private activeJobs = new Set<string>();
  private maxActiveJobs: number;

  constructor(
    storage: DataLakeStorage,
    executor: BackfillPipelineExecutor,
    maxActiveJobs: number = 3,
  ) {
    this.storage = storage;
    this.executor = executor;
    this.maxActiveJobs = maxActiveJobs;
  }

  // ===========================================================================
  // JOB CREATION
  // ===========================================================================

  /** Create a new backfill job */
  createJob(params: {
    name: string;
    description: string;
    pipeline: BackfillJob['pipeline'];
    startDate: string;
    endDate: string;
    scope?: BackfillScope;
    priority?: BackfillPriority;
    projectIds?: string[];
    eventTypes?: string[];
    maxConcurrentPartitions?: number;
    rateLimit?: number;
    cooldownMs?: number;
    maxRetries?: number;
  }): BackfillJob {
    // Generate partition list for the date range
    const partitions = this.generatePartitions(params.startDate, params.endDate, params.pipeline);

    const job: BackfillJob = {
      id: randomUUID(),
      name: params.name,
      description: params.description,
      pipeline: params.pipeline,
      scope: params.scope ?? 'date_range',
      priority: params.priority ?? 'normal',
      status: 'pending',
      startDate: params.startDate,
      endDate: params.endDate,
      projectIds: params.projectIds,
      eventTypes: params.eventTypes,
      totalPartitions: partitions.length,
      completedPartitions: 0,
      failedPartitions: 0,
      skippedPartitions: 0,
      totalInputRows: 0,
      totalOutputRows: 0,
      totalDroppedRows: 0,
      createdAt: new Date().toISOString(),
      maxConcurrentPartitions: params.maxConcurrentPartitions ?? 4,
      rateLimit: params.rateLimit ?? 10,
      cooldownMs: params.cooldownMs ?? 1000,
      maxRetries: params.maxRetries ?? 3,
      failedPartitionIds: [],
    };

    this.jobs.set(job.id, job);
    logger.info('Backfill job created', {
      jobId: job.id,
      name: job.name,
      pipeline: job.pipeline,
      partitions: job.totalPartitions,
      dateRange: `${params.startDate} → ${params.endDate}`,
    });

    return job;
  }

  /** Create a quick replay for a single day */
  replayDay(date: string, pipeline: BackfillJob['pipeline'] = 'full_reprocess'): BackfillJob {
    return this.createJob({
      name: `replay-${date}`,
      description: `Replay all data for ${date}`,
      pipeline,
      startDate: `${date}T00:00:00Z`,
      endDate: `${date}T23:59:59Z`,
      priority: 'high',
    });
  }

  /** Create a backfill for schema migration (reprocess all history) */
  schemaMigrationBackfill(
    migrationName: string,
    startDate: string,
    endDate: string,
  ): BackfillJob {
    return this.createJob({
      name: `schema-migration-${migrationName}`,
      description: `Backfill for schema migration: ${migrationName}`,
      pipeline: 'full_reprocess',
      startDate,
      endDate,
      priority: 'high',
      maxConcurrentPartitions: 8, // Higher concurrency for migrations
      cooldownMs: 500,
    });
  }

  // ===========================================================================
  // JOB EXECUTION
  // ===========================================================================

  /** Start a backfill job */
  async startJob(jobId: string): Promise<void> {
    const job = this.jobs.get(jobId);
    if (!job) throw new Error(`Backfill job ${jobId} not found`);
    if (job.status === 'running') throw new Error(`Job ${jobId} already running`);
    if (this.activeJobs.size >= this.maxActiveJobs) {
      throw new Error(`Maximum concurrent backfill jobs (${this.maxActiveJobs}) reached`);
    }

    job.status = 'running';
    job.startedAt = new Date().toISOString();
    this.activeJobs.add(jobId);

    logger.info('Starting backfill job', {
      jobId,
      name: job.name,
      pipeline: job.pipeline,
      totalPartitions: job.totalPartitions,
    });

    try {
      await this.executeJob(job);
      job.status = 'succeeded';
      job.completedAt = new Date().toISOString();
      logger.info('Backfill job completed', {
        jobId,
        name: job.name,
        completed: job.completedPartitions,
        failed: job.failedPartitions,
        inputRows: job.totalInputRows,
        outputRows: job.totalOutputRows,
      });
    } catch (err) {
      job.status = 'failed';
      job.lastError = (err as Error).message;
      job.completedAt = new Date().toISOString();
      logger.error('Backfill job failed', {
        jobId,
        name: job.name,
        error: job.lastError,
        completed: job.completedPartitions,
        failed: job.failedPartitions,
      });
    } finally {
      this.activeJobs.delete(jobId);
    }
  }

  /** Execute the backfill pipeline */
  private async executeJob(job: BackfillJob): Promise<void> {
    const partitions = this.generatePartitions(job.startDate, job.endDate, job.pipeline);

    // Resume from checkpoint if available
    let startIdx = 0;
    if (job.checkpoint) {
      const checkpointIdx = partitions.findIndex(
        p => JSON.stringify(p) === job.checkpoint!.lastCompletedPartition,
      );
      if (checkpointIdx >= 0) {
        startIdx = checkpointIdx + 1;
        logger.info('Resuming from checkpoint', { startIdx, total: partitions.length });
      }
    }

    // Process partitions with concurrency control
    const remaining = partitions.slice(startIdx);
    const chunks = this.chunkArray(remaining, job.maxConcurrentPartitions);
    let partitionsDone = startIdx;

    for (const chunk of chunks) {
      if (job.status === 'cancelled') break;

      const tasks = chunk.map(async (partition) => {
        return this.processPartitionWithRetry(job, partition);
      });

      const results = await Promise.allSettled(tasks);

      for (const result of results) {
        partitionsDone++;
        if (result.status === 'fulfilled' && result.value.success) {
          job.completedPartitions++;
          job.totalInputRows += result.value.inputRows;
          job.totalOutputRows += result.value.outputRows;
          job.totalDroppedRows += result.value.droppedRows;
        } else {
          job.failedPartitions++;
          const error = result.status === 'rejected'
            ? (result.reason as Error).message
            : result.value.error ?? 'unknown';
          job.failedPartitionIds.push(error);
        }
      }

      // Save checkpoint
      const lastPartition = chunk[chunk.length - 1];
      job.checkpoint = {
        lastCompletedPartition: JSON.stringify(lastPartition),
        lastCompletedOffset: partitionsDone,
        savedAt: new Date().toISOString(),
      };

      // Update ETA
      if (partitionsDone > startIdx) {
        const elapsed = Date.now() - new Date(job.startedAt!).getTime();
        const rate = (partitionsDone - startIdx) / elapsed;
        const remaining = job.totalPartitions - partitionsDone;
        const etaMs = remaining / rate;
        job.estimatedCompletionAt = new Date(Date.now() + etaMs).toISOString();
      }

      // Rate limiting cooldown
      if (job.cooldownMs > 0) {
        await sleep(job.cooldownMs);
      }

      // Log progress
      const pct = ((partitionsDone / job.totalPartitions) * 100).toFixed(1);
      logger.info('Backfill progress', {
        jobId: job.id,
        progress: `${partitionsDone}/${job.totalPartitions} (${pct}%)`,
        inputRows: job.totalInputRows,
        outputRows: job.totalOutputRows,
        eta: job.estimatedCompletionAt,
      });
    }
  }

  /** Process a single partition with retry logic */
  private async processPartitionWithRetry(
    job: BackfillJob,
    partition: PartitionKey,
  ): Promise<{ success: boolean; inputRows: number; outputRows: number; droppedRows: number; error?: string }> {
    const pipelines = this.getPipelinesForJob(job);

    let lastError: string | undefined;
    for (let retry = 0; retry <= job.maxRetries; retry++) {
      try {
        let totalInput = 0, totalOutput = 0, totalDropped = 0;

        for (const { source, target } of pipelines) {
          const result = await this.executor.processPartition(
            source, target, partition,
            { projectIds: job.projectIds, eventTypes: job.eventTypes },
          );
          totalInput += result.inputRows;
          totalOutput += result.outputRows;
          totalDropped += result.droppedRows;
        }

        return { success: true, inputRows: totalInput, outputRows: totalOutput, droppedRows: totalDropped };
      } catch (err) {
        lastError = (err as Error).message;
        if (retry < job.maxRetries) {
          await sleep(Math.min(1000 * Math.pow(2, retry), 30000));
        }
      }
    }

    return { success: false, inputRows: 0, outputRows: 0, droppedRows: 0, error: lastError };
  }

  // ===========================================================================
  // JOB MANAGEMENT
  // ===========================================================================

  /** Cancel a running job */
  cancelJob(jobId: string): void {
    const job = this.jobs.get(jobId);
    if (job && job.status === 'running') {
      job.status = 'cancelled';
      logger.info('Backfill job cancelled', { jobId });
    }
  }

  /** Resume a failed job from its checkpoint */
  async resumeJob(jobId: string): Promise<void> {
    const job = this.jobs.get(jobId);
    if (!job) throw new Error(`Job ${jobId} not found`);
    if (job.status !== 'failed' && job.status !== 'cancelled') {
      throw new Error(`Job ${jobId} cannot be resumed (status: ${job.status})`);
    }
    if (!job.checkpoint) {
      throw new Error(`Job ${jobId} has no checkpoint to resume from`);
    }

    logger.info('Resuming backfill job', { jobId, checkpoint: job.checkpoint.savedAt });
    await this.startJob(jobId);
  }

  /** Get job status */
  getJob(jobId: string): BackfillJob | undefined {
    return this.jobs.get(jobId);
  }

  /** List all jobs */
  listJobs(status?: EtlJobStatus): BackfillJob[] {
    const all = Array.from(this.jobs.values());
    return status ? all.filter(j => j.status === status) : all;
  }

  /** Get queue position for pending jobs */
  getQueue(): BackfillJob[] {
    return Array.from(this.jobs.values())
      .filter(j => j.status === 'pending')
      .sort((a, b) => {
        const priorityOrder: Record<BackfillPriority, number> = {
          critical: 0, high: 1, normal: 2, low: 3,
        };
        return priorityOrder[a.priority] - priorityOrder[b.priority];
      });
  }

  // ===========================================================================
  // HELPERS
  // ===========================================================================

  /** Generate partition keys for a date range */
  private generatePartitions(startDate: string, endDate: string, pipeline: BackfillJob['pipeline']): PartitionKey[] {
    const partitions: PartitionKey[] = [];
    const granularity = pipeline.includes('bronze') ? 'hour' : 'day';
    const incrementMs = granularity === 'hour' ? 3600_000 : 86400_000;

    let cursor = new Date(startDate).getTime();
    const end = new Date(endDate).getTime();

    while (cursor <= end) {
      partitions.push(timestampToPartition(new Date(cursor).toISOString(), granularity));
      cursor += incrementMs;
    }

    return partitions;
  }

  /** Get pipeline stages for a job type */
  private getPipelinesForJob(job: BackfillJob): Array<{ source: MedallionTier; target: MedallionTier }> {
    switch (job.pipeline) {
      case 'bronze_to_silver':
        return [{ source: 'bronze', target: 'silver' }];
      case 'silver_to_gold':
        return [{ source: 'silver', target: 'gold' }];
      case 'full_reprocess':
        return [
          { source: 'bronze', target: 'silver' },
          { source: 'silver', target: 'gold' },
        ];
    }
  }

  private chunkArray<T>(arr: T[], size: number): T[][] {
    const chunks: T[][] = [];
    for (let i = 0; i < arr.length; i += size) {
      chunks.push(arr.slice(i, i + size));
    }
    return chunks;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
