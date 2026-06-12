/**
 * KYBER: Decision Form
 * Form for approve/reject/escalate decisions on an approval request.
 * Owner: Review page
 * Permissions: commerce:approve
 */
import { useState } from 'react';
import type { ApprovalRequest } from '@kyber/lib/schemas/commerce';

type DecisionAction = 'approve' | 'reject' | 'escalate';

interface DecisionFormProps {
  readonly approval: ApprovalRequest;
  readonly currentUserId: string;
  readonly canApprove: boolean;
  readonly onDecide: (approvalId: string, action: DecisionAction, decidedBy: string, reason: string, isOverride?: boolean) => Promise<ApprovalRequest>;
  readonly onCancel?: () => void;
}

export function DecisionForm({ approval, currentUserId, canApprove, onDecide, onCancel }: DecisionFormProps) {
  const [reason, setReason] = useState('');
  const [isOverride, setIsOverride] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAction(action: DecisionAction) {
    if (!canApprove || !reason.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onDecide(approval.approval_id, action, currentUserId, reason.trim(), isOverride);
      setReason('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'decision failed');
    } finally {
      setBusy(false);
    }
  }

  if (!canApprove) {
    return (
      <div className="decision-form decision-form--no-permission">
        insufficient permission (commerce:approve required)
      </div>
    );
  }

  const isActionable = ['pending', 'assigned', 'escalated'].includes(approval.status);

  if (!isActionable) {
    return (
      <div className="decision-form decision-form--resolved">
        approval is already {approval.status}
      </div>
    );
  }

  return (
    <form
      className="decision-form"
      onSubmit={(e) => e.preventDefault()}
      aria-label={`decision form for ${approval.approval_id}`}
    >
      {error && <div className="decision-form__error" role="alert">{error}</div>}
      <label className="decision-form__label" htmlFor="decision-reason">
        reason (required)
      </label>
      <textarea
        id="decision-reason"
        className="decision-form__reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="explain your decision…"
        rows={3}
        disabled={busy}
        required
      />
      <label className="decision-form__override-label">
        <input
          type="checkbox"
          className="decision-form__override-check"
          checked={isOverride}
          onChange={(e) => setIsOverride(e.target.checked)}
          disabled={busy}
        />
        mark as override decision
      </label>
      <div className="decision-form__actions">
        <button
          type="button"
          className="decision-form__btn decision-form__btn--approve"
          disabled={busy || !reason.trim()}
          onClick={() => void handleAction('approve')}
        >
          approve
        </button>
        <button
          type="button"
          className="decision-form__btn decision-form__btn--reject"
          disabled={busy || !reason.trim()}
          onClick={() => void handleAction('reject')}
        >
          reject
        </button>
        <button
          type="button"
          className="decision-form__btn decision-form__btn--escalate"
          disabled={busy || !reason.trim()}
          onClick={() => void handleAction('escalate')}
        >
          escalate
        </button>
        {onCancel && (
          <button type="button" className="decision-form__btn decision-form__btn--cancel" onClick={onCancel} disabled={busy}>
            cancel
          </button>
        )}
      </div>
    </form>
  );
}
