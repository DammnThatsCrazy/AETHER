import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  EmptyState,
  ErrorState,
  GlyphIcon,
  LoadingState,
  Select,
  SeverityBadge,
  StatusIndicator,
  TerminalSeparator,
  Toggle,
  formatDate,
  useTimeContext,
  useToast,
  type TimeContext,
} from '@aether/ui';
import { queryCache } from '@aether/ui';
import {
  useInbox,
  useInboxUnreadCount,
  useMarkAllInboxRead,
  useMarkInboxRead,
  useArchiveInbox,
  type InboxNotification,
} from '@aether-app/features/notifications/use-inbox';
import { RecentActivity } from '@aether-app/features/continuation';

const SEVERITY_OPTIONS = ['all', 'P0', 'P1', 'P2', 'P3', 'info'] as const;
type SeverityFilter = typeof SEVERITY_OPTIONS[number];

const CATEGORY_LABELS: Record<string, string> = {
  alert: 'Alert',
  'action-request': 'Action request',
  operational: 'Operational',
  digest: 'Digest',
};

function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category.replace(/-/g, ' ');
}

function formatWhen(iso: string | null | undefined, ctx: TimeContext): string {
  if (!iso) return '—';
  return formatDate(iso, ctx);
}

interface NotificationRowProps {
  readonly notification: InboxNotification;
  readonly busy: string | null;
  readonly onMarkRead: (id: string) => void;
  readonly onArchive: (id: string) => void;
}

function NotificationRow({ notification, busy, onMarkRead, onArchive }: NotificationRowProps) {
  const timeCtx = useTimeContext();
  const isBusy = busy === notification.id;
  const severity = notification.severity ?? 'info';

  return (
    <div
      className={`rounded border px-3 py-2.5 text-xs transition-colors ${
        notification.read
          ? 'border-border-default bg-surface-raised/50'
          : 'border-border-default bg-surface-raised'
      }`}
    >
      <div className="flex items-start gap-2">
        <StatusIndicator
          status={notification.read ? 'healthy' : 'degraded'}
          className="mt-1.5 shrink-0"
          label={notification.read ? 'Read' : 'Unread'}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <SeverityBadge severity={severity as 'P0' | 'P1' | 'P2' | 'P3' | 'info'} />
            <Badge variant="default" size="sm">{categoryLabel(notification.category)}</Badge>
            {notification.count > 1 && (
              <Badge variant="warning" size="sm" className="font-mono">
                ×{notification.count}
              </Badge>
            )}
            <span className="text-text-muted font-mono ml-auto whitespace-nowrap">
              {formatWhen(notification.created_at, timeCtx)}
            </span>
          </div>
          <p className={`mt-1 font-medium ${notification.read ? 'text-text-secondary' : 'text-text-primary'}`}>
            {notification.title}
          </p>
          {notification.body && (
            <p className="mt-0.5 text-text-muted line-clamp-2 whitespace-pre-wrap break-words">{notification.body}</p>
          )}
          {notification.link && (
            <a
              href={notification.link}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent underline mt-1 inline-block"
            >
              Open →
            </a>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {!notification.read && (
            <Button variant="ghost" size="sm" disabled={isBusy} onClick={() => onMarkRead(notification.id)}>
              {isBusy ? '…' : 'Mark read'}
            </Button>
          )}
          {!notification.archived && (
            <Button
              variant="ghost"
              size="sm"
              className="text-danger hover:bg-danger/10"
              disabled={isBusy}
              onClick={() => onArchive(notification.id)}
            >
              {isBusy ? '…' : <GlyphIcon glyph="[x]" />}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export function NotificationCenterPage() {
  const { toast } = useToast();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [busyId, setBusyId] = useState<string | null>(null);

  const { data: notifications, isLoading, error, refetch } = useInbox({
    unread: unreadOnly,
    include_archived: showArchived,
    limit: 200,
  });
  const { data: unreadData } = useInboxUnreadCount();
  const { mutate: markRead } = useMarkInboxRead();
  const { mutate: markAllRead, isLoading: markingAll } = useMarkAllInboxRead();
  const { mutate: archive } = useArchiveInbox();

  const unread = unreadData?.unread ?? 0;
  const items = (notifications ?? []).filter(
    n => severityFilter === 'all' || n.severity === severityFilter,
  );

  function refreshInbox() {
    queryCache.invalidatePrefix('inbox-');
    queryCache.invalidate('inbox-unread-count');
    refetch();
  }

  async function handleMarkRead(id: string) {
    setBusyId(id);
    const result = await markRead({ id });
    setBusyId(null);
    if (result !== null) {
      refreshInbox();
    } else {
      toast.error('Failed to mark read');
    }
  }

  async function handleArchive(id: string) {
    setBusyId(id);
    const result = await archive({ id });
    setBusyId(null);
    if (result !== null) {
      refreshInbox();
      toast.success('Archived');
    } else {
      toast.error('Archive failed');
    }
  }

  async function handleMarkAllRead() {
    const result = await markAllRead(undefined);
    if (result !== null) {
      refreshInbox();
      toast.success('All notifications marked read');
    } else {
      toast.error('Mark-all-read failed');
    }
  }

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <span className="text-sm font-mono text-text-muted">Notification Center</span>
          <Badge variant={unread > 0 ? 'accent' : 'default'} size="sm" className="font-mono">
            {unread} unread
          </Badge>
        </div>
        <Button variant="ghost" size="sm" disabled={unread === 0 || markingAll} onClick={() => { void handleMarkAllRead(); }}>
          {markingAll ? '[···]' : 'Mark all read'}
        </Button>
      </div>

      {/* Filters */}
      <Card className="mb-4">
        <CardContent className="flex items-center gap-6 flex-wrap py-3">
          <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
            <Toggle checked={unreadOnly} onChange={() => setUnreadOnly(v => !v)} size="sm" />
            Unread only
          </label>
          <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
            <Toggle checked={showArchived} onChange={() => setShowArchived(v => !v)} size="sm" />
            Show archived
          </label>
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-secondary">Severity</span>
            <Select
              value={severityFilter}
              onChange={value => setSeverityFilter(value as SeverityFilter)}
              options={SEVERITY_OPTIONS.map(s => ({ value: s, label: s === 'all' ? 'All' : s }))}
              className="w-28"
            />
          </div>
        </CardContent>
      </Card>

      {isLoading && <LoadingState lines={5} className="space-y-2" />}
      {error && <ErrorState message="Failed to load notifications" onRetry={refetch} />}
      {!isLoading && !error && items.length === 0 && (
        <EmptyState
          title={unreadOnly ? 'No unread notifications' : 'No notifications'}
          description={showArchived ? 'No notifications match the current filters.' : 'Nothing in your inbox yet — alerts and updates will appear here.'}
        />
      )}
      {!isLoading && !error && items.length > 0 && (
        <div className="space-y-2">
          {items.map(n => (
            <NotificationRow
              key={n.id}
              notification={n}
              busy={busyId}
              onMarkRead={(id) => { void handleMarkRead(id); }}
              onArchive={(id) => { void handleArchive(id); }}
            />
          ))}
        </div>
      )}

      <TerminalSeparator label="inbox" className="my-6" />
      <p className="text-[10px] text-text-muted font-mono">
        In-app notifications are tenant-scoped. Reads and archives are idempotent; archived
        notifications drop out of the unread count.
      </p>

      <RecentActivity />
    </div>
  );
}
