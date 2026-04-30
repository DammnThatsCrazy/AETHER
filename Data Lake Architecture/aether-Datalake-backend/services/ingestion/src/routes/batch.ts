// =============================================================================
// Aether INGESTION — BATCH ROUTE
// POST /v1/batch — Primary event ingestion endpoint
// =============================================================================

import type { ServerResponse } from 'node:http';
import { createLogger } from '@aether/logger';
import { extractClientIp, generateId, safeJsonParse } from '@aether/common';
import { RateLimiter } from '@aether/auth';
import type { AuthenticatedRequest } from '../middleware/auth.js';
import { consumeRateLimit } from '../middleware/rate-limit.js';
import { parseBody } from '../middleware/cors-and-errors.js';
import type { IngestionPipeline } from '../pipeline.js';

const logger = createLogger('aether.ingestion.routes.batch');

export function createBatchHandler(pipeline: IngestionPipeline, rateLimiter: RateLimiter) {
  return async function handleBatch(
    req: AuthenticatedRequest,
    res: ServerResponse,
  ): Promise<void> {
    const requestId = generateId();
    res.setHeader('X-Request-Id', requestId);

    const projectId = req.projectId!;

    // Parse body
    const rawBody = await parseBody(req);
    const payload = safeJsonParse(rawBody);

    if (!payload) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        error: { code: 'INVALID_JSON', message: 'Request body is not valid JSON', requestId },
      }));
      return;
    }

    // Extract client IP for enrichment
    const clientIp = extractClientIp(req.headers as Record<string, string | string[] | undefined>);

    // Process through pipeline
    const result = await pipeline.process(payload, projectId, clientIp);

    // Consume rate limit tokens for the batch
    if (req.apiKey) {
      consumeRateLimit(rateLimiter, projectId, result.accepted);
    }

    // Response
    const status = result.rejected > 0 && result.accepted === 0 ? 400 : 200;

    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      success: result.accepted > 0,
      requestId,
      accepted: result.accepted,
      rejected: result.rejected,
      deduplicated: result.deduplicated,
      filtered: result.filtered,
      processingMs: Math.round(result.processingMs * 100) / 100,
    }));

    logger.info('Batch processed', {
      requestId,
      projectId,
      accepted: result.accepted,
      rejected: result.rejected,
      deduplicated: result.deduplicated,
      processingMs: result.processingMs,
    });
  };
}
