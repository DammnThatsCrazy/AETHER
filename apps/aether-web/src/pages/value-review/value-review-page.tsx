import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { EmptyState, LoadingState } from '@aether/ui';
import { ChoiceChip } from '@aether-app/components/ae-ui';
import { api } from '@aether-app/lib/api/endpoints';
import { WINDOWS, asRecord, str, type Row, type WindowDays } from './value-model';
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

function isTab(value: string | null): value is TabKey {
  return TABS.some(t => t.key === value);
}

function isWindow(value: number): value is WindowDays {
  return (WINDOWS as readonly number[]).includes(value);
}

/**
 * Value (Claude Design handoff: Aether Value). Tenant value review, value
 * events, the outcome ledger and campaign overviews — each tab is a real read
 * and says plainly when the backend has nothing for it. The 7/30/90-day window
 * is offered only where the backend honours a time range (campaign overviews).
 */
export function ValueReviewPage() {
  const [params, setParams] = useSearchParams();
  const rawTab = params.get('tab');
  const tab: TabKey = isTab(rawTab) ? rawTab : 'overview';
  const rawWindow = Number(params.get('window'));
  const days: WindowDays = isWindow(rawWindow) ? rawWindow : 30;

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

  const update = (next: Record<string, string>) => {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) merged.set(k, v);
    setParams(merged, { replace: true });
  };

  if (loading) return <div className="p-6"><LoadingState lines={6} /></div>;
  if (error) return <div className="p-6"><EmptyState title="Unable to load Value Review" description={error} /></div>;
  if (!data || Object.keys(data).length === 0) {
    return <div className="p-6"><EmptyState title="No value evidence yet" description="Value review will appear after outcomes are observed." /></div>;
  }

  const tenant = str(data['tenant_id']) ?? 'tenant';

  return (
    <div className="flex min-w-0 flex-col gap-[18px]" data-testid="aether-value">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex max-w-[640px] flex-col gap-1">
          <h1 className="text-[32px] font-medium leading-tight tracking-[-0.64px]">Value</h1>
          <span className="text-[14px]" style={{ color: 'var(--ae-mute)' }}>
            Value created, what produced it, and what is still open before your next review. Influence is observed, not proven causal.
          </span>
        </div>
        {tab === 'campaigns' && (
          <div className="flex flex-col items-end gap-1">
            <div className="flex gap-1" role="group" aria-label="Campaign spend window">
              {WINDOWS.map(w => (
                <ChoiceChip key={w} size="sm" selected={days === w} onClick={() => update({ window: String(w) })} data-testid={`value-window-${w}`}>
                  {w} days
                </ChoiceChip>
              ))}
            </div>
            <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>window for campaign spend</span>
          </div>
        )}
      </div>

      <div className="ae-scroll-none -mx-1 flex gap-1.5 overflow-x-auto px-1" role="group" aria-label="Value views">
        {TABS.map(t => (
          <ChoiceChip key={t.key} selected={tab === t.key} onClick={() => update({ tab: t.key })} data-testid={`value-tab-${t.key}`}>
            {t.label}
          </ChoiceChip>
        ))}
      </div>

      <div className="ae-rise" key={tab}>
        {tab === 'overview' && <OverviewTab tenant={tenant} review={data} />}
        {tab === 'sources' && <SourcesTab tenant={tenant} />}
        {tab === 'campaigns' && <CampaignsTab tenant={tenant} days={days} />}
        {tab === 'agents' && <AgentsValueTab />}
        {tab === 'customers' && <CustomersTab tenant={tenant} />}
        {tab === 'outcomes' && <OutcomesTab tenant={tenant} />}
      </div>
    </div>
  );
}
