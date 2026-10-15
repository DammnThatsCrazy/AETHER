import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState, formatCount, useTimeContext, type TimeContext } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

type Row = Record<string, any>;
const number = (v: unknown, ctx: TimeContext) => v == null ? '—' : formatCount(Number(v), ctx);
const money = (v: unknown, ctx: TimeContext) => v == null ? '—' : `$${formatCount(Number(v), ctx)}`;
const pct = (v: unknown) => v == null ? '—' : `${Math.round(Number(v) * 100)}%`;
function Metric({ label, value }: { readonly label: string; readonly value: any }) { return <Card><CardContent className="p-4"><div className="text-xs text-text-muted font-mono">{label}</div><div className="text-2xl font-semibold text-text-primary">{value}</div></CardContent></Card>; }
function List({ title, items }: { readonly title: string; readonly items: string[] }) { return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent>{items.length ? <ul className="list-disc pl-5 text-sm text-text-secondary">{items.map(item => <li key={item}>{item}</li>)}</ul> : <div className="text-sm text-text-muted">No open items.</div>}</CardContent></Card>; }

export function ValueReviewPage() {
  const timeCtx = useTimeContext();
  const [data, setData] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await api.valueReview.overview();
        if (active) setData(response as Row);
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, []);
  if (loading) return <div className="p-6"><LoadingState lines={6} /></div>;
  if (error) return <div className="p-6"><EmptyState title="Unable to load Value Review" description={error} /></div>;
  if (!data || Object.keys(data).length === 0) return <div className="p-6"><EmptyState title="No value evidence yet" description="Value review will appear after outcomes are observed." /></div>;
  return <div className="space-y-5 p-6"><div><h1 className="text-xl font-bold text-text-primary font-mono">Value Review</h1><p className="text-sm text-text-secondary">A tenant-scoped view of value created, open gaps, and next steps before EBRs and renewals.</p></div>
    <div className="grid gap-3 md:grid-cols-4"><Metric label="Value Created" value={money(data?.observed_value, timeCtx)} /><Metric label="Expected Value" value={money(data?.expected_value, timeCtx)} /><Metric label="Pending Value" value={money(data?.pending_value, timeCtx)} /><Metric label="Outcome Capture" value={pct(data?.outcome_capture_rate)} /></div>
    <div className="grid gap-4 md:grid-cols-3"><Metric label="Recommendations Acted Upon" value={number(data.recommendations_acted_upon, timeCtx)} /><Metric label="Outcomes Observed" value={number(data.outcomes_observed, timeCtx)} /><Metric label="Incomplete Loops" value={number(data.incomplete_loops, timeCtx)} /></div>
    <div className="grid gap-4 lg:grid-cols-2"><List title="Recommended Next Steps" items={data?.recommended_next_steps ?? []} /><List title="Setup Gaps" items={data?.setup_gaps ?? []} /><List title="Integration Gaps" items={data?.integration_gaps ?? []} /><List title="Top Playbooks" items={(data?.top_playbooks ?? []).map((p: any) => String(p.name ?? p.playbook_id ?? p))} /></div>
  </div>;
}
