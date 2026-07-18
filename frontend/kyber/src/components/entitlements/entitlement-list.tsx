/**
 * KYBER: Entitlement List
 * Lists active/expired/revoked entitlements for an agent or user.
 * Owner: Entities page, Command page
 * Feature module: features/entitlements
 */
import { formatDateTime, useTimeContext } from '@aether/ui';
import type { Entitlement } from '@kyber/lib/schemas/commerce';

interface EntitlementListProps {
  readonly entitlements: readonly Entitlement[];
  readonly loading?: boolean;
  readonly error?: string | null;
  readonly onSelect?: (entitlement: Entitlement) => void;
  readonly canRevoke?: boolean;
  readonly onRevoke?: (entitlementId: string) => void;
}

export function EntitlementList({ entitlements, loading = false, error = null, onSelect, canRevoke = false, onRevoke }: EntitlementListProps) {
  const timeCtx = useTimeContext();
  if (loading) {
    return <div className="entitlement-list entitlement-list--loading" aria-busy="true">loading entitlements…</div>;
  }
  if (error) {
    return <div className="entitlement-list entitlement-list--error" role="alert">{error}</div>;
  }
  if (entitlements.length === 0) {
    return <div className="entitlement-list entitlement-list--empty">no entitlements</div>;
  }

  return (
    <div className="entitlement-list" data-count={entitlements.length}>
      <div className="entitlement-list__header">
        <span>ENTITLEMENTS</span>
        <span className="entitlement-list__count">{entitlements.length}</span>
      </div>
      <ul className="entitlement-list__items">
        {entitlements.map((e) => (
          <li
            key={e.entitlement_id}
            className={`entitlement-list__item entitlement-list__item--${e.status}`}
            onClick={() => onSelect?.(e)}
            role={onSelect ? 'button' : undefined}
            tabIndex={onSelect ? 0 : undefined}
            onKeyDown={(ev) => ev.key === 'Enter' && onSelect?.(e)}
          >
            <div className="entitlement-list__item-head">
              <span className={`entitlement-list__status entitlement-list__status--${e.status}`}>{e.status}</span>
              <span className="entitlement-list__resource">{e.resource_id}</span>
              <span className="entitlement-list__scope">{e.scope}</span>
            </div>
            <div className="entitlement-list__item-body">
              <span className="entitlement-list__holder">{e.holder_id} ({e.holder_type})</span>
              <span className="entitlement-list__reuse">reused {e.reuse_count}×</span>
              <span className="entitlement-list__expires">
                expires {formatDateTime(e.expires_at, timeCtx)}
              </span>
            </div>
            {canRevoke && e.status === 'active' && onRevoke && (
              <div className="entitlement-list__actions" onClick={(ev) => ev.stopPropagation()}>
                <button
                  type="button"
                  className="entitlement-list__revoke-btn"
                  onClick={() => onRevoke(e.entitlement_id)}
                  aria-label={`revoke ${e.entitlement_id}`}
                >
                  revoke
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
