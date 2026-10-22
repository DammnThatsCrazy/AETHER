import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import type { InboxNotification } from '@aether-app/features/notifications/use-inbox';

/**
 * Signals reads — thin, tenant-scoped wrappers over endpoints that already
 * exist in `api`:
 *   - the tenant in-app inbox (`/v1/notifications/inbox`) is the signal feed;
 *     archiving a row is how a signal is acknowledged (persisted server-side).
 *   - alert rules (`/v1/notifications/alerts`) are listed read-only: the
 *     backend has no update / toggle / delete for a rule.
 */

/** The feed reads up to the backend's page maximum, archived rows included, so History shares one read. */
export const SIGNAL_FEED_LIMIT = 200;

export function signalFeedKey(tenantId: string): string {
  return `signals:${tenantId}:feed`;
}

export function useSignalFeed(tenantId: string) {
  return useQuery<InboxNotification[]>({
    key: signalFeedKey(tenantId),
    fetcher: () => api.inbox.list({ include_archived: true, limit: SIGNAL_FEED_LIMIT }) as Promise<InboxNotification[]>,
    staleTime: 30_000,
    enabled: Boolean(tenantId),
  });
}

export interface AlertRule {
  readonly id: string;
  readonly name: string;
  readonly condition: string | null;
  readonly channels: readonly string[];
  readonly recipients: readonly string[];
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string' && v.trim() !== '') : [];
}

/** Normalise the legacy alert-rule list (an array, or `{ items }`) into typed rows. */
export function normaliseAlertRules(raw: unknown): AlertRule[] {
  const list = Array.isArray(raw)
    ? raw
    : raw && typeof raw === 'object' && Array.isArray((raw as { items?: unknown }).items)
      ? ((raw as { items: unknown[] }).items)
      : [];
  return list
    .filter((r): r is Record<string, unknown> => Boolean(r) && typeof r === 'object')
    .map((r, index) => ({
      id: typeof r['id'] === 'string' ? r['id'] : `rule-${index}`,
      name: typeof r['name'] === 'string' && r['name'].trim() ? r['name'] : 'Unnamed rule',
      condition: typeof r['condition'] === 'string' && r['condition'].trim() ? r['condition'] : null,
      channels: strings(r['channels']),
      recipients: strings(r['recipients']),
    }));
}

export function useAlertRules(tenantId: string) {
  return useQuery<AlertRule[]>({
    key: `signals:${tenantId}:rules`,
    fetcher: () => api.notifications.alerts(tenantId).then(normaliseAlertRules),
    staleTime: 60_000,
    enabled: Boolean(tenantId),
  });
}

export function useAcknowledgeSignal() {
  return useMutation<{ id: string }, unknown>({
    mutationFn: ({ id }) => api.inbox.archive(id),
    invalidateKeys: ['inbox-unread-count'],
  });
}

export function useMarkSignalRead() {
  return useMutation<{ id: string }, unknown>({
    mutationFn: ({ id }) => api.inbox.markRead(id),
    invalidateKeys: ['inbox-unread-count'],
  });
}
