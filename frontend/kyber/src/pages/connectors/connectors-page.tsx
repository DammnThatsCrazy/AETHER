import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState, StatusIndicator } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, unknown>;

interface TypeDetail {
  enabled_count: number;
  error_count: number;
  last_synced_at: string | null;
}

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

function formatLastSync(iso: string | null): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3600000);
  if (h < 1) return 'just now';
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function connectorHealth(detail: TypeDetail): 'healthy' | 'degraded' | 'unknown' {
  if (detail.enabled_count === 0) return 'unknown';
  if (detail.error_count > 0) return 'degraded';
  if (!detail.last_synced_at) return 'unknown';
  return 'healthy';
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
  const byTypeDetail = (d.by_type_detail ?? {}) as Record<string, TypeDetail>;

  const allTypes = Array.from(new Set([
    ...Object.keys(byTypeDetail),
    ...Object.keys(byType),
  ])).sort();

  return (
    <PageWrapper
      title="Connector Health"
      subtitle="Aggregate, tenant-anonymous view of non-SDK connector ingestion across all tenants. No raw tenant configs or secrets are shown."
    >
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Available connectors" value={d.available_connectors} />
        <Metric label="Configured" value={d.configured_count} />
        <Metric label="Enabled" value={d.enabled_count} />
        <Metric label="Enabled types" value={Object.keys(byType).length} />
      </div>

      {allTypes.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Per-connector breakdown</CardTitle></CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="text-left text-text-muted border-b border-border-default">
                    <th className="pb-2 pr-4 font-normal">Connector</th>
                    <th className="pb-2 pr-4 font-normal">Status</th>
                    <th className="pb-2 pr-4 font-normal text-right">Enabled</th>
                    <th className="pb-2 pr-4 font-normal text-right">Errors</th>
                    <th className="pb-2 font-normal">Last sync</th>
                  </tr>
                </thead>
                <tbody>
                  {allTypes.map(ctype => {
                    const detail: TypeDetail = byTypeDetail[ctype] ?? { enabled_count: 0, error_count: 0, last_synced_at: null };
                    const health = connectorHealth(detail);
                    return (
                      <tr key={ctype} className="border-b border-border-default/50 last:border-0">
                        <td className="py-2 pr-4">
                          <span className="text-text-primary capitalize">{ctype.replace(/-/g, ' ')}</span>
                        </td>
                        <td className="py-2 pr-4">
                          <span className="flex items-center gap-1.5">
                            <StatusIndicator status={health} />
                            <span className="text-text-secondary">{health}</span>
                          </span>
                        </td>
                        <td className="py-2 pr-4 text-right text-text-secondary">{detail.enabled_count}</td>
                        <td className="py-2 pr-4 text-right">
                          {detail.error_count > 0
                            ? <Badge variant="danger" size="sm">{detail.error_count}</Badge>
                            : <span className="text-text-muted">0</span>
                          }
                        </td>
                        <td className="py-2 text-text-secondary">{formatLastSync(detail.last_synced_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Enabled by status</CardTitle></CardHeader>
        <CardContent className="text-xs font-mono">
          {Object.keys(byStatus).length === 0 ? <EmptyState title="No enabled connectors" /> : (
            <div className="grid gap-1 md:grid-cols-2">
              {Object.entries(byStatus).map(([s, n]) => (
                <div key={s} className="flex justify-between rounded border border-border-default px-2 py-1">
                  <span>{s}</span><span>{n}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
