import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

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
