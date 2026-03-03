// =============================================================================
// AETHER INGESTION — SINGLE-EVENT ROUTES
// POST /v1/track, POST /v1/page, POST /v1/identify, POST /v1/conversion
// Convenience endpoints that wrap events into batch format
// =============================================================================

import type { ServerResponse } from 'node:http';
import { createLogger } from '@aether/logger';
import { extractClientIp, generateId, now, safeJsonParse } from '@aether/common';
import type { EventType } from '@aether/common';
import { RateLimiter } from '@aether/auth';
import type { AuthenticatedRequest } from '../middleware/auth.js';
import { consumeRateLimit } from '../middleware/rate-limit.js';
import { parseBody } from '../middleware/cors-and-errors.js';
import type { IngestionPipeline } from '../pipeline.js';

const logger = createLogger('aether.ingestion.routes.track');

/**
 * Creates a handler for single-event endpoints.
 * These accept a simpler payload and wrap it into the batch format.
 */
export function createSingleEventHandler(
  eventType: EventType,
  pipeline: IngestionPipeline,
  rateLimiter: RateLimiter,
) {
  return async function handleSingleEvent(
    req: AuthenticatedRequest,
    res: ServerResponse,
  ): Promise<void> {
    const requestId = generateId();
    res.setHeader('X-Request-Id', requestId);

    const projectId = req.projectId!;
    const rawBody = await parseBody(req);
    const body = safeJsonParse<Record<string, unknown>>(rawBody);

    if (!body) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        error: { code: 'INVALID_JSON', message: 'Request body is not valid JSON', requestId },
      }));
      return;
    }

    // Build a proper event from the simplified payload
    const event = {
      id: (body.id as string) ?? generateId(),
      type: eventType,
      timestamp: (body.timestamp as string) ?? now(),
      sessionId: (body.sessionId as string) ?? 'server-side',
      anonymousId: (body.anonymousId as string) ?? (body.userId as string) ?? 'anonymous',
      userId: body.userId as string | undefined,
      event: body.event as string | undefined,
      properties: (body.properties as Record<string, unknown>) ?? {},
      context: (body.context as Record<string, unknown>) ?? {},
    };

    // Wrap into batch format
    const batchPayload = {
      batch: [event],
      sentAt: now(),
    };

    const clientIp = extractClientIp(req.headers as Record<string, string | string[] | undefined>);
    const result = await pipeline.process(batchPayload, projectId, clientIp);

    if (req.apiKey) {
      consumeRateLimit(rateLimiter, projectId, result.accepted);
    }

    const status = result.accepted > 0 ? 200 : 400;
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      success: result.accepted > 0,
      requestId,
      ...(result.rejected > 0 ? { error: 'Event validation failed' } : {}),
    }));
  };
}
