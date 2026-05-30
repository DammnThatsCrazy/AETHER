import type { FC } from 'react';

export interface AuditEntry {
  readonly state: string;
  readonly actor?: { readonly user_id?: string; readonly role?: string };
  readonly timestamp: string;
  readonly metadata?: Record<string, unknown>;
}

interface Props {
  readonly trail: readonly AuditEntry[];
  readonly className?: string;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'short',
      timeStyle: 'medium',
    });
  } catch {
    return iso;
  }
}

const STATE_DOT: Record<string, string> = {
  detected:        'bg-zinc-400',
  validated:       'bg-blue-400',
  queued:          'bg-yellow-400',
  operator_review: 'bg-orange-400',
  approved:        'bg-green-400',
  propagated:      'bg-teal-400',
  suppressed:      'bg-zinc-500',
  expired:         'bg-red-400',
  annotated:       'bg-purple-400',
};

export const AuditTrailTimeline: FC<Props> = ({ trail, className = '' }) => {
  if (!trail.length) {
    return (
      <p className={`text-sm text-zinc-500 ${className}`}>No audit entries yet.</p>
    );
  }

  return (
    <ol className={`relative border-l border-zinc-700 ${className}`}>
      {trail.map((entry, idx) => {
        const dotColor = STATE_DOT[entry.state] ?? 'bg-zinc-400';
        const actor = entry.actor?.user_id ?? entry.actor?.role ?? 'system';
        const annotation = entry.metadata?.annotation as string | undefined;

        return (
          <li key={idx} className="mb-6 ml-4">
            <span
              className={`absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border-2 border-zinc-900 ${dotColor}`}
            />
            <div className="flex items-baseline gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-zinc-300">
                {entry.state}
              </span>
              <time className="text-xs text-zinc-500">{formatTime(entry.timestamp)}</time>
            </div>
            <p className="mt-0.5 text-xs text-zinc-400">by {actor}</p>
            {annotation && (
              <p className="mt-1 text-xs text-zinc-300 italic">"{annotation}"</p>
            )}
          </li>
        );
      })}
    </ol>
  );
};
