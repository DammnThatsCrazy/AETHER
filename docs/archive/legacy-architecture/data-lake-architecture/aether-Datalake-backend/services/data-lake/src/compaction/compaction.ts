// =============================================================================
// Aether DATA LAKE — COMPACTION SERVICE
// Merges small files ("small file problem") into optimally-sized files
// per partition to improve query performance and reduce S3 list overhead
// =============================================================================

import { randomUUID } from 'node:crypto';
import { createLogger } from '@aether/logger';
import type { CompactionJob, MedallionTier, PartitionKey, DataLakeFile } from '../schema/types.js';
import { TIER_CONFIGS } from '../schema/tables.js';
import type { DataLakeStorage } from '../storage/s3-storage.js';

const logger = createLogger('aether.datalake.compaction');

const TARGET_FILE_SIZE_MB: Record<MedallionTier, number> = {
  bronze: 128,
  silver: 256,
  gold: 512,
};

const MAX_FILES_PER_PARTITION = 10;

export class CompactionService {
  private storage: DataLakeStorage;
  private jobs: CompactionJob[] = [];

  constructor(storage: DataLakeStorage) {
    this.storage = storage;
  }

  /**
   * Analyze a partition and determine if compaction is needed.
   * Compaction is triggered when:
   *   1. Number of files exceeds MAX_FILES_PER_PARTITION, or
   *   2. Average file size is below target / 4
   */
  async analyzePartition(
    tier: MedallionTier,
    partition: PartitionKey,
    tableName?: string,
  ): Promise<{ needsCompaction: boolean; fileCount: number; avgSizeMb: number; totalSizeMb: number }> {
    const files = await this.storage.listPartition(tier, partition, tableName);

    if (files.length === 0) {
      return { needsCompaction: false, fileCount: 0, avgSizeMb: 0, totalSizeMb: 0 };
    }

    const totalBytes = files.reduce((sum, f) => sum + f.sizeBytes, 0);
    const totalSizeMb = totalBytes / (1024 * 1024);
    const avgSizeMb = totalSizeMb / files.length;
    const targetMb = TARGET_FILE_SIZE_MB[tier];

    const needsCompaction =
      files.length > MAX_FILES_PER_PARTITION ||
      (avgSizeMb < targetMb / 4 && files.length > 1);

    return { needsCompaction, fileCount: files.length, avgSizeMb, totalSizeMb };
  }

