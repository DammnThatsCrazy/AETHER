import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useConversionExplorer } from '@kyber/features/measurement';
import { useState } from 'react';

type Row = Record<string, unknown>;

interface ConversionFilters {
  profile_id: string;
  campaign_id: string;
  cluster_id: string;
  attribution_run_id: string;
  channel: string;
  conversion_type: string;
}

const EMPTY_FILTERS: ConversionFilters = { profile_id: '', campaign_id: '', cluster_id: '', attribution_run_id: '', channel: '', conversion_type: '' };

export function ConversionExplorerPage() {
  const [filters, setFilters] = useState<ConversionFilters>(EMPTY_FILTERS);
  const [submitted, setSubmitted] = useState<ConversionFilters>(EMPTY_FILTERS);

  const { data, loading, error } = useConversionExplorer({
    ...(submitted.profile_id ? { profile_id: submitted.profile_id } : {}),
    ...(submitted.campaign_id ? { campaign_id: submitted.campaign_id } : {}),
    ...(submitted.cluster_id ? { cluster_id: submitted.cluster_id } : {}),
    ...(submitted.attribution_run_id ? { attribution_run_id: submitted.attribution_run_id } : {}),
    ...(submitted.channel ? { channel: submitted.channel } : {}),
    ...(submitted.conversion_type ? { conversion_type: submitted.conversion_type } : {}),
  });

  const hasFilters = Object.values(submitted).some(Boolean);

  function setField(field: keyof ConversionFilters, value: string) {
    setFilters(prev => ({ ...prev, [field]: value }));
  }

  if (loading) return <PageWrapper title="Conversion Explorer"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Conversion Explorer"><ErrorState title="Unable to load conversions" message={error} /></PageWrapper>;

  const conversions = data.conversions as Row[];

  return (
    <PageWrapper
      title="Conversion Explorer"
      subtitle="Canonical conversion ledger — source authority, revenue, deduplication, and attribution linkage."
    >
      <div className="flex gap-2 mb-4 flex-wrap">
        <input value={filters.profile_id} onChange={e => setField('profile_id', e.target.value)}
          placeholder="Profile ID…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-40" />
        <input value={filters.campaign_id} onChange={e => setField('campaign_id', e.target.value)}
          placeholder="Campaign ID…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-40" />
        <input value={filters.cluster_id} onChange={e => setField('cluster_id', e.target.value)}
          placeholder="Cluster ID…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-40" />
        <input value={filters.attribution_run_id} onChange={e => setField('attribution_run_id', e.target.value)}
          placeholder="Attribution run ID…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-44" />
        <input value={filters.channel} onChange={e => setField('channel', e.target.value)}
          placeholder="Channel…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-32" />
        <select value={filters.conversion_type} onChange={e => setField('conversion_type', e.target.value)}
          className="text-sm bg-surface-secondary border border-border rounded px-2 py-1.5">
          <option value="">All types</option>
          <option value="purchase">Purchase</option>
          <option value="lead">Lead</option>
          <option value="signup">Signup</option>
          <option value="trial">Trial</option>
          <option value="subscription">Subscription</option>
          <option value="x402_settlement">x402 Settlement</option>
        </select>
        <button onClick={() => setSubmitted({ ...filters })}
          className="px-4 py-1.5 text-sm bg-accent text-white rounded">
          Filter
        </button>
        {hasFilters && <button onClick={() => { setFilters(EMPTY_FILTERS); setSubmitted(EMPTY_FILTERS); }}
          className="px-4 py-1.5 text-sm border border-border rounded">Clear</button>}
      </div>

      <Card>
        <CardHeader><CardTitle>Canonical conversions</CardTitle></CardHeader>
        <CardContent>
          {conversions.length === 0
            ? <EmptyState title="No conversions found" description="Conversions are projected from commerce events (order_completed, payment_confirmed, x402_settled, etc.)." />
            : <DataTable data={conversions} keyExtractor={r => String(r.conversion_id)} columns={[
                { key: 'id', header: 'Conversion ID', render: r => <span className="font-mono text-xs">{String(r.conversion_id ?? '').slice(0, 8)}…</span> },
                { key: 'type', header: 'Type', render: r => String(r.conversion_type ?? '—') },
                { key: 'status', header: 'Status', render: r => <Badge variant={r.conversion_status === 'confirmed' ? 'success' : r.conversion_status === 'reversed' ? 'danger' : 'default'}>{String(r.conversion_status ?? '—')}</Badge> },
                { key: 'gross', header: 'Gross value', render: r => r.gross_value ? `$${Number(r.gross_value).toFixed(2)}` : '—' },
                { key: 'currency', header: 'Currency', render: r => String(r.currency ?? 'USD') },
                { key: 'authority', header: 'Authority', render: r => String(r.authority_rank ?? 0) },
                { key: 'eligible', header: 'Attribution eligible', render: r => r.attribution_eligible ? <Badge variant="success">Yes</Badge> : <Badge variant="default">No</Badge> },
                { key: 'occurred', header: 'Occurred', render: r => r.occurred_at ? new Date(String(r.occurred_at)).toLocaleDateString() : '—' },
              ]} />
          }
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
