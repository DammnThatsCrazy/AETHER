import { Link } from 'react-router-dom';
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  ProviderMark,
  StatusIndicator,
  formatDateTime,
  useTimeContext,
} from '@aether/ui';
import { useTenantIntegrations } from '@aether-app/features/integrations';
import type { TenantIntegrationItem } from '@aether-app/features/integrations';
import {
  catalogBaselineCaption,
  groupByExperienceCategory,
  tenantConnectionStatus,
} from '@aether-app/features/settings';

/** Route target for the reused connector manager (the Connect/Manage surface). */
const CONNECT_MANAGER_ROUTE = '/settings/integrations/connectors';

function IntegrationRow({ item }: { readonly item: TenantIntegrationItem }) {
  const timeCtx = useTimeContext();
  const status = tenantConnectionStatus(item);
  const baseline = catalogBaselineCaption(item.readiness?.state);

  return (
    <div className="flex items-center justify-between rounded border border-border-default px-3 py-2 gap-2">
      <div className="flex min-w-0 items-center gap-2.5">
        <ProviderMark provider={item.family} decorative size={20} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-text-primary truncate">{item.display_name}</span>
            {!item.enabled && item.connected === false && (
              <Badge variant="default" size="sm">available</Badge>
            )}
          </div>
          <div className="text-xs text-text-muted truncate">
            {item.last_synced_at
              ? `Last synced ${formatDateTime(item.last_synced_at, timeCtx)}`
              : 'Never synced'}
            {baseline ? <span className="text-text-muted/70"> · {baseline}</span> : null}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2 ml-2 shrink-0">
        <div className="text-right">
          <div className="flex items-center justify-end gap-1.5">
            <StatusIndicator status={status.indicator} />
            <span className="text-xs font-mono text-text-secondary">{status.label}</span>
          </div>
          {status.detail && (
            <div className="text-[10px] text-text-muted">{status.detail}</div>
          )}
        </div>
        <Button
          asChild
          size="sm"
          variant="secondary"
        >
          <Link to={CONNECT_MANAGER_ROUTE}>Manage</Link>
        </Button>
      </div>
    </div>
  );
}

/**
 * Settings → Integrations (WS-1). Lists the tenant's configured integrations
 * from the R1 read model (/v1/tenant-integrations), grouped by experience
 * category. Statuses are connection-record facts only — "Ready" is never
 * inferred and catalog readiness is surfaced as a muted baseline caption, never
 * as the tenant's state. Renders honest loading / unavailable / empty states
 * when the catalog is empty or unreachable (connectors are flag-gated OFF by
 * default).
 */
export function IntegrationsSection() {
  const tenant = useTenantIntegrations();
  const items = tenant.data?.items ?? null;

  if (tenant.isLoading && !items) {
    return (
      <div className="space-y-3">
        <span className="text-sm font-mono text-text-muted">Integrations</span>
        <LoadingState lines={5} />
      </div>
    );
  }

  if (tenant.error && !items) {
    return (
      <>
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm font-mono text-text-muted">Integrations</span>
        </div>
        <ErrorState
          title="Integrations unavailable"
          message="We couldn't load this workspace's integrations. The integrations service may not be enabled here — SDK ingestion is always available. Try again in a moment."
          onRetry={tenant.refetch}
        />
      </>
    );
  }

  if (!items || items.length === 0) {
    return (
      <div className="space-y-4">
        <span className="text-sm font-mono text-text-muted">Integrations</span>
        <EmptyState
          title="No integrations connected"
          description="Connect a platform to bring data into Aether without the SDK. SDK ingestion remains available and is not required."
          action={
            <Button asChild variant="primary" size="sm">
              <Link to={CONNECT_MANAGER_ROUTE}>Connect an integration</Link>
            </Button>
          }
        />
      </div>
    );
  }

  const groups = groupByExperienceCategory(items);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm font-mono text-text-muted">Integrations</span>
          <p className="text-xs text-text-secondary mt-0.5">
            Connection status reflects this workspace&apos;s records. Live data
            readiness is never inferred — a connected integration is not assumed
            to be flowing data until a sync completes.
          </p>
        </div>
        <Button asChild variant="primary" size="sm">
          <Link to={CONNECT_MANAGER_ROUTE}>Connect</Link>
        </Button>
      </div>

      {groups.map(group => (
        <section key={group.key || '__other__'} aria-label={group.label}>
          <h2 className="text-xs font-mono uppercase tracking-wide text-text-muted mb-2">
            {group.label}
          </h2>
          <div className="grid gap-2 md:grid-cols-2">
            {group.items.map(item => (
              <IntegrationRow key={item.id} item={item} />
            ))}
          </div>
        </section>
      ))}

      <p className="text-[10px] text-text-muted font-mono pt-1">
        {items.length} configured integration{items.length === 1 ? '' : 's'} ·{' '}
        <Link to={CONNECT_MANAGER_ROUTE} className="text-accent hover:text-accent-hover">
          Manage connectors
        </Link>
      </p>
    </div>
  );
}
