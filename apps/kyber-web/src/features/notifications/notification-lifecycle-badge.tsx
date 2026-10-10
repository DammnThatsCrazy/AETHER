import type { FC } from 'react';

export type LifecycleState =
  | 'detected'
  | 'validated'
  | 'queued'
  | 'operator_review'
  | 'approved'
  | 'propagated'
  | 'suppressed'
  | 'expired';

interface Props {
  readonly state: LifecycleState;
  readonly className?: string;
}

const STATE_CONFIG: Record<LifecycleState, { label: string; color: string }> = {
  detected:        { label: 'Detected',        color: 'bg-zinc-500/20 text-zinc-300 border-zinc-500/30' },
  validated:       { label: 'Validated',        color: 'bg-blue-500/20 text-blue-300 border-blue-500/30' },
  queued:          { label: 'Queued',           color: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30' },
  operator_review: { label: 'Needs Review',     color: 'bg-orange-500/20 text-orange-300 border-orange-500/30' },
  approved:        { label: 'Approved',         color: 'bg-green-500/20 text-green-300 border-green-500/30' },
  propagated:      { label: 'Propagated',       color: 'bg-teal-500/20 text-teal-300 border-teal-500/30' },
  suppressed:      { label: 'Suppressed',       color: 'bg-zinc-600/20 text-zinc-400 border-zinc-600/30' },
  expired:         { label: 'Expired',          color: 'bg-red-500/20 text-red-400 border-red-500/30' },
};

export const NotificationLifecycleBadge: FC<Props> = ({ state, className = '' }) => {
  const cfg = STATE_CONFIG[state] ?? STATE_CONFIG.detected;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${cfg.color} ${className}`}
    >
      {cfg.label}
    </span>
  );
};
