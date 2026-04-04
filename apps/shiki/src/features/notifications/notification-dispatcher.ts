import type { ShikiNotification, Severity, NotificationClass } from '@shiki/types';

let idCounter = 0;

interface DispatchOptions {
  readonly title: string;
  readonly body: string;
  readonly severity: Severity;
  readonly class: NotificationClass;
  readonly controller?: string;
  readonly entityId?: string;
  readonly entityType?: string;
  readonly what: string;
  readonly why: string;
  readonly impact: string;
  readonly recommendedAction?: string;
  readonly reversible?: boolean;
  readonly traceRef?: string;
  readonly deepLink?: string;
}

export function dispatchNotification(opts: DispatchOptions): ShikiNotification {
  const id = `notif-${Date.now()}-${++idCounter}`;
  return {
    id,
    title: opts.title,
    body: opts.body,
    severity: opts.severity,
    class: opts.class,
    channels: ['in-app'],
    timestamp: new Date().toISOString(),
    read: false,
    dismissed: false,
    entityId: opts.entityId,
    entityType: opts.entityType,
    controller: opts.controller,
    deepLink: opts.deepLink ?? `/mission`,
    what: opts.what,
    why: opts.why,
    impact: opts.impact,
    recommendedAction: opts.recommendedAction,
    reversible: opts.reversible,
    traceRef: opts.traceRef,
    dedupeKey: `${opts.controller ?? 'system'}-${opts.what}-${opts.entityId ?? 'global'}`,
  };
}
