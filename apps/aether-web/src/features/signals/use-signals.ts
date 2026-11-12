import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import type { InboxNotification } from '@aether-app/features/notifications/use-inbox';

/**
 * Signals reads — thin, tenant-scoped wrappers over endpoints that already
 * exist in `api`:
 *   - the tenant in-app inbox (`/v1/notifications/inbox`) is the signal feed;
 *     archiving a row is how a signal is acknowledged (persisted server-side).
 *   - alert rules (`/v1/notifications/alerts`) are listed and created
 *     (`POST /v1/notifications/alerts`, body `{ name, condition, channels,
 *     recipients }`); the backend has no update / toggle / delete for a rule.
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
  /** Only present when the stored rule carries one; the create body has no severity. */
  readonly severity: string | null;
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
      severity: typeof r['severity'] === 'string' && r['severity'].trim() ? r['severity'] : null,
    }));
}

export function alertRulesKey(tenantId: string): string {
  return `signals:${tenantId}:rules`;
}

export function useAlertRules(tenantId: string) {
  return useQuery<AlertRule[]>({
    key: alertRulesKey(tenantId),
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

// ── Create rule ───────────────────────────────────────────────────────────────

/** Channels the notification service delivers on. The backend stores any string; these are the ones the app offers. */
export const RULE_CHANNELS = ['in_app', 'email', 'slack', 'webhook'] as const;

export interface AlertRuleDraft {
  readonly name: string;
  readonly condition: string;
  readonly channels: readonly string[];
  /** Comma or newline separated. */
  readonly recipients: string;
}

export interface AlertRuleBody {
  readonly name: string;
  readonly condition: string;
  readonly channels: string[];
  readonly recipients: string[];
}

export type AlertRuleDraftErrors = Partial<Record<'name' | 'condition' | 'channels', string>>;

export function splitList(value: string): string[] {
  return Array.from(new Set(value.split(/[,\n]/).map(v => v.trim()).filter(Boolean)));
}

/** Mirrors `_AlertRule` (name, condition and at least one channel are required). */
export function validateAlertRuleDraft(draft: AlertRuleDraft): { errors: AlertRuleDraftErrors; body: AlertRuleBody | null } {
  const errors: AlertRuleDraftErrors = {};
  const name = draft.name.trim();
  const condition = draft.condition.trim();
  if (!name) errors.name = 'Give the rule a name.';
  if (!condition) errors.condition = 'Describe the condition that raises a signal.';
  if (draft.channels.length === 0) errors.channels = 'Pick at least one channel.';
  if (Object.keys(errors).length > 0) return { errors, body: null };
  return { errors, body: { name, condition, channels: [...draft.channels], recipients: splitList(draft.recipients) } };
}

export function useCreateAlertRule(tenantId: string) {
  return useMutation<AlertRuleBody, unknown>({
    mutationFn: body => api.notifications.createAlert({ ...body }),
    invalidateKeys: [alertRulesKey(tenantId)],
  });
}
