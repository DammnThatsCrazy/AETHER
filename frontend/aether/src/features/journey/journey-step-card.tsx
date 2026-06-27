import { useState, type FC } from 'react';
import type { JourneyStep, ActivityFamily } from './use-unified-journey';

const FAMILY_COLORS: Record<ActivityFamily, string> = {
  web2: 'border-l-blue-500',
  web3: 'border-l-violet-500',
  campaign: 'border-l-amber-500',
  commerce: 'border-l-green-500',
  agent: 'border-l-cyan-500',
  x402: 'border-l-rose-500',
  outcome: 'border-l-emerald-600',
};

const FAMILY_ICONS: Record<ActivityFamily, string> = {
  web2: '🌐',
  web3: '⛓',
  campaign: '📣',
  commerce: '💳',
  agent: '🤖',
  x402: '💸',
  outcome: '🎯',
};

const FAMILY_LABELS: Record<ActivityFamily, string> = {
  web2: 'Web',
  web3: 'Web3',
  campaign: 'Campaign',
  commerce: 'Commerce',
  agent: 'Agent',
  x402: 'x402',
  outcome: 'Outcome',
};

const STATUS_VARIANTS: Record<string, string> = {
  observed: 'bg-blue-100 text-blue-800',
  pending: 'bg-yellow-100 text-yellow-800',
  confirmed: 'bg-green-100 text-green-800',
  finalized: 'bg-green-200 text-green-900',
  failed: 'bg-red-100 text-red-800',
  reverted: 'bg-red-200 text-red-900',
  reorged: 'bg-orange-100 text-orange-800',
  adjusted: 'bg-purple-100 text-purple-800',
  deleted: 'bg-gray-100 text-gray-500 line-through',
  tombstoned: 'bg-gray-200 text-gray-400',
  consent_restricted: 'bg-gray-100 text-gray-400 italic',
};

interface Props {
  step: JourneyStep;
  position: number;
}

export const JourneyStepCard: FC<Props> = ({ step, position }) => {
  const [expanded, setExpanded] = useState(false);
  const family = step.activity_family as ActivityFamily;
  const borderColor = FAMILY_COLORS[family] ?? 'border-l-gray-300';
  const icon = FAMILY_ICONS[family] ?? '•';
  const familyLabel = FAMILY_LABELS[family] ?? family;
  const statusClass = STATUS_VARIANTS[step.activity_status] ?? 'bg-gray-100 text-gray-600';
  const isRestrictedOrDeleted = step.activity_status === 'tombstoned' || step.activity_status === 'consent_restricted';

  const formattedTime = step.occurred_at
    ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(step.occurred_at))
    : '—';

  return (
    <article
      className={`relative border-l-4 ${borderColor} bg-surface rounded-r-md px-4 py-3 shadow-sm hover:shadow transition-shadow`}
      aria-label={`Step ${position}: ${step.displayLabel}`}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 text-base leading-none" aria-hidden="true">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-sm font-medium text-text truncate">
              {isRestrictedOrDeleted ? '[Redacted]' : step.displayLabel}
            </span>
            <span className="text-xs text-text-muted shrink-0">{formattedTime}</span>
          </div>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-surface-secondary border border-border text-text-muted">
              {familyLabel}
            </span>
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${statusClass}`}>
              {step.activity_status}
            </span>
            {step.identity_confidence != null && (
              <span className="text-[10px] text-text-muted">
                {(step.identity_confidence * 100).toFixed(0)}% confidence
              </span>
            )}
          </div>
        </div>
        <button
          onClick={() => setExpanded(e => !e)}
          className="shrink-0 text-xs text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent rounded"
          aria-expanded={expanded}
          aria-controls={`step-detail-${step.step_id}`}
        >
          {expanded ? '▲' : '▼'}
        </button>
      </div>

      {expanded && (
        <dl
          id={`step-detail-${step.step_id}`}
          className="mt-3 ml-7 grid grid-cols-2 gap-x-4 gap-y-1 text-xs border-t border-border pt-2"
        >
          {step.chain_id && <><dt className="text-text-muted">Chain</dt><dd className="font-mono">{step.chain_id}</dd></>}
          {step.wallet_id && <><dt className="text-text-muted">Wallet</dt><dd className="font-mono truncate">{step.wallet_id.slice(0, 16)}…</dd></>}
          {step.campaign_id && <><dt className="text-text-muted">Campaign</dt><dd className="font-mono">{step.campaign_id}</dd></>}
          {step.agent_id && <><dt className="text-text-muted">Agent</dt><dd className="font-mono">{step.agent_id.slice(0, 12)}…</dd></>}
          {step.session_id && <><dt className="text-text-muted">Session</dt><dd className="font-mono text-[10px]">{step.session_id.slice(0, 16)}…</dd></>}
          {step.identity_method && <><dt className="text-text-muted">ID method</dt><dd>{step.identity_method}</dd></>}
          {step.actor_type && <><dt className="text-text-muted">Actor</dt><dd>{step.actor_type}</dd></>}
          <dt className="text-text-muted">Position</dt><dd>{step.step_position}</dd>
        </dl>
      )}
    </article>
  );
};
