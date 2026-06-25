import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useAttributionStudio } from '@kyber/features/measurement';
import { useState } from 'react';
import { api } from '@kyber/lib/api';

type Row = Record<string, unknown>;

export function AttributionStudioPage() {
  const [filter, setFilter] = useState<{ model_type?: string; status?: string }>({});
  const { data, loading, error } = useAttributionStudio(filter);
  const [triggering, setTriggering] = useState(false);
  const [backfillDates, setBackfillDates] = useState({ start: '', end: '' });

  if (loading) return <PageWrapper title="Attribution Studio"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Attribution Studio"><ErrorState title="Unable to load attribution runs" message={error} /></PageWrapper>;

  const runs = data.runs as Row[];

  const handleBackfill = async () => {
    if (!backfillDates.start || !backfillDates.end) return;
    setTriggering(true);
    try {
      await api.attributionRuns.backfill({ start_date: backfillDates.start, end_date: backfillDates.end });
    } finally {
      setTriggering(false);
    }
  };

  return (
    <PageWrapper
      title="Attribution Studio"
      subtitle="Per-conversion attribution runs, model selection, and backfill controls."
    >
      <div className="flex gap-3 mb-4">
        <label className="sr-only" htmlFor="attr-model-filter">Attribution model</label>
        <select id="attr-model-filter" aria-label="Attribution model" value={filter.model_type ?? ''} onChange={e => setFilter(f => ({ ...f, model_type: e.target.value || undefined } as { model_type?: string; status?: string }))}
          className="text-sm bg-surface-secondary border border-border rounded px-2 py-1">
          <option value="">All models</option>
          <option value="linear">Linear</option>
          <option value="first_touch">First touch</option>
          <option value="last_touch">Last touch</option>
          <option value="time_decay">Time decay</option>
          <option value="position_based">Position based</option>
          <option value="data_driven">Data driven</option>
        </select>
        <label className="sr-only" htmlFor="attr-status-filter">Run status</label>
        <select id="attr-status-filter" aria-label="Run status" value={filter.status ?? ''} onChange={e => setFilter(f => ({ ...f, status: e.target.value || undefined } as { model_type?: string; status?: string }))}
          className="text-sm bg-surface-secondary border border-border rounded px-2 py-1">
          <option value="">All statuses</option>
          <option value="complete">Complete</option>
          <option value="pending">Pending</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      <Card>
        <CardHeader><CardTitle>Attribution runs</CardTitle></CardHeader>
        <CardContent>
          {runs.length === 0
            ? <EmptyState title="No attribution runs" description="Trigger an attribution run via POST /v1/attribution/runs or by importing conversions." />
            : <DataTable data={runs} keyExtractor={r => String(r.attribution_run_id)} columns={[
                { key: 'id', header: 'Run ID', render: r => <span className="font-mono text-xs">{String(r.attribution_run_id ?? '').slice(0, 8)}…</span> },
                { key: 'conversion', header: 'Conversion', render: r => <span className="font-mono text-xs">{String(r.conversion_id ?? '').slice(0, 8)}…</span> },
                { key: 'model', header: 'Model', render: r => String(r.model_type ?? '—') },
                { key: 'status', header: 'Status', render: r => <Badge variant={r.status === 'complete' ? 'success' : r.status === 'failed' ? 'danger' : 'default'}>{String(r.status ?? '—')}</Badge> },
                { key: 'credits', header: 'Credits', render: r => String(r.credit_count ?? 0) },
                { key: 'revenue', header: 'Eligible revenue', render: r => r.eligible_revenue ? `$${Number(r.eligible_revenue).toFixed(2)}` : '—' },
                { key: 'active', header: 'Active', render: r => r.is_active ? <Badge variant="success">Yes</Badge> : <Badge variant="default">No</Badge> },
              ]} />
          }
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader><CardTitle>Schedule backfill</CardTitle></CardHeader>
        <CardContent>
          <div className="flex gap-3 items-end">
            <div>
              <label className="text-xs text-text-muted block mb-1">Start date</label>
              <input type="date" value={backfillDates.start} onChange={e => setBackfillDates(d => ({ ...d, start: e.target.value }))}
                className="text-sm bg-surface-secondary border border-border rounded px-2 py-1" />
            </div>
            <div>
              <label className="text-xs text-text-muted block mb-1">End date</label>
              <input type="date" value={backfillDates.end} onChange={e => setBackfillDates(d => ({ ...d, end: e.target.value }))}
                className="text-sm bg-surface-secondary border border-border rounded px-2 py-1" />
            </div>
            <button onClick={handleBackfill} disabled={triggering || !backfillDates.start || !backfillDates.end}
              className="px-4 py-1.5 text-sm bg-accent text-white rounded disabled:opacity-50">
              {triggering ? 'Scheduling…' : 'Schedule backfill'}
            </button>
          </div>
          <p className="text-xs text-text-muted mt-2">Max 365 days. Runs attribution on all unprocessed conversions in the window.</p>
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
