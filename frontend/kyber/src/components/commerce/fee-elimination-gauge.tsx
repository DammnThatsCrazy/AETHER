/**
 * KYBER: Fee Elimination Gauge
 * Shows how much x402 has saved vs. traditional payment rails.
 * Owner: Mission page
 */
interface FeeEliminationGaugeProps {
  readonly savedUsd: number;
  readonly comparisonRailFeeUsd: number;
  readonly volumeUsd: number;
  readonly loading?: boolean;
}

export function FeeEliminationGauge({ savedUsd, comparisonRailFeeUsd, volumeUsd, loading = false }: FeeEliminationGaugeProps) {
  if (loading) {
    return <div className="fee-gauge fee-gauge--loading" aria-busy="true">loading…</div>;
  }

  const eliminationPct = comparisonRailFeeUsd > 0
    ? Math.min(100, (savedUsd / comparisonRailFeeUsd) * 100)
    : 0;

  return (
    <div className="fee-gauge" aria-label={`fee elimination ${eliminationPct.toFixed(0)}%`}>
      <div className="fee-gauge__header">
        <span>FEE ELIMINATION</span>
        <span className="fee-gauge__pct">{eliminationPct.toFixed(1)}%</span>
      </div>
      <div className="fee-gauge__track" role="progressbar" aria-valuenow={eliminationPct} aria-valuemin={0} aria-valuemax={100}>
        <div className="fee-gauge__fill" style={{ width: `${eliminationPct}%` }} />
      </div>
      <div className="fee-gauge__stats">
        <span className="fee-gauge__saved">${savedUsd.toFixed(2)} saved</span>
        <span className="fee-gauge__volume">of ${volumeUsd.toFixed(2)} volume</span>
      </div>
    </div>
  );
}
