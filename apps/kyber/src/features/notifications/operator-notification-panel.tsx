import { useState, type FC } from 'react';
import { useIntelligenceNotifications, type IntelligenceNotification } from './use-intelligence-notifications';
import { OperatorActionBar } from './operator-action-bar';
import { NotificationLifecycleBadge } from './notification-lifecycle-badge';
import { AuditTrailTimeline, type AuditEntry } from './audit-trail-timeline';

interface Props {
  readonly tenantId: string;
  readonly canApprove: boolean;
  readonly canSuppress: boolean;
  readonly canEscalate: boolean;
}

function SlaCountdown({ expiresAt }: { readonly expiresAt: string | undefined }) {
  if (!expiresAt) return null;
  const remaining = new Date(expiresAt).getTime() - Date.now();
  if (remaining <= 0) return <span className="text-xs text-red-400 font-medium">SLA exceeded</span>;

  const minutes = Math.floor(remaining / 60_000);
  const hours = Math.floor(minutes / 60);
  const label = hours > 0 ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
  const urgent = minutes < 10;

  return (
    <span className={`text-xs font-medium ${urgent ? 'text-red-400' : 'text-yellow-400'}`}>
      SLA: {label} remaining
    </span>
  );
}

const SEVERITY_BADGE_COLORS: Record<string, string> = {
  P0:   'bg-red-500/20 text-red-300 border-red-500/30',
  P1:   'bg-orange-500/20 text-orange-300 border-orange-500/30',
  P2:   'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  P3:   'bg-blue-500/20 text-blue-300 border-blue-500/30',
  info: 'bg-zinc-500/20 text-zinc-300 border-zinc-500/30',
};
const SEVERITY_BADGE_DEFAULT = 'bg-zinc-500/20 text-zinc-300 border-zinc-500/30';

function SeverityBadge({ severity }: { readonly severity: string }) {
  const colorClass = SEVERITY_BADGE_COLORS[severity] ?? SEVERITY_BADGE_DEFAULT;
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-bold border ${colorClass}`}>
      {severity}
    </span>
  );
}

interface NotificationCardProps {
  readonly notification: IntelligenceNotification;
  readonly canApprove: boolean;
  readonly canSuppress: boolean;
  readonly canEscalate: boolean;
  readonly onApprove: (id: string, annotation?: string) => Promise<void>;
  readonly onSuppress: (id: string, annotation?: string) => Promise<void>;
  readonly onEscalate: (id: string, annotation?: string) => Promise<void>;
  readonly onAnnotate: (id: string, annotation: string) => Promise<void>;
}

const NotificationCard: FC<NotificationCardProps> = ({
  notification: n,
  canApprove,
  canSuppress,
  canEscalate,
  onApprove,
  onSuppress,
  onEscalate,
  onAnnotate,
}) => {
  const [expanded, setExpanded] = useState(false);

  return (
    <article className="rounded-lg border border-zinc-700 bg-zinc-800/60 overflow-hidden">
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2 flex-wrap min-w-0">
            <SeverityBadge severity={n.severity} />
            <NotificationLifecycleBadge state={n.lifecycle_state} />
            <span className="text-sm font-semibold text-zinc-100 truncate">{n.title}</span>
          </div>
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-xs text-zinc-500 hover:text-zinc-300 shrink-0"
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
        </div>

        <div className="mt-2 flex items-center gap-3 flex-wrap">
          <SlaCountdown expiresAt={n.expires_at} />
          <span className="text-xs text-zinc-500 font-mono">{n.source_topic}</span>
          <a href={n.deep_link} className="text-xs text-blue-400 hover:underline">
            View in console →
          </a>
        </div>

        {expanded && (
          <dl className="mt-3 grid grid-cols-1 gap-y-2 text-xs">
            {([
              { label: 'What',   value: n.what },
              { label: 'Why',    value: n.why },
              { label: 'Impact', value: n.impact },
              ...(n.recommended_action !== undefined
                ? [{ label: 'Action', value: n.recommended_action }]
                : []),
            ] as { label: string; value: string }[]).map(({ label, value }) => (
              <div key={label} className="flex gap-2">
                <dt className="text-zinc-500 w-14 shrink-0">{label}:</dt>
                <dd className="text-zinc-300">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>

      <div className="border-t border-zinc-700 px-4 py-3">
        <OperatorActionBar
          notificationId={n.id}
          currentState={n.lifecycle_state}
          canApprove={canApprove}
          canSuppress={canSuppress}
          canEscalate={canEscalate}
          onApprove={onApprove}
          onSuppress={onSuppress}
          onEscalate={onEscalate}
          onAnnotate={onAnnotate}
        />
      </div>

      {expanded && n.audit_trail.length > 0 && (
        <div className="border-t border-zinc-700 px-4 py-3">
          <p className="text-xs font-semibold text-zinc-400 mb-3">Audit Trail</p>
          <AuditTrailTimeline trail={n.audit_trail as unknown as readonly AuditEntry[]} />
        </div>
      )}
    </article>
  );
};

export const OperatorNotificationPanel: FC<Props> = ({
  tenantId,
  canApprove,
  canSuppress,
  canEscalate,
}) => {
  const { pending, loading, error, approve, suppress, escalate, annotate, refresh } =
    useIntelligenceNotifications(tenantId);

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-zinc-200">Operator Review Queue</h2>
          {pending.length > 0 && (
            <span className="px-2 py-0.5 text-xs rounded-full bg-orange-500/20 text-orange-300 border border-orange-500/30 font-bold">
              {pending.length}
            </span>
          )}
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          className="text-xs text-zinc-500 hover:text-zinc-300 disabled:opacity-40"
        >
          {loading ? 'Loading…' : '↻ Refresh'}
        </button>
      </div>

      {error && (
        <div className="rounded border border-red-800 bg-red-900/20 px-4 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {!loading && !error && pending.length === 0 && (
        <div className="rounded border border-zinc-700 bg-zinc-800/40 px-4 py-8 text-center text-sm text-zinc-500">
          No notifications pending operator review.
        </div>
      )}

      {pending.map(n => (
        <NotificationCard
          key={n.id}
          notification={n}
          canApprove={canApprove}
          canSuppress={canSuppress}
          canEscalate={canEscalate}
          onApprove={approve}
          onSuppress={suppress}
          onEscalate={escalate}
          onAnnotate={annotate}
        />
      ))}
    </section>
  );
};
