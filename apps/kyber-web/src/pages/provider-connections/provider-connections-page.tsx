/**
 * KYBER — Provider Connections (operator read/monitor + certify).
 *
 * The manifest-driven surface over the Universal Provider Runtime. Renders ONLY
 * from manifest data — zero connector-specific code. Honest scope: connection
 * create / test / sync stay tenant-scoped API calls and are NOT claimed here;
 * this surface is aggregate read/monitor plus the operator-certify action.
 *
 * The page is gated by the ``enableProviderRuntime`` frontend flag (mirrors the
 * backend ``KYBER_PROVIDER_RUNTIME_UI_ENABLED``). The backend mounts the admin
 * provider-connections routes (providers/certify/tenants — this surface's data)
 * when EITHER ``KYBER_PROVIDER_RUNTIME_UI_ENABLED`` OR
 * ``KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED`` is set. A direct URL hit while the
 * frontend flag is off renders an honest disabled state rather than mounting a
 * dead surface.
 */
import { Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';
import { PageWrapper } from '@kyber/components/layout';
import {
  ProviderCatalogTable,
  ProviderOverviewCards,
  ProviderRuntimeHealthCard,
} from '@kyber/components/provider-connections';
import {
  useProviderCatalog,
  useProviderOverview,
  useProviderRuntimeHealth,
} from '@kyber/features/provider-connections';

function DisabledState() {
  return (
    <PageWrapper title="Provider Connections">
      <EmptyState
        title="Provider Runtime UI is disabled"
        description="Enable the enableProviderRuntime feature flag and set KYBER_PROVIDER_RUNTIME_UI_ENABLED (or the backend health flag KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED — either one mounts the admin provider-connections routes this surface reads) to operate this aggregate read/monitor surface."
      />
    </PageWrapper>
  );
}

export function ProviderConnectionsPage() {
  if (!isFeatureEnabled('enableProviderRuntime')) {
    return <DisabledState />;
  }

  const catalog = useProviderCatalog();
  const overview = useProviderOverview();
  const health = useProviderRuntimeHealth();

  if (catalog.loading) {
    return (
      <PageWrapper title="Provider Connections">
        <LoadingState lines={6} />
      </PageWrapper>
    );
  }
  if (catalog.error !== null) {
    return (
      <PageWrapper title="Provider Connections">
        <ErrorState title="Unable to load the provider catalog" message={catalog.error} />
      </PageWrapper>
    );
  }

  return (
    <PageWrapper
      title="Provider Connections"
      subtitle="Aggregate, tenant-anonymous view of the Universal Provider Runtime manifest. No raw tenant configs or secrets are shown; create/test/sync stay tenant-scoped."
    >
      {overview.data !== null ? <ProviderOverviewCards data={overview.data} /> : null}
      {health.data !== null ? <ProviderRuntimeHealthCard data={health.data} /> : null}

      {catalog.data !== null && catalog.data.issues.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Catalog entries skipped</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-2 text-xs text-text-muted">
              The backend shipped the following provider entries that failed the manifest
              contract. They are surfaced here — not dropped silently — and are excluded
              from the catalog table below.
            </p>
            <ul className="list-disc pl-4 text-xs font-mono text-text-muted">
              {catalog.data.issues.map(issue => (
                <li key={issue.identity}>
                  {issue.identity} — {issue.status} ({issue.reason})
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Provider catalog</CardTitle>
        </CardHeader>
        <CardContent>
          <ProviderCatalogTable entries={catalog.data?.providers ?? []} />
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
