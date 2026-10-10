/**
 * KYBER: Lifecycle Trace View
 * Owner: Noesis, Review, Diagnostics (evidence drawer), Lab (replay)
 * Feature module: features/approvals (loadTrace)
 * Adapter: lib/api/commerce.ts (commerceApi.explain)
 * Schema: lifecycleTraceSchema
 * Permissions: x402:read
 * Answers: why approval, who approved, which policy fired, which facilitator,
 *          what graph state was written, did settlement succeed.
 */
import type { LifecycleTrace } from '@kyber/lib/schemas/commerce';

interface LifecycleTraceViewProps {
  readonly trace: LifecycleTrace;
}

interface Stage {
  readonly name: string;
  readonly present: boolean;
  readonly detail?: string | undefined;
}

export function LifecycleTraceView({ trace }: LifecycleTraceViewProps) {
  const stages: Stage[] = [
    {
      name: 'Challenge',
      present: !!trace.requirement,
      detail: trace.requirement
        ? `$${trace.requirement.amount_usd} ${trace.requirement.asset_symbol} on ${trace.requirement.chain} (v${trace.requirement.protocol_version})`
        : undefined,
    },
    {
      name: 'Policy',
      present: !!trace.policy_decision,
      detail: trace.policy_decision
        ? `${trace.policy_decision.outcome} — ${trace.policy_decision.rationale}`
        : undefined,
    },
    {
      name: 'Approval',
      present: !!trace.approval,
      detail: trace.approval
        ? `${trace.approval.status}${trace.approval.decided_by ? ` by ${trace.approval.decided_by}` : ''}`
        : undefined,
    },
    {
      name: 'Authorization',
      present: !!trace.authorization,
      detail: trace.authorization ? 'ready' : undefined,
    },
    {
      name: 'Receipt',
      present: !!trace.receipt,
      detail: trace.receipt ? 'verified' : undefined,
    },
    {
      name: 'Settlement',
      present: !!trace.settlement,
      detail: trace.settlement
        ? `${trace.settlement.state} via ${trace.settlement.facilitator_id}`
        : undefined,
    },
    {
      name: 'Entitlement',
      present: !!trace.entitlement,
      detail: trace.entitlement
        ? `${trace.entitlement.status}, expires ${trace.entitlement.expires_at}`
        : undefined,
    },
    {
      name: 'Grant',
      present: !!trace.grant,
      detail: trace.grant ? 'issued' : undefined,
    },
    {
      name: 'Fulfillment',
      present: !!trace.fulfillment,
      detail: trace.fulfillment ? 'completed' : undefined,
    },
  ];

  return (
    <div className="lifecycle-trace" data-challenge={trace.challenge_id}>
      <div className="lifecycle-trace__header">
        LIFECYCLE TRACE — {trace.challenge_id}
      </div>
      <ol className="lifecycle-trace__stages">
        {stages.map((s, i) => (
          <li
            key={s.name}
            className={`lifecycle-trace__stage lifecycle-trace__stage--${s.present ? 'present' : 'absent'}`}
          >
            <span className="lifecycle-trace__stage-num">{i + 1}</span>
            <span className="lifecycle-trace__stage-name">{s.name}</span>
            {s.detail && <span className="lifecycle-trace__stage-detail">{s.detail}</span>}
          </li>
        ))}
      </ol>
      <div className="lifecycle-trace__footer">
        <div className="lifecycle-trace__graph-writes">
          graph mutations: {trace.graph_writes.length}
        </div>
        <div className="lifecycle-trace__events">
          events emitted: {trace.events_emitted.length}
        </div>
      </div>
    </div>
  );
}
