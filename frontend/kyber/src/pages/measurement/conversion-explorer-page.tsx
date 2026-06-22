import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useConversionExplorer } from '@kyber/features/measurement';
import { useState } from 'react';

type Row = Record<string, unknown>;

export function ConversionExplorerPage() {
  const [profileId, setProfileId] = useState('');
  const [convType, setConvType] = useState('');
  const [submitted, setSubmitted] = useState({ profile_id: '', conversion_type: '' });

  const { data, loading, error } = useConversionExplorer({
    profile_id: submitted.profile_id || undefined,
    conversion_type: submitted.conversion_type || undefined,
  });

  if (loading) return <PageWrapper title="Conversion Explorer"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Conversion Explorer"><ErrorState title="Unable to load conversions" message={error} /></PageWrapper>;

  const conversions = data.conversions as Row[];

  return (
    <PageWrapper
      title="Conversion Explorer"
      subtitle="Canonical conversion ledger — source authority, revenue, deduplication, and attribution linkage."
    >
      <div className="flex gap-2 mb-4 flex-wrap">
        <input value={profileId} onChange={e => setProfileId(e.target.value)}
          placeholder="Profile ID…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-48" />
        <select value={convType} onChange={e => setConvType(e.target.value)}
          className="text-sm bg-surface-secondary border border-border rounded px-2 py-1.5">
          <option value="">All types</option>
          <option value="purchase">Purchase</option>
          <option value="lead">Lead</option>
          <option value="signup">Signup</option>
          <option value="trial">Trial</option>
          <option value="subscription">Subscription</option>
          <option value="x402_settlement">x402 Settlement</option>
        </select>
        <button onClick={() => setSubmitted({ profile_id: profileId, conversion_type: convType })}
          className="px-4 py-1.5 text-sm bg-accent text-white rounded">
          Filter
        </button>
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
