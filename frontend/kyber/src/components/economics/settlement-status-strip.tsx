/**
 * KYBER: Settlement Status Strip
 * Compact status bar showing pending/verifying/settled/failed/disputed counts.
 * Owner: Live page, Diagnostics page
 */
import type { Settlement } from '@kyber/lib/schemas/commerce';

interface SettlementStatusStripProps {
  readonly settlements: readonly Settlement[];
  readonly onStateClick?: (state: string) => void;
}

const STATE_ORDER = ['pending', 'verifying', 'settled', 'failed', 'disputed'] as const;

export function SettlementStatusStrip({ settlements, onStateClick }: SettlementStatusStripProps) {
  const counts: Record<string, number> = {};
  for (const s of settlements) {
    counts[s.state] = (counts[s.state] ?? 0) + 1;
  }

  return (
    <div className="settlement-strip" aria-label="settlement status strip">
      {STATE_ORDER.map((state) => {
        const count = counts[state] ?? 0;
        return (
          <button
            key={state}
            type="button"
            className={`settlement-strip__state settlement-strip__state--${state}${count > 0 ? ' settlement-strip__state--active' : ''}`}
            onClick={() => onStateClick?.(state)}
            aria-label={`${count} ${state}`}
          >
            <span className="settlement-strip__label">{state}</span>
            <span className="settlement-strip__count">{count}</span>
          </button>
        );
      })}
    </div>
  );
}
