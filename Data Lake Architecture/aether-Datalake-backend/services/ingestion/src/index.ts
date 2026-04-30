// =============================================================================
// Aether INGESTION SERVICE — MAIN ENTRY POINT
// High-throughput HTTP event ingestion server
//
// Architecture:
//   SDK → POST /v1/batch → Auth → RateLimit → Validate → Dedup → Enrich → Sinks
//                                                                           ├─ Kafka (real-time stream)
//                                                                           ├─ S3 (data lake / archival)
//                                                                           ├─ ClickHouse (OLAP analytics)
//                                                                           └─ Redis (real-time counters)
// =============================================================================

import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { createLogger } from '@aether/logger';
import { loadIngestionConfig } from '@aether/common';
import { ApiKeyValidator, InMemoryApiKeyStore, RateLimiter } from '@aether/auth';
import { EventRouter, createSink } from '@aether/events';
import { InMemoryCache, DeduplicationFilter } from '@aether/cache';
import { IngestionPipeline } from './pipeline.js';
import { createAuthMiddleware, type AuthenticatedRequest } from './middleware/auth.js';
import { createRateLimitMiddleware } from './middleware/rate-limit.js';
import { createCorsMiddleware, handleError } from './middleware/cors-and-errors.js';
import { createBatchHandler } from './routes/batch.js';
import { createSingleEventHandler } from './routes/track.js';
import { createHealthHandler, handleMetrics, handleStatus } from './routes/health.js';
import { metrics } from './metrics.js';
import { sha256 } from '@aether/common';

const logger = createLogger('aether.ingestion');

// =============================================================================
// SERVER BOOTSTRAP
// =============================================================================

