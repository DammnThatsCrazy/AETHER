import { useState, useEffect, useCallback } from 'react';
import type { SystemHealth, DependencyHealth, CircuitBreakerState, ErrorFingerprint, Severity, HealthStatus } from '@kyber/types';
import { api } from '@kyber/lib/api/endpoints';

interface HealthApiResponse {
  status: string;
  uptime?: number;
  timestamp?: string;
  services?: Record<string, { status: string; latency_ms?: number; error?: string | null }>;
  [key: string]: unknown;
}

interface ErrorsApiResponse {
  errors: {
    fingerprint: string;
    message: string;
    count: number;
    first_seen: string;
    last_seen: string;
    severity: string;
    suppressed?: boolean;
  }[];
  count: number;
}

interface DiagnosticReportResponse {
  health?: HealthApiResponse;
  errors?: ErrorsApiResponse['errors'];
  circuit_breakers?: Record<string, { state: string; failures: number; last_failure?: string | null; next_retry?: string | null }>;
  services?: Record<string, unknown>;
  event_lag?: Partial<{ current_ms: number; avg_ms: number; max_ms: number; trend: string }>;
  graph_lag?: Partial<{ current_ms: number; avg_ms: number; max_ms: number; trend: string }>;
  [key: string]: unknown;
}

function mapHealthStatus(raw: string): HealthStatus['status'] {
  if (raw === 'ok' || raw === 'healthy') return 'healthy';
  if (raw === 'degraded') return 'degraded';
  if (raw === 'unhealthy' || raw === 'down') return 'unhealthy';
  return 'unknown';
}

export function mapToSystemHealth(
  healthResp: HealthApiResponse,
  errorsResp: ErrorsApiResponse,
  circuitBreakers: Record<string, { state: string; failures: number; last_failure?: string | null; next_retry?: string | null }>,
  report: DiagnosticReportResponse,
): SystemHealth {
  const observedAt = healthResp.timestamp;
  const lag = (value: DiagnosticReportResponse['event_lag']): SystemHealth['eventLag'] => ({
    currentMs: typeof value?.current_ms === 'number' ? value.current_ms : null,
    avgMs: typeof value?.avg_ms === 'number' ? value.avg_ms : null,
    maxMs: typeof value?.max_ms === 'number' ? value.max_ms : null,
    trend: value?.trend === 'improving' || value?.trend === 'degrading' || value?.trend === 'stable'
      ? value.trend
      : 'unknown',
  });

  const dependencies: DependencyHealth[] = Object.entries(healthResp.services ?? {}).map(([name, svc]) => ({
    name,
    type: 'api' as DependencyHealth['type'],
    status: { status: mapHealthStatus(svc.status), ...(observedAt ? { lastChecked: observedAt } : {}) },
    latencyMs: svc.latency_ms ?? null,
    lastError: svc.error ?? undefined,
  }));

  const cbStates: CircuitBreakerState[] = Object.entries(circuitBreakers).map(([name, cb]) => ({
    name,
    state: (cb.state === 'closed' || cb.state === 'open' || cb.state === 'half-open' ? cb.state : 'unknown') as CircuitBreakerState['state'],
    failureCount: cb.failures,
    lastFailure: cb.last_failure ?? undefined,
    nextRetry: cb.next_retry ?? undefined,
  }));

  const errorFingerprints: ErrorFingerprint[] = errorsResp.errors.map(e => ({
    fingerprint: e.fingerprint,
    message: e.message,
    count: e.count,
    firstSeen: e.first_seen,
    lastSeen: e.last_seen,
    severity: (e.severity as Severity) ?? 'info',
    suppressed: e.suppressed ?? false,
  }));

  const severityDistribution: Record<Severity, number> = { P0: 0, P1: 0, P2: 0, P3: 0, info: 0 };
  for (const ef of errorFingerprints) {
    if (ef.severity in severityDistribution) {
      severityDistribution[ef.severity] += ef.count;
    }
  }

  return {
    overall: { status: mapHealthStatus(healthResp.status), ...(observedAt ? { lastChecked: observedAt } : {}) },
    dependencies,
    circuitBreakers: cbStates,
    errorFingerprints,
    severityDistribution,
    eventLag: lag(report.event_lag),
    graphLag: lag(report.graph_lag),
    adapterReadiness: [],
    environmentValidation: [],
  };
}

export function useDiagnosticsData() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsLoading(true);
    setError(null);
    Promise.all([
      api.diagnostics.health(),
      api.diagnostics.errors(),
      api.diagnostics.circuitBreakers(),
      api.diagnostics.report(),
    ])
      .then(([healthResp, errorsResp, cbResp, reportResp]) => {
        const mapped = mapToSystemHealth(
          healthResp as HealthApiResponse,
          errorsResp as ErrorsApiResponse,
          cbResp as Record<string, { state: string; failures: number; last_failure?: string | null; next_retry?: string | null }>,
          reportResp as DiagnosticReportResponse,
        );
        setHealth(mapped);
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load health');
        setHealth(null);
        setIsLoading(false);
      });
  }, []);

  const suppressError = useCallback((fingerprint: string) => {
    if (!health) return;

    api.diagnostics.suppressError(fingerprint)
      .then(() => {
        setHealth(prev => {
          if (!prev) return prev;
          return {
            ...prev,
            errorFingerprints: prev.errorFingerprints.map(ef =>
              ef.fingerprint === fingerprint ? { ...ef, suppressed: true } : ef
            ),
          };
        });
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to suppress error');
      });
  }, [health]);

  return { health, isLoading, error, suppressError };
}
