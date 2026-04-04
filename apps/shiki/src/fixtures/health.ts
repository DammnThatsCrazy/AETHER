import type { SystemHealth } from '@shiki/types';

export const getMockHealthData = getMockSystemHealth;

export function getMockSystemHealth(): SystemHealth {
  const now = new Date().toISOString();
  const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString();
  const tenMinAgo = new Date(Date.now() - 10 * 60_000).toISOString();
  const oneHourAgo = new Date(Date.now() - 60 * 60_000).toISOString();
  const oneDayAgo = new Date(Date.now() - 24 * 60 * 60_000).toISOString();
  const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60_000).toISOString();

  return {
    overall: {
      status: 'degraded',
      message: 'Redis cache experiencing elevated latency',
      lastChecked: now,
    },
    dependencies: [
      { name: 'postgres', type: 'database', status: { status: 'healthy', lastChecked: now }, latencyMs: 3.2, lastError: undefined },
      { name: 'redis', type: 'cache', status: { status: 'degraded', message: 'Elevated latency detected', lastChecked: now }, latencyMs: 45.8, lastError: 'Connection pool exhaustion at ' + tenMinAgo },
      { name: 'kafka', type: 'queue', status: { status: 'healthy', lastChecked: now }, latencyMs: 8.1, lastError: undefined },
      { name: 'neptune', type: 'graph', status: { status: 'healthy', lastChecked: now }, latencyMs: 12.4, lastError: undefined },
      { name: 's3', type: 'storage', status: { status: 'healthy', lastChecked: now }, latencyMs: 22.0, lastError: undefined },
      { name: 'clickhouse', type: 'analytics', status: { status: 'healthy', lastChecked: now }, latencyMs: 15.7, lastError: undefined },
      { name: 'auth-service', type: 'api', status: { status: 'healthy', lastChecked: now }, latencyMs: 5.3, lastError: undefined },
      { name: 'notification-service', type: 'api', status: { status: 'unhealthy', message: 'Service unreachable', lastChecked: fiveMinAgo }, latencyMs: -1, lastError: 'ECONNREFUSED at ' + fiveMinAgo },
    ],
    circuitBreakers: [
      { name: 'redis-write', state: 'half-open', failureCount: 3, lastFailure: tenMinAgo, nextRetry: now },
      { name: 'notification-dispatch', state: 'open', failureCount: 12, lastFailure: fiveMinAgo, nextRetry: new Date(Date.now() + 2 * 60_000).toISOString() },
      { name: 'neptune-query', state: 'closed', failureCount: 0, lastFailure: undefined, nextRetry: undefined },
      { name: 'kafka-produce', state: 'closed', failureCount: 0, lastFailure: undefined, nextRetry: undefined },
      { name: 'clickhouse-ingest', state: 'closed', failureCount: 0, lastFailure: oneDayAgo, nextRetry: undefined },
      { name: 's3-upload', state: 'closed', failureCount: 0, lastFailure: undefined, nextRetry: undefined },
    ],
    errorFingerprints: [
      { fingerprint: 'ERR-FP-001', message: 'Redis connection pool exhausted during peak load', count: 47, firstSeen: oneHourAgo, lastSeen: fiveMinAgo, severity: 'P1', suppressed: false },
      { fingerprint: 'ERR-FP-002', message: 'Notification service ECONNREFUSED', count: 128, firstSeen: oneDayAgo, lastSeen: now, severity: 'P0', suppressed: false },
      { fingerprint: 'ERR-FP-003', message: 'GraphQL query timeout on entity resolver', count: 12, firstSeen: threeDaysAgo, lastSeen: oneHourAgo, severity: 'P2', suppressed: false },
      { fingerprint: 'ERR-FP-004', message: 'S3 presigned URL generation slow (>500ms)', count: 8, firstSeen: oneDayAgo, lastSeen: tenMinAgo, severity: 'P3', suppressed: true },
      { fingerprint: 'ERR-FP-005', message: 'WebSocket heartbeat missed for client pool', count: 3, firstSeen: oneHourAgo, lastSeen: fiveMinAgo, severity: 'P2', suppressed: false },
      { fingerprint: 'ERR-FP-006', message: 'Kafka consumer lag exceeding threshold', count: 22, firstSeen: oneDayAgo, lastSeen: tenMinAgo, severity: 'P1', suppressed: false },
      { fingerprint: 'ERR-FP-007', message: 'ClickHouse materialized view refresh delayed', count: 2, firstSeen: threeDaysAgo, lastSeen: oneDayAgo, severity: 'info', suppressed: true },
    ],
    severityDistribution: {
      P0: 128,
      P1: 69,
      P2: 15,
      P3: 8,
      info: 2,
    },
    eventLag: {
      currentMs: 120,
      avgMs: 85,
      maxMs: 340,
      trend: 'degrading',
    },
    graphLag: {
      currentMs: 45,
      avgMs: 38,
      maxMs: 180,
      trend: 'stable',
    },
    adapterReadiness: [
      { name: 'REST API', type: 'rest', ready: true, lastCheck: now, error: undefined },
      { name: 'GraphQL Gateway', type: 'graphql', ready: true, lastCheck: now, error: undefined },
      { name: 'WebSocket Server', type: 'websocket', ready: true, lastCheck: now, error: undefined },
      { name: 'Mock Adapter', type: 'mock', ready: true, lastCheck: now, error: undefined },
    ],
    environmentValidation: [
      { variable: 'VITE_SHIKI_ENV', required: true, present: true, valid: true, message: undefined },
      { variable: 'VITE_API_BASE_URL', required: true, present: true, valid: true, message: undefined },
      { variable: 'VITE_WS_URL', required: true, present: true, valid: true, message: undefined },
      { variable: 'VITE_GRAPHQL_URL', required: true, present: true, valid: true, message: undefined },
      { variable: 'VITE_OIDC_AUTHORITY', required: true, present: true, valid: true, message: undefined },
      { variable: 'VITE_OIDC_CLIENT_ID', required: true, present: true, valid: true, message: undefined },
      { variable: 'VITE_AUTOMATION_POSTURE', required: true, present: true, valid: true, message: undefined },
      { variable: 'VITE_NEPTUNE_ENDPOINT', required: false, present: true, valid: true, message: undefined },
      { variable: 'VITE_CLICKHOUSE_URL', required: false, present: false, valid: false, message: 'Optional: ClickHouse analytics will use fallback' },
      { variable: 'VITE_SENTRY_DSN', required: false, present: false, valid: false, message: 'Optional: Error reporting disabled' },
    ],
  };
}
