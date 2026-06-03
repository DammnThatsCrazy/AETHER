import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

type AnyRecord = Record<string, any>;

const STATUS_VARIANT: Record<string, 'success' | 'warning' | 'danger' | 'default'> = {
  healthy: 'success', syncing: 'warning', degraded: 'warning', failed: 'danger',
  disabled: 'default', never_synced: 'default',
};

export function ConnectorsPage() {
  const [items, setItems] = useState<AnyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.connectors.list()
      .then((d) => setItems((((d as AnyRecord).items) ?? []) as AnyRecord[]))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <main className="p-6"><LoadingState lines={6} /></main>;
  if (error) return <main className="p-6"><EmptyState title="Unable to load connectors" description={error} /></main>;

  const byCategory = items.reduce<Record<string, AnyRecord[]>>((acc, c) => {
    (acc[c.category] ??= []).push(c);
    return acc;
  }, {});

  return (
    <main className="p-6 space-y-4">
      <div>
        <h1 className="text-xl font-mono font-bold">Integrations &amp; Connectors</h1>
        <p className="text-sm text-text-secondary">
          Enrich your intelligence graph without the SDK. Connect platforms via
          signed webhooks or provider sync. SDK ingestion remains available and is
          not required. Connectors are disabled by default; enabling one configures
          credentials securely (secrets are never shown here).
        </p>
      </div>

      {items.length === 0 ? <EmptyState title="No connectors available" /> : Object.entries(byCategory).map(([category, conns]) => (
        <Card key={category}>
          <CardHeader><CardTitle className="capitalize">{category.replace(/_/g, ' ')}</CardTitle></CardHeader>
          <CardContent>
            <div className="grid gap-2 md:grid-cols-2">
              {conns.map((c) => (
                <div key={c.connector_type} className="flex items-center justify-between rounded border border-border-default px-3 py-2">
                  <div>
                    <div className="text-sm font-medium">{c.label} {c.premium ? <Badge variant="warning">premium</Badge> : null}</div>
                    <div className="text-xs text-text-muted">{c.description}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    {c.enabled ? <Badge variant={STATUS_VARIANT[c.sync_status] ?? 'default'}>{c.sync_status}</Badge> : <Badge variant="default">disabled</Badge>}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ))}
    </main>
  );
}
