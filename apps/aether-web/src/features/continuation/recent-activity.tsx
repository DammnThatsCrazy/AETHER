/**
 * "Recent mobile activity / resume" panel (M5c).
 *
 * Read-only surface listing recent continuations (for resume) plus the client
 * sync change feed with readable labels for the ten change types. Embedded in an
 * existing page (the notification center). Renders nothing and fires no requests
 * while its owning feature flag(s) are OFF (D8).
 */
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
  StatusIndicator,
  TerminalSeparator,
  formatDate,
  useTimeContext,
  type TimeContext,
} from '@aether/ui';
import type { SyncChangeType } from '@aether/shared';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';
import { useClientSync } from './use-client-sync';
import { useRecentContinuations } from './use-continuations';

/** Readable labels for the exactly-ten client-sync change types. */
export const SYNC_CHANGE_TYPE_LABELS: Record<SyncChangeType, string> = {
  notification_changed: 'Notification updated',
  continuation_changed: 'Continuation updated',
  saved_view_changed: 'Saved view updated',
  conversation_changed: 'Conversation updated',
  watchlist_changed: 'Watchlist updated',
  incident_changed: 'Incident updated',
  command_receipt_changed: 'Command receipt updated',
  preference_changed: 'Preferences updated',
  session_revoked: 'Session revoked',
  installation_revoked: 'Installation revoked',
};

export function syncChangeTypeLabel(changeType: string): string {
  return SYNC_CHANGE_TYPE_LABELS[changeType as SyncChangeType] ?? changeType.replace(/_/g, ' ');
}

function formatWhen(iso: string | null | undefined, ctx: TimeContext): string {
  if (!iso) return '—';
  return formatDate(iso, ctx);
}

function RecentContinuationsSection() {
  const timeCtx = useTimeContext();
  const { data, isLoading, error, refetch } = useRecentContinuations();
  const continuations = data?.continuations ?? [];

  return (
    <div>
      <p className="mb-2 text-xs font-mono text-text-muted">Recent activity</p>
      {isLoading && <LoadingState lines={3} />}
      {error && <ErrorState message="Failed to load recent activity" onRetry={refetch} />}
      {!isLoading && !error && continuations.length === 0 && (
        <EmptyState
          title="No continuations yet"
          description="Continue-on-phone handoffs will appear here."
        />
      )}
      {!isLoading && !error && continuations.length > 0 && (
        <ul className="space-y-1.5">
          {continuations.map(c => (
            <li
              key={c.id}
              className="rounded border border-border-subtle bg-surface-raised/50 px-3 py-2 text-xs"
            >
              <div className="flex items-center gap-2">
                <span className="font-medium text-text-primary">{c.summary.title}</span>
                <Badge variant="default" size="sm">{c.surface}</Badge>
                <span className="ml-auto whitespace-nowrap font-mono text-text-muted">
                  {formatWhen(c.updated_at, timeCtx)}
                </span>
              </div>
              {c.summary.subtitle && (
                <p className="mt-0.5 text-[10px] text-text-muted">{c.summary.subtitle}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ClientSyncSection() {
  const timeCtx = useTimeContext();
  const { events, reset, has_more: hasMore, isLoading, error, reload, loadMore } = useClientSync();

  return (
    <div>
      <TerminalSeparator label="sync feed" className="my-3" />
      <p className="mb-2 text-xs font-mono text-text-muted">Device sync feed</p>
      {isLoading && <LoadingState lines={3} />}
      {error && <ErrorState message="Failed to load sync events" onRetry={reload} />}
      {!isLoading && !error && events.length === 0 && (
        <EmptyState
          title="No sync events"
          description="Changes across your devices will appear here."
        />
      )}
      {!isLoading && !error && events.length > 0 && (
        <>
          {reset && (
            <p className="mb-2 font-mono text-[10px] text-warning">
              Feed was reset — showing the latest slice only.
            </p>
          )}
          <ul className="space-y-1.5">
            {events.map(ev => (
              <li
                key={ev.id}
                className="rounded border border-border-subtle bg-surface-raised/50 px-3 py-2 text-xs"
              >
                <div className="flex items-center gap-2">
                  <StatusIndicator status="healthy" className="shrink-0" label="synced" />
                  <span className="font-medium text-text-primary">{syncChangeTypeLabel(ev.change_type)}</span>
                  <span className="ml-auto whitespace-nowrap font-mono text-[10px] text-text-muted">
                    {formatWhen(ev.created_at, timeCtx)}
                  </span>
                </div>
                <p className="mt-0.5 font-mono text-[10px] text-text-muted">
                  {ev.resource_kind ?? 'resource'} · {ev.resource_id ?? '—'} · rev {ev.revision ?? '—'}
                </p>
              </li>
            ))}
          </ul>
          {hasMore && (
            <button
              type="button"
              onClick={loadMore}
              className="mt-2 h-7 rounded border border-border-subtle bg-surface-raised px-3 text-[11px] text-text-secondary hover:text-text-primary"
            >
              Load more
            </button>
          )}
        </>
      )}
    </div>
  );
}

export function RecentActivity() {
  const continuationsEnabled = isFeatureEnabled('enableContinuations');
  const syncEnabled = isFeatureEnabled('enableClientSyncConsumption');
  if (!continuationsEnabled && !syncEnabled) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-mono text-text-muted">Recent mobile activity</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {continuationsEnabled && <RecentContinuationsSection />}
        {syncEnabled && <ClientSyncSection />}
      </CardContent>
    </Card>
  );
}