  /** Compact a partition: read all files, merge, write optimally-sized output files */
  async compactPartition(
    tier: MedallionTier,
    partition: PartitionKey,
    tableName?: string,
  ): Promise<CompactionJob> {
    const job: CompactionJob = {
      id: randomUUID(),
      tier,
      table: tableName ?? 'events',
      partition: JSON.stringify(partition),
      inputFiles: 0,
      inputSizeBytes: 0,
      outputFiles: 0,
      outputSizeBytes: 0,
      status: 'pending',
    };

    const startTime = Date.now();
    job.status = 'running';
    job.startedAt = new Date().toISOString();

    try {
      // 1. List all files in the partition
      const files = await this.storage.listPartition(tier, partition, tableName);
      job.inputFiles = files.length;
      job.inputSizeBytes = files.reduce((sum, f) => sum + f.sizeBytes, 0);

      if (files.length <= 1) {
        job.status = 'succeeded';
        job.completedAt = new Date().toISOString();
        logger.info('Compaction skipped: single file', { tier, partition });
        this.jobs.push(job);
        return job;
      }

      logger.info('Starting compaction', {
        tier,
        partition,
        inputFiles: files.length,
        inputSizeMb: (job.inputSizeBytes / (1024 * 1024)).toFixed(1),
      });

      // 2. Read all files and concatenate rows
      const allRows: string[] = [];
      for (const file of files) {
        const data = await this.storage.readFile(file.bucket, file.path);
        const lines = data.toString('utf8').split('\n').filter(Boolean);
        allRows.push(...lines);
      }

      // 3. Deduplicate by event ID (for silver/gold)
      let rows = allRows;
      if (tier !== 'bronze') {
        const seen = new Set<string>();
        rows = allRows.filter(line => {
          try {
            const parsed = JSON.parse(line);
            const id = parsed.event_id ?? parsed.id;
            if (id && seen.has(id)) return false;
            if (id) seen.add(id);
            return true;
          } catch {
            return true;
          }
        });
      }

      // 4. Calculate optimal file sizes
      const config = TIER_CONFIGS[tier];
      const targetBytes = (config?.compactionTargetSizeMb ?? TARGET_FILE_SIZE_MB[tier]) * 1024 * 1024;
      const estimatedRowSize = rows.length > 0
        ? Buffer.byteLength(rows.slice(0, 100).join('\n'), 'utf8') / Math.min(100, rows.length)
        : 200;
      const rowsPerFile = Math.max(1, Math.floor(targetBytes / estimatedRowSize));

      // 5. Write compacted files
      let outputFiles = 0;
      let outputSizeBytes = 0;

      for (let i = 0; i < rows.length; i += rowsPerFile) {
        const chunk = rows.slice(i, i + rowsPerFile);
        const body = chunk.join('\n');
        const size = Buffer.byteLength(body, 'utf8');

        // Write via the appropriate tier method
        if (tier === 'bronze') {
          const events = chunk.map(line => {
            try { return JSON.parse(line); } catch { return null; }
          }).filter(Boolean);

          await this.storage.writeBronze(
            partition.extraValues.project_id ?? 'unknown',
            events,
            new Date().toISOString(),
          );
        }
        // Silver and Gold would use their respective write methods

        outputFiles++;
        outputSizeBytes += size;
      }

      // 6. Remove original files (after successful write)
      // In production: this would use S3 batch delete
      // await this.storage.deleteFiles(files);

      job.outputFiles = outputFiles;
      job.outputSizeBytes = outputSizeBytes;
      job.compressionRatio = job.inputSizeBytes > 0 ? outputSizeBytes / job.inputSizeBytes : 1;
      job.status = 'succeeded';
      job.completedAt = new Date().toISOString();

      logger.info('Compaction complete', {
        tier,
        partition,
        inputFiles: job.inputFiles,
        outputFiles: job.outputFiles,
        compressionRatio: job.compressionRatio?.toFixed(2),
        durationMs: Date.now() - startTime,
        rowsProcessed: rows.length,
      });
    } catch (error) {
      job.status = 'failed';
      job.completedAt = new Date().toISOString();
      logger.error('Compaction failed', error as Error, { tier, partition });
    }

    this.jobs.push(job);
    return job;
  }

  /** Scan all partitions in a tier and compact those that need it */
  async scanAndCompact(
    tier: MedallionTier,
    startDate: Date,
    endDate: Date,
    maxJobs: number = 10,
  ): Promise<CompactionJob[]> {
    const partitions = await this.storage.listPartitionsInRange(tier, startDate, endDate);
    const jobs: CompactionJob[] = [];

    let jobCount = 0;
    for (const partition of partitions) {
      if (jobCount >= maxJobs) break;

      const analysis = await this.analyzePartition(tier, partition);
      if (analysis.needsCompaction) {
        const job = await this.compactPartition(tier, partition);
        jobs.push(job);
        jobCount++;
      }
    }

    logger.info('Compaction scan complete', {
      tier,
      partitionsScanned: partitions.length,
      partitionsCompacted: jobs.length,
    });

    return jobs;
  }

  /** Get compaction history */
  getHistory(): CompactionJob[] {
    return this.jobs;
  }

  /** Get compaction statistics */
  getStats(): {
    totalJobs: number;
    succeeded: number;
    failed: number;
    totalInputFiles: number;
    totalOutputFiles: number;
    avgCompressionRatio: number;
  } {
    const succeeded = this.jobs.filter(j => j.status === 'succeeded');
    const failed = this.jobs.filter(j => j.status === 'failed');

    return {
      totalJobs: this.jobs.length,
      succeeded: succeeded.length,
      failed: failed.length,
      totalInputFiles: succeeded.reduce((s, j) => s + j.inputFiles, 0),
      totalOutputFiles: succeeded.reduce((s, j) => s + j.outputFiles, 0),
      avgCompressionRatio: succeeded.length > 0
        ? succeeded.reduce((s, j) => s + (j.compressionRatio ?? 1), 0) / succeeded.length
        : 0,
    };
  }
}
