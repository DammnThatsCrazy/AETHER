/**
 * KYBER: Escalation Router
 * UI for routing/reassigning escalated approvals to a new assignee.
 * Owner: Review page
 */
import { useState } from 'react';
import type { ApprovalRequest } from '@kyber/lib/schemas/commerce';

interface EscalationRouterProps {
  readonly approval: ApprovalRequest;
  readonly availableAssignees: readonly string[];
  readonly currentUserId: string;
  readonly onAssign: (approvalId: string, assigneeId: string, assignedBy: string) => Promise<ApprovalRequest>;
  readonly onEscalate: (approvalId: string, action: 'escalate', decidedBy: string, reason: string) => Promise<ApprovalRequest>;
}

export function EscalationRouter({ approval, availableAssignees, currentUserId, onAssign, onEscalate }: EscalationRouterProps) {
  const [selectedAssignee, setSelectedAssignee] = useState('');
  const [escalateReason, setEscalateReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAssign() {
    if (!selectedAssignee || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onAssign(approval.approval_id, selectedAssignee, currentUserId);
      setSelectedAssignee('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'assign failed');
    } finally {
      setBusy(false);
    }
  }

  async function handleEscalate() {
    if (!escalateReason.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onEscalate(approval.approval_id, 'escalate', currentUserId, escalateReason.trim());
      setEscalateReason('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'escalation failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="escalation-router">
      {error && <div className="escalation-router__error" role="alert">{error}</div>}
      <div className="escalation-router__chain">
        <span className="escalation-router__label">escalation chain</span>
        {approval.escalation_chain.length > 0
          ? <span className="escalation-router__chain-list">{approval.escalation_chain.join(' → ')}</span>
          : <span className="escalation-router__chain-empty">none yet</span>
        }
      </div>
      <div className="escalation-router__assign">
        <label htmlFor="escalation-assignee" className="escalation-router__label">assign to</label>
        <select
          id="escalation-assignee"
          value={selectedAssignee}
          onChange={(e) => setSelectedAssignee(e.target.value)}
          className="escalation-router__select"
          disabled={busy}
        >
          <option value="">— select assignee —</option>
          {availableAssignees.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <button
          type="button"
          className="escalation-router__btn escalation-router__btn--assign"
          onClick={() => void handleAssign()}
          disabled={busy || !selectedAssignee}
        >
          assign
        </button>
      </div>
      <div className="escalation-router__escalate">
        <label htmlFor="escalation-reason" className="escalation-router__label">escalate reason</label>
        <input
          id="escalation-reason"
          type="text"
          value={escalateReason}
          onChange={(e) => setEscalateReason(e.target.value)}
          placeholder="reason for escalation…"
          className="escalation-router__input"
          disabled={busy}
        />
        <button
          type="button"
          className="escalation-router__btn escalation-router__btn--escalate"
          onClick={() => void handleEscalate()}
          disabled={busy || !escalateReason.trim()}
        >
          escalate
        </button>
      </div>
    </div>
  );
}
