import { useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  ErrorState,
  LoadingState,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api/endpoints';

type Row = Record<string, unknown>;
type AnyData = Record<string, unknown>;

interface RightsOpsData {
  reconciliation: AnyData;
  impacts: Row[];
}

function text(value: unknown): string {
  return value === null || value === undefined || value === '' ? '—' : String(value);
}

function rows(value: unknown): Row[] {
  if (!value || typeof value !== 'object') return [];
  const items = (value as { items?: unknown }).items;
  return Array.isArray(items) ? items.filter((item): item is Row => Boolean(item && typeof item === 'object')) : [];
}

function statusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (['completed', 'delivered', 'healthy', 'no_rightsless_rows_found'].includes(status)) return 'success';
  if (['blocked', 'evidence_required', 'failed'].includes(status)) return 'danger';
  return 'warning';
}

function Status({ value }: { readonly value: unknown }) {
  const status = text(value);
  return <Badge variant={statusVariant(status)}>{status}</Badge>;
}

export function RightsOperationsPage() {
  const [data, setData] = useState<RightsOpsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const [reconciliation, impacts] = await Promise.all([
      api.rightsAuthority.reconciliation(),
      api.rightsAuthority.impacts(),
    ]);
    setData({
      reconciliation: (reconciliation && typeof reconciliation === 'object' ? reconciliation : {}) as AnyData,
      impacts: rows(impacts),
    });
  }

  useEffect(() => {
    let active = true;
    void load().catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : 'Rights authority unavailable');
    });
    return () => { active = false; };
  }, []);

  async function execute(impactGraphId: string) {
    setRunning(impactGraphId);
    setMessage(null);
    try {
      const result = await api.rightsAuthority.executeImpact(impactGraphId);
      setMessage(`Remediation ${impactGraphId}: ${text((result as AnyData).status)}`);
      await load();
    } catch (cause: unknown) {
      setMessage(cause instanceof Error ? cause.message : 'Remediation request failed');
    } finally {
      setRunning(null);
    }
  }

  if (error) {
    return <PageWrapper title="Rights Operations"><ErrorState title="Rights authority unavailable" message={error} /></PageWrapper>;
  }
  if (!data) return <PageWrapper title="Rights Operations"><LoadingState lines={8} /></PageWrapper>;

  const totals = (data.reconciliation.totals ?? {}) as AnyData;
  const migration = (data.reconciliation.migration ?? {}) as AnyData;
  return (
    <PageWrapper
      title="Rights Operations"
      subtitle="Internal Kyber view of rights reconciliation and remediation. This surface is operator-only; it never changes what an Aether tenant sees."
    >
      {message && <div className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">{message}</div>}
      <div className="grid gap-3 md:grid-cols-4">
        <Card><CardContent><p className="text-xs text-text-muted font-mono">Rows scanned</p><p className="text-2xl font-semibold text-text-primary mt-1">{text(totals.rows_scanned)}</p></CardContent></Card>
        <Card><CardContent><p className="text-xs text-text-muted font-mono">Rights attached</p><p className="text-2xl font-semibold text-text-primary mt-1">{text(totals.rights_attached)}</p></CardContent></Card>
        <Card><CardContent><p className="text-xs text-text-muted font-mono">Rightsless</p><p className="text-2xl font-semibold text-text-primary mt-1">{text(totals.rightsless)}</p></CardContent></Card>
        <Card><CardContent><p className="text-xs text-text-muted font-mono">Authority mode</p><p className="text-2xl font-semibold text-text-primary mt-1">{text(data.reconciliation.rights_mode)}</p></CardContent></Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Migration reconciliation</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          <div className="flex items-center gap-3"><span className="text-sm text-text-secondary">Status</span><Status value={migration.status} /></div>
          <p className="text-xs text-text-muted">{text(migration.next_action)}</p>
          <p className="text-[11px] text-text-muted font-mono">Mutation performed: {text(migration.mutation_performed)}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Impact remediation</CardTitle></CardHeader>
        <CardContent>
          <DataTable
            data={data.impacts}
            keyExtractor={row => text(row.impact_graph_id ?? row.id ?? 'impact')}
            columns={[
              { key: 'impact', header: 'Impact graph', render: row => <span className="font-mono text-xs">{text(row.impact_graph_id ?? row.id)}</span> },
              { key: 'tenant', header: 'Tenant', render: row => <span className="font-mono text-xs">{text(row.tenant_id)}</span> },
              { key: 'status', header: 'Status', render: row => <Status value={row.status} /> },
              { key: 'action', header: '', render: row => {
                const id = text(row.impact_graph_id ?? row.id);
                return id === '—' ? null : <Button size="sm" variant="ghost" disabled={running === id} onClick={() => { void execute(id); }}>{running === id ? 'Running…' : 'Execute remediation'}</Button>;
              } },
            ]}
            emptyMessage="No rights impacts recorded"
          />
          <p className="mt-3 text-xs text-text-muted">An absent storage/search/vector/model adapter remains blocked and is reported as such. The control never fabricates completion.</p>
        </CardContent>
      </Card>
    </PageWrapper>
  );
}

export default RightsOperationsPage;
