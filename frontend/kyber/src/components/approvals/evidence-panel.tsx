/**
 * KYBER: Evidence Panel
 * Displays the full evidence bundle for an approval (policy decision, requirement).
 * Owner: Review page
 */
import { formatDateTime, useTimeContext } from '@aether/ui';
import type { EvidenceBundle } from '@kyber/lib/schemas/commerce';

interface EvidencePanelProps {
  readonly evidence: EvidenceBundle | null;
  readonly loading?: boolean;
  readonly error?: string | null;
}

export function EvidencePanel({ evidence, loading = false, error = null }: EvidencePanelProps) {
  const timeCtx = useTimeContext();
  if (loading) {
    return <div className="evidence-panel evidence-panel--loading" aria-busy="true">loading evidence…</div>;
  }
  if (error) {
    return <div className="evidence-panel evidence-panel--error" role="alert">{error}</div>;
  }
  if (!evidence) {
    return <div className="evidence-panel evidence-panel--empty">no evidence loaded</div>;
  }

  const { approval, policy_decision, requirement } = evidence;

  return (
    <div className="evidence-panel">
      <div className="evidence-panel__header">EVIDENCE BUNDLE</div>
      <section className="evidence-panel__section">
        <h4 className="evidence-panel__section-title">Approval</h4>
        <dl className="evidence-panel__dl">
          <dt>id</dt><dd>{approval.approval_id}</dd>
          <dt>status</dt><dd>{approval.status}</dd>
          <dt>priority</dt><dd>{approval.priority}</dd>
          <dt>amount</dt><dd>${approval.amount_usd.toFixed(4)} {approval.asset_symbol}</dd>
          <dt>requester</dt><dd>{approval.requester_id} ({approval.requester_type})</dd>
          {approval.decided_by && <><dt>decided by</dt><dd>{approval.decided_by}</dd></>}
          {approval.decision_reason && <><dt>reason</dt><dd>{approval.decision_reason}</dd></>}
        </dl>
      </section>
      {policy_decision && (
        <section className="evidence-panel__section">
          <h4 className="evidence-panel__section-title">Policy Decision</h4>
          <dl className="evidence-panel__dl">
            <dt>outcome</dt><dd>{policy_decision.outcome}</dd>
            <dt>rationale</dt><dd>{policy_decision.rationale}</dd>
            <dt>rules</dt><dd>{policy_decision.active_rules.join(', ')}</dd>
            {policy_decision.denial_reason && <><dt>denial</dt><dd>{policy_decision.denial_reason}</dd></>}
          </dl>
        </section>
      )}
      {requirement && (
        <section className="evidence-panel__section">
          <h4 className="evidence-panel__section-title">Payment Requirement</h4>
          <dl className="evidence-panel__dl">
            <dt>challenge id</dt><dd>{requirement.challenge_id}</dd>
            <dt>amount</dt><dd>${requirement.amount_usd.toFixed(4)} {requirement.asset_symbol}</dd>
            <dt>chain</dt><dd>{requirement.chain}</dd>
            <dt>expires</dt><dd>{formatDateTime(requirement.expires_at, timeCtx)}</dd>
          </dl>
        </section>
      )}
    </div>
  );
}
