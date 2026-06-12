/**
 * KYBER: Reuse History
 * Shows how many times an entitlement has been reused and when.
 * Owner: Entities page, Lab page
 */
import type { Entitlement } from '@kyber/lib/schemas/commerce';

interface ReuseHistoryProps {
  readonly entitlement: Entitlement;
  readonly maxReuse?: number;
}

export function ReuseHistory({ entitlement: e, maxReuse }: ReuseHistoryProps) {
  const utilizationPct = maxReuse && maxReuse > 0
    ? Math.min(100, (e.reuse_count / maxReuse) * 100)
    : null;

  return (
    <div className="reuse-history" data-id={e.entitlement_id}>
      <div className="reuse-history__header">
        <span>REUSE HISTORY</span>
        <span className="reuse-history__count">{e.reuse_count} reuses</span>
      </div>
      {utilizationPct !== null && (
        <div className="reuse-history__utilization">
          <div
            className="reuse-history__bar-track"
            role="progressbar"
            aria-valuenow={utilizationPct}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div className="reuse-history__bar-fill" style={{ width: `${utilizationPct}%` }} />
          </div>
          <span className="reuse-history__pct">{utilizationPct.toFixed(0)}% of max</span>
        </div>
      )}
      <dl className="reuse-history__dl">
        <dt>issued</dt><dd>{new Date(e.issued_at).toLocaleString()}</dd>
        {e.last_reused_at && <><dt>last reused</dt><dd>{new Date(e.last_reused_at).toLocaleString()}</dd></>}
        <dt>expires</dt><dd>{new Date(e.expires_at).toLocaleString()}</dd>
        {e.siwx_binding && <><dt>siwx session</dt><dd>{e.siwx_binding}</dd></>}
      </dl>
    </div>
  );
}
