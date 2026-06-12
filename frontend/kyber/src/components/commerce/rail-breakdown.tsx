/**
 * KYBER: Rail Breakdown
 * Shows payment volume breakdown by chain/asset rail.
 * Owner: Live page, Mission page
 */
interface RailStat {
  chain: string;
  asset_symbol: string;
  volume_usd: number;
  transaction_count: number;
  success_rate: number;
}

interface RailBreakdownProps {
  readonly rails: readonly RailStat[];
  readonly loading?: boolean;
}

export function RailBreakdown({ rails, loading = false }: RailBreakdownProps) {
  if (loading) {
    return <div className="rail-breakdown rail-breakdown--loading" aria-busy="true">loading rails…</div>;
  }
  if (rails.length === 0) {
    return <div className="rail-breakdown rail-breakdown--empty">no rail data</div>;
  }

  const totalVolume = rails.reduce((sum, r) => sum + r.volume_usd, 0);

  return (
    <div className="rail-breakdown" data-rails={rails.length}>
      <div className="rail-breakdown__header">
        <span>RAIL BREAKDOWN</span>
        <span className="rail-breakdown__total">${totalVolume.toFixed(2)} total</span>
      </div>
      <ul className="rail-breakdown__list">
        {rails.map((r) => {
          const pct = totalVolume > 0 ? ((r.volume_usd / totalVolume) * 100).toFixed(1) : '0.0';
          return (
            <li key={`${r.chain}:${r.asset_symbol}`} className="rail-breakdown__item">
              <span className="rail-breakdown__rail">{r.asset_symbol}/{r.chain.split(':')[0]}</span>
              <div className="rail-breakdown__bar-wrap">
                <div className="rail-breakdown__bar" style={{ width: `${pct}%` }} />
              </div>
              <span className="rail-breakdown__volume">${r.volume_usd.toFixed(2)}</span>
              <span className="rail-breakdown__pct">{pct}%</span>
              <span className="rail-breakdown__success">{(r.success_rate * 100).toFixed(1)}% ok</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
