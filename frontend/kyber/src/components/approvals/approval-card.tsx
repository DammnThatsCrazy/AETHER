/**
 * KYBER: Approval Card
 * Read-only card displaying a single approval request detail.
 * Owner: Review page
 */
import type { ApprovalRequest } from '@kyber/lib/schemas/commerce';

interface ApprovalCardProps {
  readonly approval: ApprovalRequest;
  readonly onClick?: (approval: ApprovalRequest) => void;
  readonly compact?: boolean;
}

export function ApprovalCard({ approval: a, onClick, compact = false }: ApprovalCardProps) {
  return (
    <div
      className={`approval-card approval-card--${a.priority} approval-card--${a.status}${compact ? ' approval-card--compact' : ''}`}
      onClick={() => onClick?.(a)}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => e.key === 'Enter' && onClick?.(a)}
      data-id={a.approval_id}
    >
      <div className="approval-card__head">
        <span className="approval-card__priority" aria-label={`priority ${a.priority}`}>{a.priority.toUpperCase()}</span>
        <span className="approval-card__status">{a.status}</span>
        <span className="approval-card__amount">${a.amount_usd.toFixed(2)} {a.asset_symbol}</span>
      </div>
      {!compact && (
        <>
          <div className="approval-card__body">
            <span className="approval-card__resource">{a.resource_id}</span>
            <span className="approval-card__requester">{a.requester_id} ({a.requester_type})</span>
          </div>
          <div className="approval-card__reason">{a.reason}</div>
          {a.decided_by && (
            <div className="approval-card__decision">
              <span className="approval-card__decision-by">{a.decided_by}</span>
              <span className="approval-card__decision-reason">{a.decision_reason}</span>
            </div>
          )}
          <div className="approval-card__timestamps">
            <span>created {new Date(a.created_at).toLocaleString()}</span>
            {a.decided_at && <span>decided {new Date(a.decided_at).toLocaleString()}</span>}
          </div>
        </>
      )}
    </div>
  );
}
