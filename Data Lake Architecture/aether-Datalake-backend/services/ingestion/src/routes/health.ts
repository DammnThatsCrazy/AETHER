// =============================================================================
// AETHER INGESTION — HEALTH & METRICS ROUTES
// GET /health, GET /metrics, GET /status
// =============================================================================

import type { IncomingMessage, ServerResponse } from 'node:http';
import type { EventRouter } from '@aether/events';
import type { HealthStatus } from '@aether/common';
import { metrics } from '../metrics.js';

const VERSION = '4.0.0';
const startTime = Date.now();

export function createHealthHandler(router: EventRouter) {
  return async function handleHealth(
    _req: IncomingMessage,
    res: ServerResponse,
  ): Promise<void> {
    const sinkHealth = await router.healthCheck();

    const allHealthy = Object.values(sinkHealth).every(s => s.healthy);
    const anyDown = Object.values(sinkHealth).some(s => !s.healthy);

    const status: HealthStatus = {
      status: allHealthy ? 'healthy' : anyDown ? 'degraded' : 'healthy',
      version: VERSION,
      uptime: Math.floor((Date.now() - startTime) / 1000),
      timestamp: new Date().toISOString(),
      checks: {},
    };

    // Add sink health
    for (const [name, health] of Object.entries(sinkHealth)) {
      status.checks[`sink:${name}`] = {
        status: health.healthy ? 'up' : 'down',
        latencyMs: health.latencyMs,
        lastCheck: new Date().toISOString(),
      };
    }

    // Process health
    status.checks['process'] = {
      status: 'up',
      message: `Memory: ${Math.round(process.memoryUsage().heapUsed / 1024 / 1024)}MB`,
      lastCheck: new Date().toISOString(),
    };

    const statusCode = status.status === 'unhealthy' ? 503 : 200;
    res.writeHead(statusCode, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(status));
  };
}

export function handleMetrics(
  _req: IncomingMessage,
  res: ServerResponse,
): void {
  const accept = _req.headers['accept'] ?? '';

  if (accept.includes('text/plain') || accept.includes('text/plain; version=0.0.4')) {
    // Prometheus format
    res.writeHead(200, { 'Content-Type': 'text/plain; version=0.0.4; charset=utf-8' });
    res.end(metrics.toPrometheus());
  } else {
    // JSON format
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(metrics.snapshot(), null, 2));
  }
}

export function handleStatus(
  _req: IncomingMessage,
  res: ServerResponse,
): void {
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({
    service: 'aether-ingestion',
    version: VERSION,
    uptime: Math.floor((Date.now() - startTime) / 1000),
    environment: process.env.NODE_ENV ?? 'development',
    node: process.version,
    memory: {
      heapUsed: Math.round(process.memoryUsage().heapUsed / 1024 / 1024),
      heapTotal: Math.round(process.memoryUsage().heapTotal / 1024 / 1024),
      rss: Math.round(process.memoryUsage().rss / 1024 / 1024),
    },
    metrics: metrics.snapshot(),
  }));
}
