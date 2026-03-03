// =============================================================================
// AETHER INGESTION — RATE LIMITING MIDDLEWARE
// Token bucket rate limiter per API key with configurable limits
// =============================================================================

import type { ServerResponse } from 'node:http';
import { RateLimiter } from '@aether/auth';
import { RateLimitError } from '@aether/common';
import { createLogger } from '@aether/logger';
import type { AuthenticatedRequest } from './auth.js';
import { metrics } from '../metrics.js';

const logger = createLogger('aether.ingestion.ratelimit');

export function createRateLimitMiddleware(limiter: RateLimiter) {
  return async function rateLimitMiddleware(
    req: AuthenticatedRequest,
    res: ServerResponse,
  ): Promise<void> {
    if (!req.apiKey) return; // Auth middleware didn't run yet

    const key = req.apiKey.projectId;
    const limits = req.apiKey.rateLimits;
    const result = limiter.check(key, limits);

    // Set rate limit headers
    res.setHeader('X-RateLimit-Limit', limits.eventsPerMinute);
    res.setHeader('X-RateLimit-Remaining', result.remaining);
    res.setHeader('X-RateLimit-Reset', Math.ceil(result.resetMs / 1000));

    if (!result.allowed) {
      metrics.recordRateLimitHit(key);
      logger.warn('Rate limit exceeded', { projectId: key, limit: limits.eventsPerMinute });

      const retryAfter = Math.ceil(result.resetMs / 1000);
      res.setHeader('Retry-After', retryAfter);
      throw new RateLimitError(retryAfter);
    }
  };
}

/** Record batch size against rate limit (called after validation) */
export function consumeRateLimit(limiter: RateLimiter, projectId: string, eventCount: number): void {
  limiter.consume(projectId, eventCount);
}
