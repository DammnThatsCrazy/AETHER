import type { Severity } from './common';

export type LiveEventType =
  | 'analytics'
  | 'graph-mutation'
  | 'agent-lifecycle'
  | 'controller'
  | 'onboarding'
  | 'support'
  | 'stuck-loop'
  | 'anomaly'
  | 'alert'
  | 'system';

export interface LiveEvent {
  readonly id: string;
  readonly type: LiveEventType;
  readonly timestamp: string;
  readonly severity: Severity;
  readonly title: string;
  readonly description: string;
  readonly source: string;
  readonly controller?: string | undefined;
  readonly entityId?: string | undefined;
  readonly entityType?: string | undefined;
  readonly traceId?: string | undefined;
  readonly pinned: boolean;
  readonly metadata: Record<string, unknown>;
}

export interface EventFilter {
  readonly types?: readonly LiveEventType[] | undefined;
  readonly severities?: readonly Severity[] | undefined;
  readonly controllers?: readonly string[] | undefined;
  readonly search?: string | undefined;
  readonly pinnedOnly?: boolean | undefined;
}

export interface EventStreamState {
  readonly events: readonly LiveEvent[];
  readonly isConnected: boolean;
  readonly isPaused: boolean;
  readonly filter: EventFilter;
  readonly pinnedEvents: readonly LiveEvent[];
}
