import type { ReactNode } from 'react';
import { formatDecimal, useTimeContext, type LocaleContext } from '@aether/ui';
import { Eyebrow, InlineNotice, MetricTile, Spinner, TonePill } from '@aether-app/components/ae-ui';
import { useOutcomeLedger, useProfileOutcomeLedger } from '@aether-app/features/intelligence';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item)) : [];
}

function num(value: unknown): number | null {
  if (value == null || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function money(value: unknown, locale: LocaleContext): string {
  const parsed = num(value);
  return parsed == null ? '—' : `$${formatDecimal(parsed, locale, { maximumFractionDigits: 0 })}`;
}

function pct(value: unknown): string {
  const parsed = num(value);
  return parsed == null ? '—' : `${Math.round(parsed * 100)}%`;
}

/** Full: as many tiles per row as fit. Value: the four value tiles as a 2×2 block. */
const KPI_GRID = { gridTemplateColumns: 'repeat(auto-fit, minmax(min(140px, 100%), 1fr))' } as const;
const KPI_GRID_2 = { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' } as const;
const mute = { color: 'var(--ae-mute)' } as const;

/**
 * Outcome ledger: value, capture and loop health from recommendations →
 * decisions → actions → outcomes, in the glass card style.
 *
 * `variant="value"` drops the loop counts, outcome mix and loop health — used
 * on the Value page's Outcomes tab, which already draws those from the same
 * ledger — and keeps the value figures, confidence change and top lists.
 */
export function OutcomeLedgerPanel({ entityId, variant = 'full' }: { readonly entityId?: string; readonly variant?: 'full' | 'value' }) {
  const timeCtx = useTimeContext();
  const tenantLedger = useOutcomeLedger();
  const entityLedger = useProfileOutcomeLedger(entityId ?? '');
  const ledger = entityId ? entityLedger : tenantLedger;
  const data = asRecord(ledger.data);
  const summary = asRecord(data.summary);
  const byType = asList(data.by_recommendation_type).slice(0, 4);
  const byPlaybook = asList(data.by_playbook).slice(0, 4);
  const confidence = asList(data.confidence_deltas_over_time);
  const full = variant === 'full';

  return (
    <section className="ae-card flex min-w-0 flex-col gap-3.5 rounded-[20px] px-5 py-[18px]" data-testid="outcome-ledger-panel">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <Eyebrow>Outcome Ledger{entityId ? ' for entity' : ''}</Eyebrow>
          <span className="text-[12px] leading-snug" style={mute}>
            Value, capture, and loop health from recommendations → decisions → actions → outcomes.
          </span>
        </div>
        <TonePill tone="blue" className="flex-none">ROI</TonePill>
      </div>

      {ledger.isLoading ? (
        <div className="flex items-center gap-2.5 py-3 text-[13px]" style={mute} role="status">
          <Spinner size={16} />
          Loading the outcome ledger
        </div>
      ) : null}
      {ledger.error ? (
        <div className="flex flex-col items-start gap-2">
          <InlineNotice tone="amber">Outcome ledger unavailable right now.</InlineNotice>
          <button type="button" onClick={() => ledger.refetch()} className="ae-btn-secondary ae-focus px-3.5 py-1.5 text-[12px]">Retry</button>
        </div>
      ) : null}
      {!ledger.isLoading && !ledger.error && !ledger.data ? (
        <p className="text-[13px]" style={mute} data-state="empty">No outcome evidence has been recorded.</p>
      ) : null}

      {!ledger.isLoading && !ledger.error && !!ledger.data && (
        <>
          <div className="grid gap-2.5" style={full ? KPI_GRID : KPI_GRID_2}>
            <MetricTile label="Observed value" value={money(summary.observed_value, timeCtx)} />
            <MetricTile label="Expected value" value={money(summary.expected_value, timeCtx)} />
            <MetricTile label="Pending value" value={money(summary.pending_value, timeCtx)} />
            <MetricTile label="Outcome capture" value={pct(summary.outcome_capture_rate)} />
            {full && (
              <>
                <MetricTile label="Recommendations" value={String(num(summary.recommendations_generated) ?? '—')} />
                <MetricTile label="Decisions" value={String(num(summary.decisions_recorded) ?? '—')} />
                <MetricTile label="Actions" value={String(num(summary.actions_logged) ?? '—')} />
                <MetricTile label="Outcomes" value={String(num(summary.outcomes_observed) ?? '—')} />
              </>
            )}
          </div>

          <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))' }}>
            {full && (
              <LedgerBox title="Outcome mix">
                <div className="flex flex-wrap gap-1.5">
                  <TonePill tone="sage">Success {pct(summary.success_rate)}</TonePill>
                  <TonePill tone="ember">Failure {pct(summary.failure_rate)}</TonePill>
                  <TonePill tone="mute">Neutral {pct(summary.neutral_rate)}</TonePill>
                </div>
              </LedgerBox>
            )}
            {full && (
              <LedgerBox title="Loop health">
                <span className="text-[12px]" style={mute}>
                  {num(summary.stale_loops) ?? '—'} stale · {num(summary.incomplete_loops) ?? '—'} incomplete · {num(summary.failed_loops) ?? '—'} failed
                </span>
              </LedgerBox>
            )}
            <LedgerBox title="Confidence change">
              <span className="text-[12px]" style={mute}>
                {num(summary.confidence_delta_total)?.toFixed(2) ?? '—'} total delta across {confidence.length} updates
              </span>
            </LedgerBox>
          </div>

          <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(260px, 100%), 1fr))' }}>
            {full && <LedgerList title="Top recommendation types" items={byType} empty="No recommendation type value yet." />}
            <LedgerList title="Top playbooks" items={byPlaybook} empty="No playbook-linked value yet." playbook />
          </div>
        </>
      )}
    </section>
  );
}

function LedgerBox({ title, children }: { readonly title: string; readonly children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-[14px] px-3.5 py-3" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
      <span className="text-[13px] font-medium">{title}</span>
      {children}
    </div>
  );
}

function LedgerList({ title, items, empty, playbook = false }: { readonly title: string; readonly items: Array<Record<string, unknown>>; readonly empty: string; readonly playbook?: boolean }) {
  const timeCtx = useTimeContext();
  return (
    <LedgerBox title={title}>
      {items.length === 0 ? <span className="text-[12px]" style={mute}>{empty}</span> : (
        <div className="flex flex-col">
          {items.map((item) => (
            <div key={String(playbook ? item.playbook_id : item.key)} className="flex items-center justify-between gap-3 border-t py-1.5 text-[12px]" style={{ borderColor: 'var(--ae-edge)' }}>
              <span className="truncate" style={mute}>{String(playbook ? item.playbook_name : item.key)}</span>
              <span className="ae-mono">{money(item.observed_value, timeCtx)}</span>
            </div>
          ))}
        </div>
      )}
    </LedgerBox>
  );
}
