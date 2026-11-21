/**
 * System Sources: every data source by who owns it.
 *
 * Olympus sources (the reserved `olympus` scope) are shown in full: each
 * connection's state, whether a credential is stored (never the credential),
 * and each grant's permitted uses. Tenant sources are aggregated per provider
 * (connections by state, grants by relationship), never by tenant. The
 * provider catalog shows which ownership modes each provider supports.
 */
import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState, formatInstant, useTimeContext } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api, type SystemSourcesView } from '@kyber/lib/api';

const RELATIONSHIP_LABEL: Record<string, string> = {
  organization_system: 'Organization system',
  personal_account: 'Personal account',
  first_party_application: 'First-party app',
  partner_feed: 'Partner feed',
  public_reference: 'Public reference',
  olympus_source: 'Olympus source',
  internal_system: 'Internal',
  unclassified: 'Unclassified',
};

function Metric({ label, value }: { readonly label: string; readonly value: number }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{value}</div>
      </CardContent>
    </Card>
  );
}

function Uses({ grant }: { readonly grant: SystemSourcesView['olympus']['grants'][number] }) {
  return (
    <span className="flex flex-wrap gap-1">
      <Badge variant={grant.olympus_baseline_allowed ? 'success' : 'default'}>baseline {grant.olympus_baseline_allowed ? 'yes' : 'no'}</Badge>
      <Badge variant={grant.model_training_allowed ? 'warning' : 'default'}>training {grant.model_training_allowed ? 'yes' : 'no'}</Badge>
      <Badge variant={grant.commercial_reuse_allowed ? 'warning' : 'default'}>commercial reuse {grant.commercial_reuse_allowed ? 'yes' : 'no'}</Badge>
    </span>
  );
}

export function SystemSourcesPage() {
  const timeCtx = useTimeContext();
  const [data, setData] = useState<SystemSourcesView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.admin.kyber.providerConnections.systemSources()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const title = 'System Sources';
  const subtitle = 'Every data source by owner. Olympus sources in full; tenant sources aggregated by provider, never by tenant. No credentials or tenant configuration are shown.';
  if (error) return <PageWrapper title={title} subtitle={subtitle}><EmptyState title="Unable to load sources" description={error} /></PageWrapper>;
  if (!data) return <PageWrapper title={title} subtitle={subtitle}><LoadingState lines={6} /></PageWrapper>;

  const tenantProviders = Object.entries(data.tenants.providers).sort(([a], [b]) => a.localeCompare(b));
  const when = (ts?: string | null) => (ts ? formatInstant(ts, timeCtx) : '—');

  return (
    <PageWrapper title={title} subtitle={subtitle}>
      <div className="grid gap-3 md:grid-cols-4" data-testid="system-sources-metrics">
        <Metric label="Olympus connections" value={data.olympus.connections.length} />
        <Metric label="Olympus grants" value={data.olympus.grants.length} />
        <Metric label="Tenants with sources" value={data.tenants.tenant_count} />
        <Metric label="Tenant connections" value={data.tenants.connection_count} />
      </div>
      {data.truncated && <p className="mt-2 text-xs text-warning">Showing the first 5,000 connections.</p>}

      <Card className="mt-4" data-testid="system-sources-olympus">
        <CardHeader><CardTitle>Olympus sources</CardTitle></CardHeader>
        <CardContent>
          {data.olympus.connections.length === 0 ? (
            <EmptyState title="No Olympus sources yet" description="Add one from Provider Runtime under the olympus scope." />
          ) : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-text-muted"><th>Source</th><th>State</th><th>Credential</th><th>Accounts</th><th>Updated</th></tr></thead>
              <tbody>
                {data.olympus.connections.map(c => (
                  <tr key={c.connection_id} className="border-t border-border-subtle">
                    <td className="py-1.5"><div>{c.display_name}</div><div className="font-mono text-xs text-text-faint">{c.provider_identity}</div></td>
                    <td><Badge>{c.state}</Badge></td>
                    <td>{c.credential_stored ? <Badge variant="success">stored</Badge> : <Badge variant="warning">missing</Badge>}</td>
                    <td>{c.account_count}</td>
                    <td className="text-xs">{when(c.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data.olympus.grants.length > 0 && (
            <div className="mt-4 space-y-2">
              <div className="text-xs font-mono text-text-muted">Grants</div>
              {data.olympus.grants.map(g => (
                <div key={g.grant_id} className="flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle pt-2 text-sm">
                  <span><span className="font-mono text-xs">{g.source_id}</span> <span className="text-text-faint">· {g.connector_class}</span></span>
                  <Uses grant={g} />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="mt-4" data-testid="system-sources-tenants">
        <CardHeader><CardTitle>Tenant sources (aggregate)</CardTitle></CardHeader>
        <CardContent>
          {tenantProviders.length === 0 ? (
            <EmptyState title="No tenant sources yet" />
          ) : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-text-muted"><th>Provider</th><th>Connections by state</th><th>Active grants by relationship</th></tr></thead>
              <tbody>
                {tenantProviders.map(([provider, view]) => (
                  <tr key={provider} className="border-t border-border-subtle align-top">
                    <td className="py-1.5 font-mono text-xs">{provider}</td>
                    <td><span className="flex flex-wrap gap-1">{Object.entries(view.connections).map(([state, n]) => <Badge key={state}>{state} {n}</Badge>)}</span></td>
                    <td><span className="flex flex-wrap gap-1">{Object.entries(view.grants).map(([rel, n]) => <Badge key={rel}>{RELATIONSHIP_LABEL[rel] ?? rel} {n}</Badge>)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
