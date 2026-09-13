// =============================================================================
// Aether INGESTION — AUTHENTICATION MIDDLEWARE
// Extracts + validates API key, attaches project context to request
// =============================================================================

import type { IncomingMessage, ServerResponse } from 'node:http';
import { ApiKeyValidator } from '@aether/auth';
import type { ApiKeyRecord } from '@aether/common';
import { AuthenticationError } from '@aether/common';
import { createLogger } from '@aether/logger';
import { metrics } from '../metrics.js';

const logger = createLogger('aether.ingestion.auth');

/** Extended request with resolved project info */
export interface AuthenticatedRequest extends IncomingMessage {
  apiKey?: ApiKeyRecord;
  projectId?: string;
}

export function createAuthMiddleware(validator: ApiKeyValidator) {
  return async function authMiddleware(
    req: AuthenticatedRequest,
    _res: ServerResponse,
  ): Promise<void> {
    // Extract API key from header or query
    const authHeader = req.headers['authorization'] as string | undefined;
    const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
    const queryKey = url.searchParams.get('key') ?? undefined;

    const key = ApiKeyValidator.extractKey(authHeader, queryKey);

    if (!key) {
      metrics.recordAuthResult(false);
      throw new AuthenticationError('Missing API key. Provide via Authorization header or "key" query parameter.');
    }

    const record = await validator.validate(key);

    if (!record) {
      metrics.recordAuthResult(false);
      logger.warn('Invalid API key attempted', { keyPrefix: key.slice(0, 8) + '...' });
      throw new AuthenticationError('Invalid or expired API key');
    }

    // Check origin restriction
    if (record.permissions.allowedOrigins && record.permissions.allowedOrigins.length > 0) {
      const origin = req.headers['origin'] as string | undefined;
      if (origin && !record.permissions.allowedOrigins.includes(origin) && !record.permissions.allowedOrigins.includes('*')) {
        metrics.recordAuthResult(false);
        throw new AuthenticationError(`Origin "${origin}" is not allowed for this API key`);
      }
    }

    // Check write permission
    if (!record.permissions.write) {
      metrics.recordAuthResult(false);
      throw new AuthenticationError('API key does not have write permission');
    }

    // Attach to request
    req.apiKey = record;
    req.projectId = record.projectId;

    metrics.recordAuthResult(true);
    logger.debug('Authenticated request', { projectId: record.projectId, env: record.environment });
  };
}
