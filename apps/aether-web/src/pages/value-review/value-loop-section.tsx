import { DecisionIntelligencePanel } from '@aether-app/components/decision-intelligence-panel';
import { OutcomeLedgerPanel } from '@aether-app/components/outcome-ledger-panel';
import { useAuth } from '@aether-app/features/auth';
import { ModelSelectionPanel } from '@aether-app/features/model-selection';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';

/**
 * "Loop and decisions" — the outcome ledger's value figures, the decision
 * intelligence feed (with approval gates and playbooks) and, behind
 * `enableModelHarness` (ADR-008 D8/D9), the tenant model-routing preference.
 * These used to sit on Home; they live with the rest of the outcome loop now.
 */
export function LoopAndDecisionsSection({ ledger = 'value' }: { readonly ledger?: 'full' | 'value' }) {
  const { user } = useAuth();
  return (
    <section className="flex min-w-0 flex-col gap-[18px]" aria-labelledby="value-loop-heading" data-testid="value-loop-decisions">
      <div className="flex flex-col gap-1 border-t pt-[18px]" style={{ borderColor: 'var(--ae-edge)' }}>
        <h2 id="value-loop-heading" className="text-[20px] font-medium leading-tight tracking-[-0.3px]">Loop and decisions</h2>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
          What the open recommendations are, who can approve them, and the value the loop has captured so far.
        </span>
      </div>
      <div className="grid items-start gap-[18px]" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(360px, 100%), 1fr))' }}>
        <OutcomeLedgerPanel variant={ledger} />
        <DecisionIntelligencePanel />
      </div>
      {isFeatureEnabled('enableModelHarness') && (
        <div className="ae-legacy min-w-0">
          <ModelSelectionPanel {...(user?.id ? { tenantId: user.id } : {})} />
        </div>
      )}
    </section>
  );
}
