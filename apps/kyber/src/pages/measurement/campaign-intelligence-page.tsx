import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState, formatCount, formatCurrency, formatDecimal, formatDate, useTimeContext } from '@aether/ui';
import type { LocaleContext } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useCampaignIntelligence } from '@kyber/features/measurement';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

type Row = Record<string, unknown>;

// Render a spend ledger amount in the row's OWN billing currency (never a
// hardcoded "$"), and honestly show "—" when the amount is absent rather than
// coercing a missing value to a zero-dollar figure.
function fmtSpend(amount: unknown, currency: unknown, ctx: LocaleContext): string {
  if (amount === null || amount === undefined || amount === '') return '—';
  const n = Number(amount);
  if (!Number.isFinite(n)) return '—';
  const code = typeof currency === 'string' && currency.trim() ? currency.trim() : 'USD';
  return formatCurrency(n, code, ctx);
}

export function CampaignIntelligencePage() {
  const [campaignId, setCampaignId] = useState('');
  const [submitted, setSubmitted] = useState('');
  const navigate = useNavigate();
  const { data, loading, error } = useCampaignIntelligence(submitted ? { campaign_id: submitted } : {});
  const timeCtx = useTimeContext();

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
          <div className="mt-1 text-2xl font-semibold">${formatDecimal(totalSpend, timeCtx, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
        </CardContent></Card>
        <Card><CardContent>
          <div className="text-xs text-text-muted font-mono">Impressions</div>
          <div className="mt-1 text-2xl font-semibold">{formatCount(totalImpressions, timeCtx)}</div>
        </CardContent></Card>
        <Card><CardContent>
          <div className="text-xs text-text-muted font-mono">Clicks</div>
          <div className="mt-1 text-2xl font-semibold">{formatCount(totalClicks, timeCtx)}</div>
        </CardContent></Card>
      </div>

      {!!recon.days && (
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
                { key: 'period', header: 'Period', render: r => `${r.period_start ? formatDate(String(r.period_start), timeCtx) : '—'}` },
                { key: 'spend', header: 'Spend', render: r => fmtSpend(r.total_cost, r.billing_currency, timeCtx) },
                { key: 'impressions', header: 'Impressions', render: r => formatCount(Number(r.impressions ?? 0), timeCtx) },
                { key: 'clicks', header: 'Clicks', render: r => formatCount(Number(r.clicks ?? 0), timeCtx) },
                { key: 'currency', header: 'Currency', render: r => String(r.billing_currency ?? 'USD') },
                { key: 'actions', header: '', render: r => r.campaign_id
                  ? <button onClick={() => navigate(`/measurement/campaigns/${r.campaign_id}`)} className="text-xs text-accent hover:underline whitespace-nowrap">Campaign 360 →</button>
                  : null
                },
              ]} />
          }
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
