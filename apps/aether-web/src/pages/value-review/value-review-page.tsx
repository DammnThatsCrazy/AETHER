import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { EmptyState, LoadingState } from '@aether/ui';
import { SegmentedTabs } from '@aether-app/components/ae-campaigns-geo-ui';
import { api } from '@aether-app/lib/api/endpoints';
import { WINDOWS, asRecord, rangeLabel, str, valueWindows, type Row, type WindowDays } from './value-model';
import { LoopAndDecisionsSection } from './value-loop-section';
import { AgentsValueTab, CampaignsTab, CustomersTab, OutcomesTab, OverviewTab, SourcesTab } from './value-tabs';

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'sources', label: 'Sources' },
  { key: 'campaigns', label: 'Campaigns' },
  { key: 'agents', label: 'Agents' },
  { key: 'customers', label: 'Customers' },
  { key: 'outcomes', label: 'Outcomes' },
] as const;
type TabKey = (typeof TABS)[number]['key'];

/** Tabs whose reads take no date range: they say "all time" instead of following the window. */
const ALL_TIME_TABS: ReadonlySet<TabKey> = new Set(['customers', 'outcomes']);

/** Per-tab copy for the shared review states, so the title and tabs stay put. */
const EMPTY_COPY: Record<TabKey, string> = {
  overview: 'Value review will appear after outcomes are observed.',
  sources: 'Sources appear here once outcomes, playbooks or integration actions report value.',
  campaigns: 'Campaign spend against value appears here once value is observed for this workspace.',
  agents: 'Agent-completed value appears here once value is observed for this workspace.',
  customers: 'Customers appear here when an outcome with a value is recorded against them.',
  outcomes: 'The loop from recommendation to outcome appears here once outcomes are observed.',
};

function isTab(value: string | null): value is TabKey {
  return TABS.some(t => t.key === value);
}

function isWindow(value: number): value is WindowDays {
  return (WINDOWS as readonly number[]).includes(value);
}

function CompareToggle({ on, onChange }: { readonly on: boolean; readonly onChange: (next: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      data-testid="value-compare"
      className="ae-focus inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[13px] transition-colors"
      style={{
        borderColor: on ? 'var(--ae-blue)' : 'var(--ae-edge)',
        background: on ? 'var(--ae-blue-tint)' : 'transparent',
        color: on ? 'var(--ae-blue-ink)' : 'var(--ae-ink)',
      }}
    >
      <span className="relative inline-block h-4 w-7 flex-none rounded-full transition-colors" style={{ background: on ? 'var(--ae-blue)' : 'var(--ae-edge)' }} aria-hidden="true">
        <span className="absolute top-0.5 h-3 w-3 rounded-full transition-all" style={{ left: on ? 14 : 2, background: 'var(--ae-raised)' }} />
      </span>
      Compare previous
    </button>
  );
}

/**
 * Value (Claude Design handoff: Aether Value). Tenant value review, value
 * events, the outcome ledger and campaign overviews — each tab is a real read
 * and says plainly when the backend has nothing for it. One page-wide
 * 7/30/90-day window scopes every read that accepts a period (value events,
 * campaign overviews); the outcome-ledger tabs say "all time".
 */
export function ValueReviewPage() {
  const [params, setParams] = useSearchParams();
  const rawTab = params.get('tab');
  const tab: TabKey = isTab(rawTab) ? rawTab : 'overview';
  const rawWindow = Number(params.get('window'));
  const days: WindowDays = isWindow(rawWindow) ? rawWindow : 30;
  const compare = params.get('compare') === '1';
  // One anchor per visit, so the current and previous windows (and their cache keys) stay put.
  const [anchor] = useState(() => new Date());
  const windows = useMemo(() => valueWindows(days, anchor), [days, anchor]);

  const [data, setData] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await api.valueReview.overview();
        if (active) setData(asRecord(response));
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  const update = (next: Record<string, string | null>) => {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) merged.delete(k);
      else merged.set(k, v);
    }
    setParams(merged, { replace: true });
  };

  const review = data && Object.keys(data).length > 0 ? data : null;
  const tenant = str(review?.['tenant_id']) ?? 'tenant';
  // Compare previous feeds the Overview's tiles and chart; other tabs do not show deltas.
  const comparing = compare && tab === 'overview';
  const allTime = ALL_TIME_TABS.has(tab);

  let body: ReactNode;
  if (loading) {
    body = <LoadingState lines={6} />;
  } else if (error) {
    body = <EmptyState title="Unable to load Value Review" description={error} />;
  } else if (!review) {
    body = <EmptyState title="No value evidence yet" description={EMPTY_COPY[tab]} />;
  } else {
    body = (
      <>
        {tab === 'overview' && <OverviewTab tenant={tenant} review={review} period={windows.current} previousPeriod={windows.previous} compare={comparing} />}
        {tab === 'sources' && <SourcesTab tenant={tenant} period={windows.current} />}
        {tab === 'campaigns' && <CampaignsTab tenant={tenant} period={windows.current} />}
        {tab === 'agents' && <AgentsValueTab />}
        {tab === 'customers' && <CustomersTab tenant={tenant} />}
        {tab === 'outcomes' && (
          <div className="flex min-w-0 flex-col gap-[18px]">
            <OutcomesTab tenant={tenant} />
            <LoopAndDecisionsSection />
          </div>
        )}
      </>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-[18px]" data-testid="aether-value">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex max-w-[560px] flex-col gap-1">
          <h1 className="text-[32px] font-medium leading-tight tracking-[-0.64px]">Value</h1>
          <span className="text-[14px]" style={{ color: 'var(--ae-mute)' }}>
            Value created, what produced it, and what is still open before your next review. Influence is observed, not proven causal.
          </span>
        </div>
        <div className="flex min-w-0 flex-col items-start gap-1.5 sm:items-end">
          <div className="flex flex-wrap items-center gap-2">
            {tab === 'overview' && <CompareToggle on={compare} onChange={next => update({ compare: next ? '1' : null })} />}
            <SegmentedTabs
              label="Value window"
              value={String(days)}
              onChange={v => update({ window: v })}
              options={WINDOWS.map(w => ({ value: String(w), label: `${w} days`, testId: `value-window-${w}` }))}
            />
          </div>
          <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }} data-testid="value-range">
            {rangeLabel(windows.current)}
            {comparing ? ` · vs ${rangeLabel(windows.previous)}` : ''}
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <SegmentedTabs
          label="Value views"
          value={tab}
          onChange={key => update({ tab: key })}
          options={TABS.map(t => ({ value: t.key, label: t.label, testId: `value-tab-${t.key}` }))}
          className="self-start"
        />
        {allTime && (
          <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }} data-testid="value-scope-all-time">
            All time. The outcome ledger takes no date range, so the {days}-day window does not apply to this view.
          </span>
        )}
      </div>

      <div className="ae-rise min-w-0" key={tab}>
        {body}
      </div>
    </div>
  );
}
