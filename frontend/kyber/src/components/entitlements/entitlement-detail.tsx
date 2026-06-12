/**
 * KYBER: Entitlement Detail
 * Full details for a single entitlement.
 * Owner: Entities page
 */
import type { Entitlement } from '@kyber/lib/schemas/commerce';

interface EntitlementDetailProps {
  readonly entitlement: Entitlement | null;
  readonly loading?: boolean;
  readonly error?: string | null;
}

export function EntitlementDetail({ entitlement: e, loading = false, error = null }: EntitlementDetailProps) {
  if (loading) {
    return <div className="entitlement-detail entitlement-detail--loading" aria-busy="true">loading…</div>;
  }
  if (error) {
    return <div className="entitlement-detail entitlement-detail--error" role="alert">{error}</div>;
  }
  if (!e) {
    return <div className="entitlement-detail entitlement-detail--empty">no entitlement selected</div>;
  }

  return (
    <div className="entitlement-detail" data-id={e.entitlement_id} data-status={e.status}>
      <div className="entitlement-detail__header">
        <span className="entitlement-detail__id">{e.entitlement_id}</span>
        <span className={`entitlement-detail__status entitlement-detail__status--${e.status}`}>{e.status}</span>
      </div>
      <dl className="entitlement-detail__dl">
        <dt>resource</dt><dd>{e.resource_id}</dd>
        <dt>scope</dt><dd>{e.scope}</dd>
        <dt>holder</dt><dd>{e.holder_id} ({e.holder_type})</dd>
        <dt>settlement</dt><dd>{e.settlement_id}</dd>
        <dt>issued</dt><dd>{new Date(e.issued_at).toLocaleString()}</dd>
        <dt>expires</dt><dd>{new Date(e.expires_at).toLocaleString()}</dd>
        <dt>reuse count</dt><dd>{e.reuse_count}</dd>
        {e.last_reused_at && <><dt>last reused</dt><dd>{new Date(e.last_reused_at).toLocaleString()}</dd></>}
        {e.siwx_binding && <><dt>siwx binding</dt><dd>{e.siwx_binding}</dd></>}
        {e.revoked_at && (
          <>
            <dt>revoked at</dt><dd>{new Date(e.revoked_at).toLocaleString()}</dd>
            <dt>revoked by</dt><dd>{e.revoked_by}</dd>
            <dt>revoke reason</dt><dd>{e.revoke_reason}</dd>
          </>
        )}
      </dl>
    </div>
  );
}
