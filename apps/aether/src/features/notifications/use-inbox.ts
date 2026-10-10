import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export type InboxNotification = {
  id: string;
  tenant_id: string;
  category: string;
  severity: string;
  title: string;
  body: string | null;
  link: string | null;
  correlation_id: string | null;
  dedupe_key: string | null;
  read: boolean;
  read_at: string | null;
  archived: boolean;
  archived_at: string | null;
  count: number;
  created_at: string;
};

export interface InboxQueryParams {
  unread?: boolean;
  include_archived?: boolean;
  limit?: number;
  offset?: number;
}

export function useInbox(params: InboxQueryParams = {}) {
  const { unread = false, include_archived = false, limit = 100, offset = 0 } = params;
  return useQuery<InboxNotification[]>({
    key: `inbox-${unread}-${include_archived}-${limit}-${offset}`,
    fetcher: () => api.inbox.list({ unread, include_archived, limit, offset }) as Promise<InboxNotification[]>,
  });
}

export function useInboxUnreadCount() {
  return useQuery<{ unread: number }>({
    key: 'inbox-unread-count',
    fetcher: () => api.inbox.unreadCount(),
  });
}

export function useMarkInboxRead() {
  return useMutation<{ id: string }, unknown>({
    mutationFn: ({ id }) => api.inbox.markRead(id),
    invalidateKeys: ['inbox-unread-count'],
  });
}

export function useMarkAllInboxRead() {
  return useMutation<void, unknown>({
    mutationFn: () => api.inbox.markAllRead(),
    invalidateKeys: ['inbox-unread-count'],
  });
}

export function useArchiveInbox() {
  return useMutation<{ id: string }, unknown>({
    mutationFn: ({ id }) => api.inbox.archive(id),
    invalidateKeys: ['inbox-unread-count'],
  });
}