async function bootstrap(): Promise<void> {
  const config = loadIngestionConfig();

  logger.info('Starting Aether Ingestion Service', {
    port: config.port,
    environment: config.environment,
    sinks: config.sinks.map(s => s.type),
  });

  // -------------------------------------------------------------------------
  // Dependencies
  // -------------------------------------------------------------------------

  // API Key store (production: DynamoDB/PostgreSQL backed)
  const keyStore = new InMemoryApiKeyStore();

  // Seed a development API key
  if (config.environment === 'development') {
    const devKey = 'ak_dev_aether_test_key_12345678';
    keyStore.addKey({
      key: devKey,
      keyHash: sha256(devKey),
      projectId: 'proj_dev_001',
      projectName: 'Development Project',
      organizationId: 'org_dev',
      environment: 'development',
      permissions: { write: true, read: true, admin: false },
      rateLimits: {
        eventsPerSecond: 100,
        eventsPerMinute: 5000,
        batchSizeLimit: 500,
        dailyEventLimit: 1_000_000,
      },
      createdAt: new Date().toISOString(),
      isActive: true,
    });
    logger.info('Development API key seeded', { key: devKey });
  }

  const keyValidator = new ApiKeyValidator(keyStore);
  const rateLimiter = new RateLimiter(config.rateLimiting.windowMs);

  // Cache (for deduplication + real-time counters)
  const cache = new InMemoryCache();
  const dedup = config.processing.deduplicationWindowMs > 0
    ? new DeduplicationFilter(cache, config.processing.deduplicationWindowMs)
    : null;

  // Event router + sinks
  const router = new EventRouter();
  for (const sinkConfig of config.sinks) {
    const sink = createSink(sinkConfig);
    await router.addSink(sink);
  }

  // Ingestion pipeline
  const pipeline = new IngestionPipeline(config.processing, router, dedup);

  // -------------------------------------------------------------------------
  // Middleware & Route Handlers
  // -------------------------------------------------------------------------

  const cors = createCorsMiddleware(config.cors);
  const auth = createAuthMiddleware(keyValidator);
  const rateLimit = createRateLimitMiddleware(rateLimiter);

  const handleBatch = createBatchHandler(pipeline, rateLimiter);
  const handleTrack = createSingleEventHandler('track', pipeline, rateLimiter);
  const handlePage = createSingleEventHandler('page', pipeline, rateLimiter);
  const handleIdentify = createSingleEventHandler('identify', pipeline, rateLimiter);
  const handleConversion = createSingleEventHandler('conversion', pipeline, rateLimiter);
  const handleHealth = createHealthHandler(router);

  // -------------------------------------------------------------------------
  // HTTP Router
  // -------------------------------------------------------------------------

  let activeConnections = 0;

  const server = createServer(async (req: IncomingMessage, res: ServerResponse) => {
    activeConnections++;
    metrics.setActiveConnections(activeConnections);

    const requestId = `req_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    res.setHeader('X-Request-Id', requestId);
    res.setHeader('X-Powered-By', 'Aether/4.0');

    try {
      // CORS (handles OPTIONS preflight)
      if (cors(req, res)) {
        activeConnections--;
        return;
      }

      const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
      const path = url.pathname;
      const method = req.method?.toUpperCase() ?? 'GET';

      // Public routes (no auth required)
      if (path === '/health' || path === config.monitoring.healthCheckPath) {
        await handleHealth(req, res);
        activeConnections--;
        return;
      }

      if (path === '/metrics' && method === 'GET') {
        handleMetrics(req, res);
        activeConnections--;
        return;
      }

      if (path === '/status' && method === 'GET') {
        handleStatus(req, res);
        activeConnections--;
        return;
      }

      // Authenticated routes
      if (path.startsWith('/v1/')) {
        await auth(req as AuthenticatedRequest, res);
        await rateLimit(req as AuthenticatedRequest, res);

        if (path === '/v1/batch' && method === 'POST') {
          await handleBatch(req as AuthenticatedRequest, res);
        } else if (path === '/v1/track' && method === 'POST') {
          await handleTrack(req as AuthenticatedRequest, res);
        } else if (path === '/v1/page' && method === 'POST') {
          await handlePage(req as AuthenticatedRequest, res);
        } else if (path === '/v1/identify' && method === 'POST') {
          await handleIdentify(req as AuthenticatedRequest, res);
        } else if (path === '/v1/conversion' && method === 'POST') {
          await handleConversion(req as AuthenticatedRequest, res);
        } else {
          res.writeHead(404, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: { code: 'NOT_FOUND', message: `${method} ${path} not found` } }));
        }
      } else {
        // Root
        if (path === '/' && method === 'GET') {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({
            service: 'aether-ingestion',
            version: '4.0.0',
            docs: 'https://docs.aether.network/api/ingestion',
          }));
        } else {
          res.writeHead(404, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: { code: 'NOT_FOUND', message: `${method} ${path} not found` } }));
        }
      }
    } catch (error) {
      handleError(error, res, requestId);
    } finally {
      activeConnections--;
      metrics.setActiveConnections(activeConnections);
    }
  });

  // -------------------------------------------------------------------------
  // Graceful Shutdown
  // -------------------------------------------------------------------------

  const shutdown = async (signal: string) => {
    logger.info(`Received ${signal}, starting graceful shutdown...`);

    // Stop accepting new connections
    server.close();

    // Wait for in-flight requests (max 30s)
    const shutdownTimeout = setTimeout(() => {
      logger.warn('Shutdown timeout exceeded, forcing exit');
      process.exit(1);
    }, 30_000);

    try {
      // Flush all sinks
      logger.info('Flushing sinks...');
      await router.flush();

      // Close sinks
      logger.info('Closing sinks...');
      await router.close();

      // Close cache
      await cache.close();

      // Clean up rate limiter
      rateLimiter.destroy();

      clearTimeout(shutdownTimeout);
      logger.info('Graceful shutdown complete');
      process.exit(0);
    } catch (error) {
      logger.error('Error during shutdown', error as Error);
      clearTimeout(shutdownTimeout);
      process.exit(1);
    }
  };

  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));

  // Uncaught error handlers
  process.on('uncaughtException', (error) => {
    logger.fatal('Uncaught exception', error);
    shutdown('uncaughtException');
  });

  process.on('unhandledRejection', (reason) => {
    logger.error('Unhandled rejection', reason as Error);
  });

  // -------------------------------------------------------------------------
  // Start Server
  // -------------------------------------------------------------------------

  server.listen(config.port, config.host, () => {
    logger.info(`Aether Ingestion Service listening on ${config.host}:${config.port}`, {
      environment: config.environment,
      sinks: config.sinks.map(s => s.type),
      rateLimiting: config.rateLimiting.enabled,
      deduplication: config.processing.deduplicationWindowMs > 0,
      geoEnrichment: config.processing.enrichGeo,
    });
  });
}

// Run
bootstrap().catch((error) => {
  logger.fatal('Failed to start ingestion service', error);
  process.exit(1);
});
