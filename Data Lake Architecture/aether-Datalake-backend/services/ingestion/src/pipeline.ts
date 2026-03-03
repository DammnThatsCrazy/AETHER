// =============================================================================
// AETHER INGESTION — PROCESSING PIPELINE
// Orchestrates: Parse → Validate → Deduplicate → Enrich → Route to Sinks
// =============================================================================

import type { BaseEvent, EnrichedEvent, ProcessingConfig } from '@aether/common';
import { createLogger } from '@aether/logger';
import { startTimer } from '@aether/common';
import type { EventRouter } from '@aether/events';
import type { DeduplicationFilter } from '@aether/cache';
import { EventValidator } from './validators/event-validator.js';
import { EventEnricher, DeadLetterQueue } from './enrichers/event-enricher.js';
import { metrics } from './metrics.js';

const logger = createLogger('aether.ingestion.pipeline');

export interface PipelineResult {
  accepted: number;
  rejected: number;
  deduplicated: number;
  filtered: number;
  processingMs: number;
}

export class IngestionPipeline {
  private validator: EventValidator;
  private enricher: EventEnricher;
  private dlq: DeadLetterQueue;

  constructor(
    private config: ProcessingConfig,
    private router: EventRouter,
    private dedup: DeduplicationFilter | null,
  ) {
    this.validator = new EventValidator(config);
    this.enricher = new EventEnricher({
      enrichGeo: config.enrichGeo,
      enrichUA: config.enrichUA,
      anonymizeIp: config.anonymizeIp,
    });
    this.dlq = new DeadLetterQueue();
  }

  /**
   * Process a raw batch payload through the full pipeline.
   *
   * Flow:
   *  1. Schema validation (structure, types, required fields)
   *  2. Consent filtering (respect user's consent state)
   *  3. PII masking (credit cards, SSNs, passwords)
   *  4. Deduplication (sliding-window by event ID)
   *  5. Server-side enrichment (GeoIP, UA parsing, IP anonymization)
   *  6. Fan-out to all configured sinks (Kafka, S3, ClickHouse, Redis)
   */
  async process(
    rawPayload: unknown,
    projectId: string,
    clientIp: string,
  ): Promise<PipelineResult> {
    const elapsed = startTimer();

    // Step 1: Validate batch envelope
    const batch = this.validator.validateBatch(rawPayload);

    metrics.recordBatchReceived(projectId, batch.batch.length);

    // Step 2: Validate individual events (schema + consent + PII)
    const validation = this.validator.validateEvents(batch.batch);

    let accepted = validation.valid;
    let deduplicated = 0;

    // Step 3: Deduplication
    if (this.dedup && accepted.length > 0) {
      const dupeIds = await this.dedup.filterDuplicates(accepted.map(e => e.id));
      if (dupeIds.size > 0) {
        deduplicated = dupeIds.size;
        accepted = accepted.filter(e => !dupeIds.has(e.id));
        logger.debug('Deduplicated events', { removed: deduplicated });
      }
    }

    // Step 4: Enrichment
    let enriched: EnrichedEvent[] = [];
    if (accepted.length > 0) {
      enriched = this.enricher.enrich(accepted, projectId, clientIp);

      // Stamp processing time
      const processingMs = elapsed();
      for (const event of enriched) {
        event.processedAt = new Date().toISOString();
        if (event.enrichment) {
          event.enrichment.processingDurationMs = processingMs;
        }
      }
    }

    // Step 5: Route to sinks
    if (enriched.length > 0) {
      try {
        await this.router.route(enriched);
        metrics.recordEventsProcessed(enriched.length, projectId);
      } catch (error) {
        logger.error('Sink routing failed', error as Error, { projectId, eventCount: enriched.length });
        // Send to DLQ
        for (const event of enriched) {
          this.dlq.push(event, (error as Error).message);
        }
      }
    }

    // Track dropped events
    if (validation.invalid.length > 0) {
      metrics.recordEventsDropped(validation.invalid.length, 'validation');

      // Send invalid events to DLQ for inspection
      if (this.config.deadLetterEnabled) {
        for (const inv of validation.invalid) {
          this.dlq.push(inv.event, inv.errors.join('; '));
        }
      }
    }

    if (validation.filtered > 0) {
      metrics.recordEventsDropped(validation.filtered, 'consent');
    }

    if (deduplicated > 0) {
      metrics.recordEventsDropped(deduplicated, 'dedup');
    }

    const processingMs = elapsed();
    metrics.recordProcessingDuration(processingMs, projectId);

    return {
      accepted: enriched.length,
      rejected: validation.invalid.length,
      deduplicated,
      filtered: validation.filtered,
      processingMs,
    };
  }

  /** Get DLQ size for monitoring */
  get dlqSize(): number {
    return this.dlq.size;
  }

  /** Drain DLQ for reprocessing */
  drainDLQ(limit?: number): Array<{ event: unknown; error: string; timestamp: string }> {
    return this.dlq.drain(limit);
  }
}
