import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useCampaignIntelligence } from '@kyber/features/measurement';
import { useState } from 'react';

type Row = Record<string, unknown>;

export function CampaignIntelligencePage() {
  const [campaignId, setCampaignId] = useState('');
  const [submitted, setSubmitted] = useState('');
  const { data, loading, error } = useCampaignIntelligence(submitted ? { campaign_id: submitted } : {});

  if (loading) return <PageWrapper title="Campaign Intelligence"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Campaign Intelligence"><ErrorState title="Unable to load campaign intelligence" message={error} /></PageWrapper>;

  const spend = data.spend as Row[];
  const recon = data.reconciliation as Row;

  const totalSpend = spend.reduce((s, r) => s + Number(r.total_cost ?? 0), 0);
  const totalImpressions = spend.reduce((s, r) => s + Number(r.impressions ?? 0), 0);
  const totalClicks = spend.reduce((s, r) => s + Number(r.clicks ?? 0), 0);

  return (
    <PageWrapper
      title="Campaign Intelligence"
      subtitle="Actual spend ledger, ROAS from canonical attribution credits, and spend reconciliation."
    >
      <div className="flex gap-2 mb-4">
        <input value={campaignId} onChange={e => setCampaignId(e.target.value)}
          placeholder="Campaign ID (optional)…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-64" />
        <button onClick={() => setSubmitted(campaignId)} className="px-4 py-1.5 text-sm bg-accent text-white rounded">
          Filter
        </button>
        {submitted && <button onClick={() => { setCampaignId(''); setSubmitted(''); }} className="px-4 py-1.5 text-sm border border-border rounded">Clear</button>}
      </div>

      <div className="grid gap-4 md:grid-cols-3 mb-4">
        <Card><CardContent>
          <div className="text-xs text-text-muted font-mono">Total spend</div>
          <div className="mt-1 text-2xl font-semibold">${totalSpend.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
        </CardContent></Card>
        <Card><CardContent>
          <div className="text-xs text-text-muted font-mono">Impressions</div>
          <div className="mt-1 text-2xl font-semibold">{totalImpressions.toLocaleString()}</div>
        </CardContent></Card>
        <Card><CardContent>
          <div className="text-xs text-text-muted font-mono">Clicks</div>
          <div className="mt-1 text-2xl font-semibold">{totalClicks.toLocaleString()}</div>
        </CardContent></Card>
      </div>

      {recon.days && (
        <Card className="mb-4">
          <CardHeader><CardTitle>Spend reconciliation</CardTitle></CardHeader>
          <CardContent>
            <div className="flex gap-4 text-sm text-text-secondary">
              <span>Coverage: <strong>{String(recon.spend_coverage_pct ?? '—')}%</strong></span>
              <span>Total days: <strong>{String(recon.total_days ?? '—')}</strong></span>
              <span>Days with data: <strong>{String(recon.days_with_data ?? '—')}</strong></span>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Spend records</CardTitle></CardHeader>
        <CardContent>
          {spend.length === 0
            ? <EmptyState title="No spend records" description="Import spend via POST /v1/spend/imports or connect a paid-media connector." />
            : <DataTable data={spend} keyExtractor={r => String(r.spend_record_id)} columns={[
                { key: 'platform', header: 'Platform', render: r => String(r.platform ?? '—') },
                { key: 'campaign', header: 'Campaign', render: r => <span className="font-mono text-xs">{String(r.campaign_id ?? '—').slice(0, 12)}…</span> },
                { key: 'period', header: 'Period', render: r => `${r.period_start ? new Date(String(r.period_start)).toLocaleDateString() : '—'}` },
                { key: 'spend', header: 'Spend', render: r => `$${Number(r.total_cost ?? 0).toFixed(2)}` },
                { key: 'impressions', header: 'Impressions', render: r => Number(r.impressions ?? 0).toLocaleString() },
                { key: 'clicks', header: 'Clicks', render: r => Number(r.clicks ?? 0).toLocaleString() },
                { key: 'currency', header: 'Currency', render: r => String(r.billing_currency ?? 'USD') },
              ]} />
          }
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
