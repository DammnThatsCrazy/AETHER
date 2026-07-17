/**
 * KYBER: Spend Timeline
 * Shows agent/cluster spend events over time.
 * Owner: Mission page, Live page
 * Feature module: features/commerce
 */
import { formatTime, useTimeContext } from '@aether/ui';
import type { Settlement } from '@kyber/lib/schemas/commerce';

interface SpendTimelineProps {
  readonly settlements: readonly Settlement[];
  readonly agentId?: string;
  readonly maxItems?: number;
}

export function SpendTimeline({ settlements, agentId, maxItems = 20 }: SpendTimelineProps) {
  const timeCtx = useTimeContext();
  const items = agentId
    ? settlements.filter((s) => s.challenge_id.includes(agentId))
    : settlements;
  const visible = items.slice(-maxItems);

  if (visible.length === 0) {
    return <div className="spend-timeline spend-timeline--empty">no spend events</div>;
  }

  return (
    <div className="spend-timeline" data-count={visible.length}>
      <div className="spend-timeline__header">
        <span>SPEND TIMELINE</span>
        <span className="spend-timeline__count">{visible.length} events</span>
      </div>
      <ol className="spend-timeline__list">
        {visible.map((s) => (
          <li key={s.settlement_id} className={`spend-timeline__item spend-timeline__item--${s.state}`}>
            <span className="spend-timeline__time">
              {s.settled_at ? formatTime(s.settled_at, timeCtx) : '—'}
            </span>
            <span className="spend-timeline__chain">{s.chain.split(':')[0]}</span>
            <span className="spend-timeline__asset">{s.facilitator_id}</span>
            <span className="spend-timeline__amount">${s.amount_usd.toFixed(4)}</span>
            <span className={`spend-timeline__state spend-timeline__state--${s.state}`}>{s.state}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
