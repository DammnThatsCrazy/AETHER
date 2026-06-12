import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, unknown>;

function Metric({ label, value }: { readonly label: string; readonly value: unknown }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? 0)}</div>
      </CardContent>
    </Card>
  );
}

function statusColor(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'healthy') return 'success';
  if (status === 'degraded') return 'warning';
  if (status === 'failed') return 'danger';
  return 'default';
}

function formatTs(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

interface TypeRow {
  readonly connector_type: string;
  readonly label: string;
  readonly category: string;
  readonly supports_pull: boolean;
  readonly supports_webhook: boolean;
  readonly enabled_tenants: number;
  readonly status_breakdown: Record<string, number>;
  readonly last_synced_at: string | null;
}

export function ConnectorsPage() {
  const [data, setData] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.admin.kyber.connectorsOverview()
      .then((d) => setData(d as AnyRecord))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <PageWrapper title="Connector Health"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Connector Health"><EmptyState title="Unable to load connector health" description={error} /></PageWrapper>;

  const d = data ?? {};
  const byType = (d.enabled_by_type ?? {}) as Record<string, number>;
  const byStatus = (d.enabled_by_status ?? {}) as Record<string, number>;
  const typeDetail = (d.by_type_detail ?? []) as TypeRow[];

  return (
    <PageWrapper
      title="Connector Health"
      subtitle="Aggregate, tenant-anonymous view of non-SDK connector ingestion across all tenants. No raw tenant configs or secrets are shown."
    >
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Available connectors" value={d.available_connectors} />
        <Metric label="Configured" value={d.configured_count} />
        <Metric label="Enabled" value={d.enabled_count} />
        <Metric label="Active types" value={Object.keys(byType).length} />
      </div>

      <Card>
        <CardHeader><CardTitle>Status breakdown</CardTitle></CardHeader>
        <CardContent className="text-xs font-mono">
          {Object.keys(byStatus).length === 0 ? <EmptyState title="No enabled connectors" /> : (
            <div className="grid gap-1 md:grid-cols-3">
              {Object.entries(byStatus).map(([s, n]) => (
                <div key={s} className="flex justify-between rounded border border-border-default px-2 py-1">
                  <Badge variant={statusColor(s)}>{s}</Badge>
                  <span>{n}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Per-connector health</CardTitle></CardHeader>
        <CardContent>
          {typeDetail.length === 0 ? <EmptyState title="No connector data" /> : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono border-collapse">
                <thead>
                  <tr className="border-b border-border-default text-text-muted">
                    <th className="py-2 px-2 text-left">Connector</th>
                    <th className="py-2 px-2 text-left">Category</th>
                    <th className="py-2 px-2 text-left">Mode</th>
                    <th className="py-2 px-2 text-right">Enabled tenants</th>
                    <th className="py-2 px-2 text-left">Status</th>
                    <th className="py-2 px-2 text-left">Last synced</th>
                  </tr>
                </thead>
                <tbody>
                  {typeDetail.map((row) => {
                    const STATUS_SEVERITY: Record<string, number> = { failed: 3, degraded: 2, never_synced: 1, healthy: 0 };
                    const worstStatus = Object.keys(row.status_breakdown).sort((a, b) => (STATUS_SEVERITY[b] ?? 0) - (STATUS_SEVERITY[a] ?? 0))[0] ?? 'never_synced';
                    const dominantStatus = worstStatus;
                    return (
                      <tr key={row.connector_type} className="border-b border-border-subtle hover:bg-surface-hover">
                        <td className="py-2 px-2 font-semibold text-text-primary">{row.label}</td>
                        <td className="py-2 px-2 text-text-muted">{row.category}</td>
                        <td className="py-2 px-2">
                          {row.supports_pull && <Badge variant="default">pull</Badge>}
                          {row.supports_webhook && <Badge variant="default">webhook</Badge>}
                        </td>
                        <td className="py-2 px-2 text-right">{row.enabled_tenants}</td>
                        <td className="py-2 px-2">
                          {row.enabled_tenants === 0
                            ? <span className="text-text-muted">—</span>
                            : <Badge variant={statusColor(dominantStatus)}>{dominantStatus}</Badge>}
                        </td>
                        <td className="py-2 px-2 text-text-muted">{formatTs(row.last_synced_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
