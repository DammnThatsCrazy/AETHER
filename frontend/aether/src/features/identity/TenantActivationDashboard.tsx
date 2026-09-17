/**
 * Tenant Activation Dashboard — PR 8, blueprint §12.1.
 *
 * Tenant-scoped dashboard surface showing identity activation state:
 * historical data status, SDK status, resolution counts, conflict counts,
 * projection restatement status. Gated by tenant_identity_activation_dashboard_enabled.
 */

import { RequireAuth } from '@aether-app/features/auth';
import { useAuth } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';
import { queryCache, useQuery } from '@aether/ui';
import type { FC, ReactNode } from 'react';

const STALE = 60_000;

interface ActivationStatusData {
  readonly tenant_id: string;
  readonly historical_data_status: string;
  readonly sdk_status: string;
  readonly resolution_counts: Record<string, number>;
  readonly conflict_counts: Record<string, number>;
  readonly projection_restatement_status: string;
  readonly computed_at: string;
}

async function fetchActivationStatus(tenantId: string): Promise<ActivationStatusData> {
  const r = await api.identity.activationStatus(tenantId);
  return r as ActivationStatusData;
}

function statusBadge(status: string): string {
  switch (status) {
    case 'available':
    case 'connected':
    case 'active':
    case 'ready':
      return 'inline-flex items-center gap-1.5 rounded-full bg-surface-success/20 px-2.5 py-1 text-xs font-medium text-theme-success';
    case 'empty':
    case 'not_connected':
    case 'not_ready':
      return 'inline-flex items-center gap-1.5 rounded-full bg-surface-warning/20 px-2.5 py-1 text-xs font-medium text-theme-warning';
    default:
      return 'inline-flex items-center gap-1.5 rounded-full bg-surface-elevated px-2.5 py-1 text-xs font-medium text-text-secondary';
  }
}

function StatusPill({ label, status }: { label: string; status: string }) {
  return (
    <span className={statusBadge(status)}>
      <span className="size-1.5 rounded-full bg-current opacity-60" />
      {label}
    </span>
  );
}

