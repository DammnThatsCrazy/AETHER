// =============================================================================
// AETHER INGESTION — CORS MIDDLEWARE
// =============================================================================

import type { IncomingMessage, ServerResponse } from 'node:http';
import type { CorsConfig } from '@aether/common';

export function createCorsMiddleware(config: CorsConfig) {
  const allowedOrigins = new Set(config.origins);
  const allowAll = allowedOrigins.has('*');

  return function corsMiddleware(req: IncomingMessage, res: ServerResponse): boolean {
    const origin = req.headers['origin'];

    if (origin && (allowAll || allowedOrigins.has(origin))) {
      res.setHeader('Access-Control-Allow-Origin', allowAll ? '*' : origin);
    }

    res.setHeader('Access-Control-Allow-Methods', config.methods.join(', '));
    res.setHeader('Access-Control-Allow-Headers', config.allowedHeaders.join(', '));
    res.setHeader('Access-Control-Max-Age', config.maxAge);
    res.setHeader('Access-Control-Expose-Headers', 'X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, X-Request-Id');

    // Handle preflight
    if (req.method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return true; // Signals that response has been sent
    }

    return false;
  };
}

// =============================================================================
// ERROR HANDLER
// =============================================================================

import { AetherError } from '@aether/common';
import { createLogger } from '@aether/logger';

const logger = createLogger('aether.ingestion.error');

export function handleError(error: unknown, res: ServerResponse, requestId: string): void {
  if (error instanceof AetherError) {
    const body = JSON.stringify({
      error: {
        code: error.code,
        message: error.message,
        details: error.details,
        requestId,
      },
    });

    res.writeHead(error.statusCode, { 'Content-Type': 'application/json' });
    res.end(body);

    if (error.statusCode >= 500) {
      logger.error('Server error', error, { requestId, code: error.code });
    }
    return;
  }

  // Unexpected errors
  const message = error instanceof Error ? error.message : 'Internal server error';
  logger.error('Unhandled error', error instanceof Error ? error : new Error(String(error)), { requestId });

  const body = JSON.stringify({
    error: {
      code: 'INTERNAL_ERROR',
      message: process.env.NODE_ENV === 'production' ? 'Internal server error' : message,
      requestId,
    },
  });

  res.writeHead(500, { 'Content-Type': 'application/json' });
  res.end(body);
}

// =============================================================================
// REQUEST BODY PARSER
// =============================================================================

export function parseBody(req: IncomingMessage, maxBytes: number = 5 * 1024 * 1024): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;

    req.on('data', (chunk: Buffer) => {
      size += chunk.length;
      if (size > maxBytes) {
        req.destroy();
        reject(new AetherError(`Request body exceeds ${maxBytes} bytes`, 'PAYLOAD_TOO_LARGE', 413));
        return;
      }
      chunks.push(chunk);
    });

    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}
