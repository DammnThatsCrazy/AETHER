import type { Severity } from './common';

export type NotificationChannel = 'in-app' | 'browser' | 'slack' | 'email' | 'mobile-push' | 'pagerduty' | 'opsgenie' | 'webhook';

export type NotificationClass = 'alert' | 'action-request' | 'operational' | 'digest';

export interface ShikiNotification {
  readonly id: string;
  readonly title: string;
  readonly body: string;
  readonly severity: Severity;
  readonly class: NotificationClass;
  readonly channels: readonly NotificationChannel[];
  readonly timestamp: string;
  readonly read: boolean;
  readonly dismissed: boolean;
  readonly entityId?: string | undefined;
  readonly entityType?: string | undefined;
  readonly controller?: string | undefined;
  readonly deepLink: string;
  readonly what: string;
  readonly why: string;
  readonly impact: string;
  readonly recommendedAction?: string | undefined;
  readonly reversible?: boolean | undefined;
  readonly traceRef?: string | undefined;
  readonly dedupeKey: string;
}

export interface NotificationPreferences {
  readonly channels: Record<NotificationChannel, boolean>;
  readonly severityRouting: Record<Severity, readonly NotificationChannel[]>;
  readonly digestFrequency: 'hourly' | 'daily' | 'weekly';
  readonly quietHours?: { readonly start: string; readonly end: string } | undefined;
}

export interface NotificationState {
  readonly notifications: readonly ShikiNotification[];
  readonly unreadCount: number;
  readonly isConnected: boolean;
}
