import { Badge, Card, CardContent, CardHeader, formatDecimal, useTimeContext, type LocaleContext } from '@aether/ui';
import { useOutcomeLedger, useProfileOutcomeLedger } from '@aether-app/features/intelligence';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item)) : [];
}

function num(value: unknown): number {
  return typeof value === 'number' ? value : Number(value ?? 0);
}

function money(value: unknown, locale: LocaleContext): string {
  return `$${formatDecimal(num(value), locale, { maximumFractionDigits: 0 })}`;
}

function pct(value: unknown): string {
  return `${Math.round(num(value) * 100)}%`;
}

function Stat({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-surface-raised p-3">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className="mt-1 text-lg font-semibold text-text-primary">{value}</p>
    </div>
  );
}

export function OutcomeLedgerPanel({ entityId }: { readonly entityId?: string }) {
  const timeCtx = useTimeContext();
  const tenantLedger = useOutcomeLedger();
  const entityLedger = useProfileOutcomeLedger(entityId ?? '');
  const ledger = entityId ? entityLedger : tenantLedger;
  const data = asRecord(ledger.data);
  const summary = asRecord(data.summary);
  const byType = asList(data.by_recommendation_type).slice(0, 4);
  const byPlaybook = asList(data.by_playbook).slice(0, 4);
  const confidence = asList(data.confidence_deltas_over_time);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-medium text-text-primary">Outcome Ledger{entityId ? ' for entity' : ''}</h2>
            <p className="mt-1 text-xs text-text-secondary">
              Value, capture, and loop health from recommendations → decisions → actions → outcomes.
            </p>
          </div>
          <Badge variant="info">ROI</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {ledger.isLoading ? <p className="text-sm text-text-secondary">Loading outcome ledger…</p> : null}
        {ledger.error ? <p className="text-sm text-danger">Outcome ledger unavailable.</p> : null}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Observed value" value={money(summary.observed_value, timeCtx)} />
          <Stat label="Expected value" value={money(summary.expected_value, timeCtx)} />
          <Stat label="Pending value" value={money(summary.pending_value, timeCtx)} />
          <Stat label="Outcome capture" value={pct(summary.outcome_capture_rate)} />
          <Stat label="Recommendations" value={String(num(summary.recommendations_generated))} />
          <Stat label="Decisions" value={String(num(summary.decisions_recorded))} />
          <Stat label="Actions" value={String(num(summary.actions_logged))} />
          <Stat label="Outcomes" value={String(num(summary.outcomes_observed))} />
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <div className="rounded-lg border border-border-subtle p-3">
            <h3 className="text-sm font-medium text-text-primary">Outcome mix</h3>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <Badge variant="success">Success {pct(summary.success_rate)}</Badge>
              <Badge variant="danger">Failure {pct(summary.failure_rate)}</Badge>
              <Badge variant="default">Neutral {pct(summary.neutral_rate)}</Badge>
            </div>
          </div>
          <div className="rounded-lg border border-border-subtle p-3">
            <h3 className="text-sm font-medium text-text-primary">Loop health</h3>
            <p className="mt-2 text-xs text-text-secondary">
              {num(summary.stale_loops)} stale · {num(summary.incomplete_loops)} incomplete · {num(summary.failed_loops)} failed
            </p>
          </div>
          <div className="rounded-lg border border-border-subtle p-3">
            <h3 className="text-sm font-medium text-text-primary">Confidence change</h3>
            <p className="mt-2 text-xs text-text-secondary">
              {num(summary.confidence_delta_total).toFixed(2)} total delta across {confidence.length} updates
            </p>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <LedgerList title="Top recommendation types" items={byType} empty="No recommendation type value yet." />
          <LedgerList title="Top playbooks" items={byPlaybook} empty="No playbook-linked value yet." playbook />
        </div>
      </CardContent>
    </Card>
  );
}

function LedgerList({ title, items, empty, playbook = false }: { readonly title: string; readonly items: Array<Record<string, unknown>>; readonly empty: string; readonly playbook?: boolean }) {
  const timeCtx = useTimeContext();
  return (
    <div className="rounded-lg border border-border-subtle p-3">
      <h3 className="text-sm font-medium text-text-primary">{title}</h3>
      {items.length === 0 ? <p className="mt-2 text-xs text-text-secondary">{empty}</p> : (
        <div className="mt-2 space-y-2">
          {items.map((item) => (
            <div key={String(playbook ? item.playbook_id : item.key)} className="flex items-center justify-between gap-3 text-xs">
              <span className="truncate text-text-secondary">{String(playbook ? item.playbook_name : item.key)}</span>
              <span className="font-medium text-text-primary">{money(item.observed_value, timeCtx)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
