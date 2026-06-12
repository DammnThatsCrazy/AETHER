import { Badge, LoadingState, useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

interface FeederHealth {
  readonly status: 'ok' | 'degraded';
  readonly total_bronze_records: number;
  readonly total_silver_records: number;
  readonly total_gold_records: number;
  readonly unique_source_tags: number;
  readonly rejection_rate: number;
  readonly last_ingest_at: string | null;
  readonly last_ingest_source_tag: string | null;
  readonly graph_isolation_enforced: boolean;
}

interface GoldRecord {
  readonly gold_id: string;
  readonly source_tag: string;
  readonly domain: string;
  readonly query_id: string;
  readonly query_name: string | null;
  readonly tenant_scope: string | null;
  readonly materialized_at: string;
  readonly row_count: number;
  readonly avg_quality_score: number;
}

function healthVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'ok') return 'success';
  if (status === 'degraded') return 'warning';
  return 'danger';
}

function formatTs(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export function DuneFeederPage() {
  const health = useQuery({
    key: 'dune-feeder-health',
    fetcher: () => api.kyber.duneFeederHealth() as Promise<{ data: FeederHealth }>,
    staleTime: 30_000,
  });

  const gold = useQuery({
    key: 'dune-feeder-gold',
    fetcher: () => api.kyber.duneFeederGold() as Promise<{ data: { records: GoldRecord[]; record_count: number } }>,
    staleTime: 30_000,
  });

  const h = (health.data as any)?.data as FeederHealth | undefined;
  const goldRecords = ((gold.data as any)?.data?.records ?? []) as GoldRecord[];

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Dune Analytics Feeder</h1>
          <p className="text-sm text-text-muted mt-1">
            Governed Bronze → Silver → Gold pipeline. Dune data is strictly read-only and never mutates the canonical graph.
          </p>
        </div>
        {h && (
          <Badge variant={healthVariant(h.status)}>
            {h.status === 'ok' ? 'healthy' : h.status}
          </Badge>
        )}
      </div>

      {health.loading && <LoadingState lines={4} />}

      {h && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Bronze records', value: h.total_bronze_records },
            { label: 'Silver records', value: h.total_silver_records },
            { label: 'Gold records', value: h.total_gold_records },
            { label: 'Source tags', value: h.unique_source_tags },
          ].map(({ label, value }) => (
            <div key={label} className="rounded border border-border-subtle p-4 bg-surface-raised">
              <p className="text-xs text-text-muted">{label}</p>
              <p className="text-2xl font-semibold text-text-primary mt-1">{value}</p>
            </div>
          ))}
        </div>
      )}

      {h && (
        <div className="rounded border border-border-subtle p-4 bg-surface-raised space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-text-muted">Last ingest</span>
            <span className="text-text-primary">{formatTs(h.last_ingest_at)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-muted">Last source tag</span>
            <span className="font-mono text-text-primary">{h.last_ingest_source_tag ?? '—'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-muted">Rejection rate</span>
            <span className={h.rejection_rate > 0.5 ? 'text-status-danger' : 'text-text-primary'}>
              {(h.rejection_rate * 100).toFixed(1)}%
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-muted">Graph isolation enforced</span>
            <Badge variant={h.graph_isolation_enforced ? 'success' : 'danger'}>
              {h.graph_isolation_enforced ? 'yes' : 'no'}
            </Badge>
          </div>
        </div>
      )}

      <div>
        <h2 className="text-lg font-semibold text-text-primary mb-3">Gold records</h2>
        {gold.loading && <LoadingState lines={3} />}
        {!gold.loading && goldRecords.length === 0 && (
          <p className="text-sm text-text-muted">No Gold records yet. Ingest Bronze rows, promote to Silver, then materialize Gold via the admin API.</p>
        )}
        {goldRecords.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border border-border-subtle rounded">
              <thead className="bg-surface-raised text-text-muted text-left">
                <tr>
                  <th className="py-2 px-3">Source tag</th>
                  <th className="py-2 px-3">Domain</th>
                  <th className="py-2 px-3">Query</th>
                  <th className="py-2 px-3 text-right">Rows</th>
                  <th className="py-2 px-3 text-right">Avg quality</th>
                  <th className="py-2 px-3">Tenant scope</th>
                  <th className="py-2 px-3">Materialized at</th>
                </tr>
              </thead>
              <tbody>
                {goldRecords.map((r) => (
                  <tr key={r.gold_id} className="border-t border-border-subtle hover:bg-surface-hover">
                    <td className="py-2 px-3 font-mono text-xs">{r.source_tag}</td>
                    <td className="py-2 px-3">{r.domain}</td>
                    <td className="py-2 px-3 text-text-muted">{r.query_name ?? r.query_id}</td>
                    <td className="py-2 px-3 text-right">{r.row_count}</td>
                    <td className="py-2 px-3 text-right">
                      <span className={r.avg_quality_score >= 0.9 ? 'text-status-success' : r.avg_quality_score >= 0.8 ? 'text-status-warning' : 'text-status-danger'}>
                        {(r.avg_quality_score * 100).toFixed(1)}%
                      </span>
                    </td>
                    <td className="py-2 px-3 text-text-muted">{r.tenant_scope ?? 'global'}</td>
                    <td className="py-2 px-3 text-text-muted">{formatTs(r.materialized_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
