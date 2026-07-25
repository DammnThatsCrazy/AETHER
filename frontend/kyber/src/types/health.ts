import type { HealthStatus, Severity } from './common';

export interface SystemHealth {
  readonly overall: HealthStatus;
  readonly dependencies: readonly DependencyHealth[];
  readonly circuitBreakers: readonly CircuitBreakerState[];
  readonly errorFingerprints: readonly ErrorFingerprint[];
  readonly severityDistribution: Record<Severity, number>;
  readonly eventLag: LagMetric;
  readonly graphLag: LagMetric;
  readonly adapterReadiness: readonly AdapterReadiness[];
  readonly environmentValidation: readonly EnvValidation[];
}

export interface DependencyHealth {
  readonly name: string;
  readonly type: 'database' | 'cache' | 'queue' | 'api' | 'graph' | 'storage' | 'analytics';
  readonly status: HealthStatus;
  readonly latencyMs: number | null;
  readonly lastError?: string | undefined;
}

export interface CircuitBreakerState {
  readonly name: string;
  readonly state: 'closed' | 'open' | 'half-open' | 'unknown';
  readonly failureCount: number;
  readonly lastFailure?: string | undefined;
  readonly nextRetry?: string | undefined;
}

export interface ErrorFingerprint {
  readonly fingerprint: string;
  readonly message: string;
  readonly count: number;
  readonly firstSeen: string;
  readonly lastSeen: string;
  readonly severity: Severity;
  readonly suppressed: boolean;
}

export interface LagMetric {
  readonly currentMs: number | null;
  readonly avgMs: number | null;
  readonly maxMs: number | null;
  readonly trend: 'improving' | 'degrading' | 'stable' | 'unknown';
}

export interface AdapterReadiness {
  readonly name: string;
  readonly type: 'rest' | 'graphql' | 'websocket';
  readonly ready: boolean;
  readonly lastCheck: string;
  readonly error?: string | undefined;
}

export interface EnvValidation {
  readonly variable: string;
  readonly required: boolean;
  readonly present: boolean;
  readonly valid: boolean;
  readonly message?: string | undefined;
}
