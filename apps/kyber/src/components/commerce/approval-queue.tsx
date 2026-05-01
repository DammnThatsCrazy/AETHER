/**
 * KYBER: Approval Queue Panel
 * Owner: Review page (primary), Command page (backlog summary)
 * Feature module: features/approvals
 * Adapter: lib/api/commerce.ts (approvalsApi)
 * Schema: lib/schemas/commerce.ts
 * Permissions:
 *   - viewing queue: approvals:read  (kyber: canViewAll)
 *   - deciding: commerce:approve     (kyber: canApprove)
 * Action emits: aether.commerce.approval.{approved|rejected|escalated}
 * Mocked mode: fixtureApprovalQueue
 * Live mode: GET /v1/approvals
 */
import { useState } from 'react';
import { useApprovals } from '@kyber/features/approvals';
import type { ApprovalRequest, ApprovalStatus } from '@kyber/lib/schemas/commerce';

interface ApprovalQueueProps {
  readonly statusFilter?: ApprovalStatus;
  readonly canApprove: boolean;
  readonly currentUserId: string;
  readonly onRowClick?: (approval: ApprovalRequest) => void;
}

export function ApprovalQueue({
  statusFilter,
  canApprove,
  currentUserId,
  onRowClick,
}: ApprovalQueueProps) {
  const { approvals, loading, error, mode, decide, revoke } = useApprovals(statusFilter);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [decisionReason, setDecisionReason] = useState('');

  async function handleDecide(
    approval: ApprovalRequest,
    action: 'approve' | 'reject' | 'escalate'
  ) {
    if (!canApprove) return;
    if (!decisionReason.trim()) return;
    setBusyId(approval.approval_id);
    try {
      await decide(approval.approval_id, action, currentUserId, decisionReason);
      setDecisionReason('');
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return <div className="approval-queue approval-queue--loading">loading approvals…</div>;
  }
  if (error) {
    return (
      <div className="approval-queue approval-queue--error" role="alert">
        error: {error}
      </div>
    );
  }
  if (approvals.length === 0) {
    return (
      <div className="approval-queue approval-queue--empty">
        no approvals in queue ({mode} mode)
      </div>
    );
  }

  return (
    <div className="approval-queue" data-mode={mode} data-count={approvals.length}>
      <div className="approval-queue__header">
        <span>APPROVAL QUEUE</span>
        <span className="approval-queue__mode">{mode.toUpperCase()}</span>
        <span className="approval-queue__count">{approvals.length} items</span>
      </div>
      {canApprove && (
        <div className="approval-queue__decision-bar">
          <input
            type="text"
            value={decisionReason}
            onChange={(e) => setDecisionReason(e.target.value)}
            placeholder="decision reason (required)"
            className="approval-queue__reason-input"
            aria-label="decision reason"
          />
        </div>
      )}
      <ul className="approval-queue__list">
        {approvals.map((a) => (
          <li
            key={a.approval_id}
            className={`approval-queue__item approval-queue__item--${a.priority} approval-queue__item--${a.status}`}
            onClick={() => onRowClick?.(a)}
          >
            <div className="approval-queue__row-head">
              <span className="approval-queue__priority">{a.priority.toUpperCase()}</span>
              <span className="approval-queue__amount">${a.amount_usd.toFixed(2)}</span>
              <span className="approval-queue__asset">
                {a.asset_symbol}/{a.chain.split(':')[0]}
              </span>
              <span className="approval-queue__status">{a.status}</span>
            </div>
            <div className="approval-queue__row-body">
              <span className="approval-queue__requester">{a.requester_id}</span>
              <span className="approval-queue__resource">{a.resource_id}</span>
              <span className="approval-queue__reason">{a.reason}</span>
            </div>
            {canApprove && (a.status === 'pending' || a.status === 'assigned' || a.status === 'escalated') && (
              <div className="approval-queue__actions" onClick={(e) => e.stopPropagation()}>
                <button
                  type="button"
                  disabled={busyId === a.approval_id || !decisionReason.trim()}
                  onClick={() => handleDecide(a, 'approve')}
                  className="approval-queue__btn approval-queue__btn--approve"
                  aria-label={`approve ${a.approval_id}`}
                >
                  approve
                </button>
                <button
                  type="button"
                  disabled={busyId === a.approval_id || !decisionReason.trim()}
                  onClick={() => handleDecide(a, 'reject')}
                  className="approval-queue__btn approval-queue__btn--reject"
                  aria-label={`reject ${a.approval_id}`}
                >
                  reject
                </button>
                <button
                  type="button"
                  disabled={busyId === a.approval_id || !decisionReason.trim()}
                  onClick={() => handleDecide(a, 'escalate')}
                  className="approval-queue__btn approval-queue__btn--escalate"
                  aria-label={`escalate ${a.approval_id}`}
                >
                  escalate
                </button>
              </div>
            )}
            {canApprove && a.status === 'approved' && (
              <div className="approval-queue__actions" onClick={(e) => e.stopPropagation()}>
                <button
                  type="button"
                  disabled={busyId === a.approval_id || !decisionReason.trim()}
                  onClick={async () => {
                    setBusyId(a.approval_id);
                    try {
                      await revoke(a.approval_id, currentUserId, decisionReason);
                      setDecisionReason('');
                    } finally {
                      setBusyId(null);
                    }
                  }}
                  className="approval-queue__btn approval-queue__btn--revoke"
                  aria-label={`revoke ${a.approval_id}`}
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
