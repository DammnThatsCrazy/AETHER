import { useState, useEffect, useCallback, useRef } from 'react';
import { useNotifications } from './notification-context';
import { dispatchNotification } from './notification-dispatcher';
import type { LifecycleState } from './notification-lifecycle-badge';

export interface IntelligenceNotification {
  readonly id: string;
  readonly tenant_id: string;
  readonly lifecycle_state: LifecycleState;
  readonly severity: string;
  readonly notification_class: string;
  readonly title: string;
  readonly body: string;
  readonly what: string;
  readonly why: string;
  readonly impact: string;
  readonly recommended_action?: string;
  readonly source_topic: string;
  readonly deep_link: string;
  readonly detected_at: string;
  readonly expires_at?: string;
  readonly audit_trail: readonly Record<string, unknown>[];
  readonly operator_context?: Record<string, unknown>;
}

interface UseIntelligenceNotificationsResult {
  readonly pending: readonly IntelligenceNotification[];
  readonly all: readonly IntelligenceNotification[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly approve: (id: string, annotation?: string) => Promise<void>;
  readonly suppress: (id: string, annotation?: string) => Promise<void>;
  readonly escalate: (id: string, annotation?: string) => Promise<void>;
  readonly annotate: (id: string, annotation: string) => Promise<void>;
  readonly refresh: () => void;
}

const POLL_INTERVAL_MS = 10_000;

async function apiPatch(path: string, body: Record<string, unknown>): Promise<void> {
  const res = await fetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`PATCH ${path} failed: ${res.status} ${text}`);
  }
}

export function useIntelligenceNotifications(tenantId: string): UseIntelligenceNotificationsResult {
  const [all, setAll] = useState<IntelligenceNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { addNotification } = useNotifications();
  const seenIds = useRef<Set<string>>(new Set());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchNotifications = useCallback(async () => {
    if (!tenantId) return;
    try {
      setLoading(true);
      const res = await fetch(
        `/v1/notifications/intelligence?tenant_id=${encodeURIComponent(tenantId)}&limit=100`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json() as { data?: IntelligenceNotification[] };
      const notifications = json.data ?? [];
      setAll(notifications);
      setError(null);

      // Surface new operator_review notifications into the in-app center
      for (const n of notifications) {
        if (n.lifecycle_state === 'operator_review' && !seenIds.current.has(n.id)) {
          seenIds.current.add(n.id);
          addNotification(dispatchNotification({
            title: n.title,
            body: n.body,
            severity: n.severity as Parameters<typeof dispatchNotification>[0]['severity'],
            class: n.notification_class as Parameters<typeof dispatchNotification>[0]['class'],
            what: n.what,
            why: n.why,
            impact: n.impact,
            ...(n.recommended_action !== undefined ? { recommendedAction: n.recommended_action } : {}),
            deepLink: n.deep_link,
          }));
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [tenantId, addNotification]);

  const refresh = useCallback(() => { void fetchNotifications(); }, [fetchNotifications]);

  useEffect(() => {
    void fetchNotifications();
    intervalRef.current = setInterval(() => { void fetchNotifications(); }, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchNotifications]);

  const approve = useCallback(async (id: string, annotation?: string) => {
    await apiPatch(`/v1/notifications/intelligence/${id}/approve`, { annotation });
    void fetchNotifications();
  }, [fetchNotifications]);

  const suppress = useCallback(async (id: string, annotation?: string) => {
    await apiPatch(`/v1/notifications/intelligence/${id}/suppress`, { annotation });
    void fetchNotifications();
  }, [fetchNotifications]);

  const escalate = useCallback(async (id: string, annotation?: string) => {
    await apiPatch(`/v1/notifications/intelligence/${id}/escalate`, { annotation });
    void fetchNotifications();
  }, [fetchNotifications]);

  const annotate = useCallback(async (id: string, annotation: string) => {
    await apiPatch(`/v1/notifications/intelligence/${id}/annotate`, { annotation });
    void fetchNotifications();
  }, [fetchNotifications]);

  const pending = all.filter(n => n.lifecycle_state === 'operator_review');

  return { pending, all, loading, error, approve, suppress, escalate, annotate, refresh };
}
