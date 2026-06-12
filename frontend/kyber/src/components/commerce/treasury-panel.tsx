/**
 * KYBER: Treasury Panel
 * Displays treasury balance, runway, and spend rate.
 * Owner: Mission page, Command page
 * Adapter: GET /v1/commerce/treasury (commerce:admin)
 */
interface TreasuryData {
  balance_usd: number;
  spend_rate_per_day_usd: number;
  runway_days: number | null;
  last_updated?: string | null;
}

interface TreasuryPanelProps {
  readonly treasury: TreasuryData | null;
  readonly loading?: boolean;
  readonly error?: string | null;
}

export function TreasuryPanel({ treasury, loading = false, error = null }: TreasuryPanelProps) {
  if (loading) {
    return <div className="treasury-panel treasury-panel--loading" aria-busy="true">loading treasury…</div>;
  }
  if (error) {
    return <div className="treasury-panel treasury-panel--error" role="alert">{error}</div>;
  }
  if (!treasury) {
    return <div className="treasury-panel treasury-panel--empty">no treasury data</div>;
  }

  const runwayLabel = treasury.runway_days === null
    ? '∞'
    : treasury.runway_days === 0
    ? 'depleted'
    : `${treasury.runway_days}d`;

  return (
    <div className="treasury-panel">
      <div className="treasury-panel__header">
        <span>TREASURY</span>
      </div>
      <div className="treasury-panel__row">
        <span className="treasury-panel__key">balance</span>
        <span className="treasury-panel__value treasury-panel__value--balance">
          ${treasury.balance_usd.toFixed(2)}
        </span>
      </div>
      <div className="treasury-panel__row">
        <span className="treasury-panel__key">spend/day</span>
        <span className="treasury-panel__value">${treasury.spend_rate_per_day_usd.toFixed(4)}</span>
      </div>
      <div className="treasury-panel__row">
        <span className="treasury-panel__key">runway</span>
        <span
          className={`treasury-panel__value treasury-panel__value--runway${
            treasury.runway_days !== null && treasury.runway_days < 7 ? ' treasury-panel__value--warning' : ''
          }`}
        >
          {runwayLabel}
        </span>
      </div>
    </div>
  );
}
