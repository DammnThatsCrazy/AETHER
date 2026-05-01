export type Environment = 'local-mocked' | 'local-live' | 'staging' | 'production';
export type RuntimeMode = 'mocked' | 'live';

export type Severity = 'P0' | 'P1' | 'P2' | 'P3' | 'info';

export type ActionClass = 0 | 1 | 2 | 3 | 4 | 5;

export type AutomationPosture = 'conservative' | 'balanced' | 'aggressive';

export type TimeWindow = '1h' | '6h' | '24h' | '7d' | '30d' | 'custom';

export interface TimeRange {
  readonly start: Date;
  readonly end: Date;
}

export interface PaginatedResponse<T> {
  readonly data: readonly T[];
  readonly total: number;
  readonly offset: number;
  readonly limit: number;
  readonly hasMore: boolean;
}

export interface ApiError {
  readonly code: string;
  readonly message: string;
  readonly details?: Record<string, unknown> | undefined;
  readonly correlationId?: string | undefined;
}

export interface HealthStatus {
  readonly status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  readonly message?: string | undefined;
  readonly lastChecked: string;
}

export interface ThroughputMetrics {
  readonly eventsPerSecond: number;
  readonly eventsPerMinute: number;
  readonly totalLast1h: number;
  readonly totalLast24h: number;
  readonly trend: 'up' | 'down' | 'stable';
}

export interface ActionAttribution {
  readonly userId: string;
  readonly displayName: string;
  readonly email: string;
  readonly role: string;
  readonly timestamp: string;
  readonly environment: Environment;
  readonly reason: string;
  readonly correlationId: string;
  readonly revertId?: string | undefined;
}

export interface KeyChange {
  readonly id: string;
  readonly description: string;
  readonly severity: Severity;
  readonly timestamp: string;
  readonly controller: string;
  readonly entityId?: string | undefined;
  readonly entityType?: string | undefined;
}

export interface RecommendedAction {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly actionClass: ActionClass;
  readonly confidence: number;
  readonly reversible: boolean;
  readonly controller: string;
  readonly rationale: string;
  readonly entityId?: string | undefined;
}
