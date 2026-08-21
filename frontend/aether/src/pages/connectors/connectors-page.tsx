import { useEffect, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, CapabilityStateBadge, EmptyState, LoadingState, ProviderMark, formatDateTime, resolveCapabilityState, useTimeContext, type CapabilityState } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { ConnectorConfigModal } from './connector-config-modal';

type AnyRecord = Record<string, any>;

// Honest capability-state for a connector row. Availability gates win first, then
// the raw sync_status maps onto the canonical CapabilityState matrix. Nothing that
// is not actually live may read green.
function connectorCapabilityState(c: AnyRecord): CapabilityState {
  if (!c.enabled) return 'disabled';
  if (!c.secret_configured) return 'not_configured';
  switch (String(c.sync_status)) {
    case 'healthy': return 'partner_live';
    case 'syncing': return 'connection_testing';
    case 'degraded': return 'degraded';
    case 'failed': return 'error';
    case 'error': return 'error';
    case 'rate_limited': return 'stale';
    case 'permission_missing': return 'credential_required';
    case 'revoked': return 'credential_invalid';
    case 'credentials_invalid': return 'credential_invalid';
    case 'credentials_missing': return 'not_configured';
    case 'never_synced': return 'credential_waiting';
    default: return resolveCapabilityState(String(c.sync_status)) ?? 'unavailable';
  }
}

function healthLabel(c: AnyRecord): string {
  if (!c.enabled) return 'Disabled';
  if (!c.secret_configured) return 'Credentials Missing';
  const s = String(c.sync_status ?? 'never_synced');
  const labels: Record<string, string> = {
    healthy: 'Connected', syncing: 'Syncing', degraded: 'Degraded', failed: 'Failed',
    never_synced: 'Unconfigured', error: 'Error', rate_limited: 'Rate Limited',
    permission_missing: 'Permission Missing', revoked: 'Revoked',
    credentials_invalid: 'Credentials Invalid',
  };
  return labels[s] ?? s;
}

export function ConnectorsPage() {
  const [items, setItems] = useState<AnyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [configuring, setConfiguring] = useState<AnyRecord | null>(null);
  const timeCtx = useTimeContext();

  function load() {
    setLoading(true);
    api.connectors.list()
      .then((d) => setItems((((d as AnyRecord).items) ?? []) as AnyRecord[]))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  if (loading) return <main className="p-6"><LoadingState lines={6} /></main>;
  if (error) return <main className="p-6"><EmptyState title="Unable to load connectors" description={error} /></main>;

  const byCategory = items.reduce<Record<string, AnyRecord[]>>((acc, c) => {
    (acc[c.category] ??= []).push(c);
    return acc;
  }, {});

  return (
    <>
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
                    <div className="flex min-w-0 items-center gap-2">
                      <ProviderMark provider={String(c.connector_type)} decorative size={20} />
                      <div className="min-w-0">
                        <div className="text-sm font-medium">{c.label} {c.premium ? <Badge variant="warning">premium</Badge> : null}</div>
                        <div className="text-xs text-text-muted truncate">{c.description}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 ml-2 shrink-0">
                      <div className="text-right">
                        <CapabilityStateBadge
                          state={connectorCapabilityState(c)}
                          label={healthLabel(c)}
                          reason={c.last_error_message ?? undefined}
                        />
                        {c.last_sync_at && (
                          <div className="text-xs text-text-muted mt-0.5">
                            {formatDateTime(c.last_sync_at as string, timeCtx)}
                          </div>
                        )}
                        {c.last_error_message && c.sync_status === 'error' && (
                          <div className="text-xs text-danger mt-0.5 max-w-[200px] truncate" title={String(c.last_error_message)}>
                            {String(c.last_error_message)}
                          </div>
                        )}
                      </div>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => setConfiguring(c)}
                      >
                        Configure
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </main>

      {configuring && (
        <ConnectorConfigModal
          connector={configuring as any}
          onClose={() => setConfiguring(null)}
          onSaved={() => { setConfiguring(null); load(); }}
        />
      )}
    </>
  );
}