export const TenantActivationDashboard: FC<{ readonly children?: ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  const tenantId = user?.id ?? '';
  const enabled = isFeatureEnabled('tenant_identity_activation_dashboard_enabled');

  const { data, isLoading, error, refetch } = useQuery<ActivationStatusData>({
    key: `activation-status:${tenantId}`,
    fetcher: () => fetchActivationStatus(tenantId),
    enabled: enabled && !!tenantId,
    staleTime: STALE,
  });

  if (!enabled) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="text-center text-text-secondary text-sm">
          Tenant activation dashboard is not enabled in this environment.
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="text-center">
          <div className="text-text-secondary text-sm">Loading activation status...</div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="text-center text-text-secondary text-sm">
          Unable to load activation status. {error ? ` (${String(error)})` : ''}
          <button
            className="mt-2 rounded bg-surface-accent px-3 py-1 text-xs text-text-on-accent"
            onClick={() => { queryCache.invalidatePrefix('activation-status'); refetch(); }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const counts = data.resolution_counts;
  const conflicts = data.conflict_counts;

  return (
    <RequireAuth>
      <div className="flex min-h-screen flex-col bg-surface-base">
        <header className="flex h-14 items-center border-b border-surface-border bg-surface-surface px-4">
          <div className="flex items-center gap-2">
            <span className="text-text-primary text-sm font-medium">Tenant Activation</span>
            <span className="text-text-secondary text-xs">/ Identity Continuity</span>
          </div>
        </header>
        <main className="flex-1 px-6 py-8">
          <div className="mx-auto max-w-4xl">
            <div className="mb-6">
              <h1 className="text-text-primary text-xl font-semibold">Activation Status</h1>
              <p className="text-text-secondary text-sm">
                Identity continuity activation state for tenant <code className="rounded bg-surface-elevated px-1.5 py-0.5 text-xs">{data.tenant_id}</code>
              </p>
            </div>

            {/* Top-level status cards */}
            <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded border border-surface-border bg-surface-surface p-4">
                <div className="text-text-secondary text-xs">Historical Data</div>
                <div className="mt-2">
                  <StatusPill label={data.historical_data_status} status={data.historical_data_status} />
                </div>
                <p className="mt-1 text-text-secondary text-xs">
                  {data.historical_data_status === 'available'
                    ? 'Historical identity data is available for this tenant.'
                    : 'No historical identity data has been imported yet.'}
                </p>
              </div>

              <div className="rounded border border-surface-border bg-surface-surface p-4">
                <div className="text-text-secondary text-xs">SDK Status</div>
                <div className="mt-2">
                  <StatusPill label={data.sdk_status} status={data.sdk_status} />
                </div>
                <p className="mt-1 text-text-secondary text-xs">
                  {data.sdk_status === 'connected'
                    ? 'SDKs are actively sending identity signals.'
                    : 'No SDK signals received yet — check SDK integration.'}
                </p>
              </div>

              <div className="rounded border border-surface-border bg-surface-surface p-4">
                <div className="text-text-secondary text-xs">Projection Restatement</div>
                <div className="mt-2">
                  <StatusPill label={data.projection_restatement_status} status="active" />
                </div>
                <p className="mt-1 text-text-secondary text-xs">
                  Downstream projections are being restated after identity changes.
                </p>
              </div>

              <div className="rounded border border-surface-border bg-surface-surface p-4">
                <div className="text-text-secondary text-xs">Computed At</div>
                <div className="mt-2 text-text-primary text-sm font-mono text-xs break-all">
                  {data.computed_at}
                </div>
              </div>
            </div>

            {/* Resolution counts */}
            <div className="mb-6 rounded border border-surface-border bg-surface-surface p-4">
              <h2 className="mb-3 text-text-primary text-sm font-semibold">Resolution Counts</h2>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="rounded bg-surface-elevated p-3 text-center">
                  <div className="text-text-primary text-2xl font-semibold">{counts.total_entities ?? 0}</div>
                  <div className="text-text-secondary text-xs">Total Entities</div>
                </div>
                <div className="rounded bg-surface-elevated p-3 text-center">
                  <div className="text-text-primary text-2xl font-semibold">{counts.total_aliases ?? 0}</div>
                  <div className="text-text-secondary text-xs">Total Aliases</div>
                </div>
                <div className="rounded bg-surface-elevated p-3 text-center">
                  <div className="text-text-primary text-2xl font-semibold">{counts.total_clusters ?? 0}</div>
                  <div className="text-text-secondary text-xs">Total Clusters</div>
                </div>
                <div className="rounded bg-surface-elevated p-3 text-center">
                  <div className="text-text-primary text-2xl font-semibold">{counts.recent_merges ?? 0}</div>
                  <div className="text-text-secondary text-xs">Recent Merges</div>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
                <div className="rounded bg-surface-elevated p-3 text-center">
                  <div className="text-text-primary text-2xl font-semibold">{counts.recent_splits ?? 0}</div>
                  <div className="text-text-secondary text-xs">Recent Splits</div>
                </div>
                <div className="rounded bg-surface-elevated p-3 text-center">
                  <div className="text-text-primary text-2xl font-semibold">{conflicts.open ?? 0}</div>
                  <div className="text-text-secondary text-xs">Open Conflicts</div>
                </div>
                <div className="rounded bg-surface-elevated p-3 text-center">
                  <div className="text-text-primary text-2xl font-semibold">{conflicts.resolved ?? 0}</div>
                  <div className="text-text-secondary text-xs">Resolved</div>
                </div>
              </div>
            </div>

            {/* Action hint */}
            <div className="rounded border border-surface-border bg-surface-surface p-4">
              <h2 className="mb-3 text-text-primary text-sm font-semibold">Next Steps</h2>
              <ul className="list-disc space-y-1 text-text-secondary text-sm">
                <li>If historical data is empty, check connector imports and SDK instrumentation.</li>
                <li>If SDK status is not_connected, verify SDK initialization and event delivery.</li>
                <li>Review open conflicts in the Identity Review Queue to resolve identity stitching issues.</li>
                <li>Restatement status is active — projections update automatically after merge/split/reconcile.</li>
              </ul>
            </div>

            {children}
          </div>
        </main>
      </div>
    </RequireAuth>
  );
};

export default TenantActivationDashboard;
