import { useState, useEffect, useCallback } from 'react';
import type { SystemHealth, DependencyHealth, CircuitBreakerState, ErrorFingerprint, Severity, HealthStatus } from '@shiki/types';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockSystemHealth } from '@shiki/fixtures/health';
import { api } from '@shiki/lib/api/endpoints';

interface HealthApiResponse {
  status: string;
  uptime?: number;
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
  [key: string]: unknown;
}

function mapHealthStatus(raw: string): HealthStatus['status'] {
  if (raw === 'ok' || raw === 'healthy') return 'healthy';
  if (raw === 'degraded') return 'degraded';
  if (raw === 'unhealthy' || raw === 'down') return 'unhealthy';
  return 'unknown';
}

function mapToSystemHealth(
  healthResp: HealthApiResponse,
  errorsResp: ErrorsApiResponse,
  circuitBreakers: Record<string, { state: string; failures: number; last_failure?: string | null; next_retry?: string | null }>,
  report: DiagnosticReportResponse,
): SystemHealth {
  const now = new Date().toISOString();

  const dependencies: DependencyHealth[] = Object.entries(healthResp.services ?? {}).map(([name, svc]) => ({
    name,
    type: 'api' as DependencyHealth['type'],
    status: { status: mapHealthStatus(svc.status), lastChecked: now },
    latencyMs: svc.latency_ms ?? 0,
    lastError: svc.error ?? undefined,
  }));

  const cbStates: CircuitBreakerState[] = Object.entries(circuitBreakers).map(([name, cb]) => ({
    name,
    state: (cb.state === 'closed' || cb.state === 'open' || cb.state === 'half-open' ? cb.state : 'closed') as CircuitBreakerState['state'],
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
    overall: { status: mapHealthStatus(healthResp.status), lastChecked: now },
    dependencies,
    circuitBreakers: cbStates,
    errorFingerprints,
    severityDistribution,
    eventLag: { currentMs: 0, avgMs: 0, maxMs: 0, trend: 'stable' },
    graphLag: { currentMs: 0, avgMs: 0, maxMs: 0, trend: 'stable' },
    adapterReadiness: [],
    environmentValidation: [],
  };
}

export function useDiagnosticsData() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isLocalMocked()) {
      setHealth(getMockSystemHealth());
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
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
        setIsLoading(false);
      });
  }, []);

  const suppressError = useCallback((fingerprint: string) => {
    if (!health) return;

    if (isLocalMocked()) {
      setHealth({
        ...health,
        errorFingerprints: health.errorFingerprints.map(ef =>
          ef.fingerprint === fingerprint ? { ...ef, suppressed: true } : ef
        ),
      });
      return;
    }

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
