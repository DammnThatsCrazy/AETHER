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
import { queryCache, useCapabilities, useQuery } from '@aether/ui';
import { useGraphContext } from '@aether/ui/exploration';
import type { FC, ReactNode } from 'react';

const STALE = 60_000;
const RESTATEMENT_PENDING = new Set(['accepted', 'queued', 'running', 'retrying', 'cancel_requested']);
const RESTATEMENT_FAILED = new Set(['failed', 'partially_succeeded', 'expired']);

function countStatuses(counts: Record<string, number>, statuses: Set<string>): number {
  return Object.entries(counts).reduce(
    (total, [status, count]) => total + (statuses.has(status) ? count : 0),
    0,
  );
}

interface ActivationStatusData {
  readonly tenant_id: string;
  readonly historical_data_status: string;
  readonly sdk_status: string;
  readonly resolution_counts: Record<string, number>;
  readonly conflict_counts: Record<string, number>;
  readonly projection_restatement_counts: Record<string, number>;
  readonly pending_review_counts: Record<string, number>;
  readonly runtime_flags: Record<string, boolean>;
  readonly projection_restatement_status: string;
  readonly sdk_last_seen_at: string | null;
  readonly computed_at: string;
}

async function fetchActivationStatus(tenantId: string): Promise<ActivationStatusData> {
  void tenantId; // Cache scope only; the backend derives the tenant from auth.
  const r = await api.identity.activationStatus();
  return r as ActivationStatusData;
}

function statusBadge(status: string): string {
  switch (status) {
    case 'available':
    case 'connected':
    case 'active':
    case 'ready':
    case 'completed':
      return 'inline-flex items-center gap-1.5 rounded-full bg-surface-success/20 px-2.5 py-1 text-xs font-medium text-theme-success';
    case 'empty':
    case 'not_connected':
    case 'not_ready':
    case 'disabled':
    case 'idle':
      return 'inline-flex items-center gap-1.5 rounded-full bg-surface-warning/20 px-2.5 py-1 text-xs font-medium text-theme-warning';
    case 'queued':
    case 'running':
    case 'partial':
    case 'in_progress':
      return 'inline-flex items-center gap-1.5 rounded-full bg-theme-warning/20 px-2.5 py-1 text-xs font-medium text-theme-warning';
    case 'failed':
    case 'stale':
    case 'blocked':
    case 'needs_attention':
      return 'inline-flex items-center gap-1.5 rounded-full bg-theme-danger/20 px-2.5 py-1 text-xs font-medium text-theme-danger';
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
  const { isAuthenticated } = useAuth();
  const graphContext = useGraphContext();
  const tenantId = graphContext.scope.tenant_id;
  const { capabilities } = useCapabilities();
  const enabled = capabilities?.feature_flags.tenant_identity_activation_dashboard_enabled === true;

  const { data, isLoading, error, refetch } = useQuery<ActivationStatusData>({
    key: `activation-status:${tenantId}`,
    fetcher: () => fetchActivationStatus(tenantId),
    enabled: enabled && isAuthenticated && !!tenantId,
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
                    ? `Latest authenticated SDK heartbeat: ${data.sdk_last_seen_at ?? 'time unavailable'}.`
                    : data.sdk_status === 'stale'
                      ? `The last SDK heartbeat was ${data.sdk_last_seen_at ?? 'recorded earlier'}; no heartbeat arrived in the last 24 hours.`
                      : data.sdk_status === 'unknown'
                        ? 'An SDK heartbeat exists, but its timestamp could not be validated.'
                        : 'No durable SDK heartbeat has been received yet — check SDK initialization and consent setup.'}
                </p>
              </div>

              <div className="rounded border border-surface-border bg-surface-surface p-4">
                <div className="text-text-secondary text-xs">Projection Restatement</div>
                <div className="mt-2">
                  <StatusPill
                    label={data.projection_restatement_status}
                    status={data.projection_restatement_status}
                  />
                </div>
                <p className="mt-1 text-text-secondary text-xs">
                  {data.projection_restatement_status === 'active'
                    ? 'Restatement processing is enabled and no failing jobs are reported.'
                    : data.projection_restatement_status === 'in_progress'
                      ? 'Projection restatement jobs are queued or running.'
                      : data.projection_restatement_status === 'needs_attention'
                        ? 'One or more projection restatement jobs need attention.'
                        : data.projection_restatement_status === 'disabled'
                          ? 'Projection restatement is disabled by the current runtime flags.'
                          : data.projection_restatement_status === 'completed'
                            ? 'Projection restatement jobs have completed; no work is currently pending.'
                            : 'No projection restatement jobs are currently reported.'}
                </p>
              </div>

              <div className="rounded border border-surface-border bg-surface-surface p-4">
                <div className="text-text-secondary text-xs">Computed At</div>
                <div className="mt-2 text-text-primary text-sm font-mono text-xs break-all">
                  {new Date(data.computed_at).toLocaleString()}
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
                <div className="rounded bg-surface-elevated p-3 text-center">
                  <div className="text-text-primary text-2xl font-semibold">{data.pending_review_counts.open ?? 0}</div>
                  <div className="text-text-secondary text-xs">Open Identity Reviews</div>
                </div>
                <div className="rounded bg-surface-elevated p-3 text-center">
                  <div className="text-text-primary text-2xl font-semibold">{countStatuses(data.projection_restatement_counts, RESTATEMENT_FAILED)}</div>
                  <div className="text-text-secondary text-xs">Failed Restatements</div>
                </div>
                <div className="rounded bg-surface-elevated p-3 text-center">
                  <div className="text-text-primary text-2xl font-semibold">{countStatuses(data.projection_restatement_counts, RESTATEMENT_PENDING)}</div>
                  <div className="text-text-secondary text-xs">Pending Restatements</div>
                </div>
              </div>
            </div>

            <section className="mb-6 rounded border border-surface-border bg-surface-surface p-4">
              <h2 className="mb-3 text-text-primary text-sm font-semibold">Runtime Controls</h2>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {Object.entries(data.runtime_flags).map(([name, enabledFlag]) => (
                  <div key={name} className="flex items-center justify-between rounded bg-surface-elevated px-3 py-2">
                    <span className="text-text-secondary text-xs">{name.replace(/_/g, ' ')}</span>
                    <StatusPill label={enabledFlag ? 'enabled' : 'disabled'} status={enabledFlag ? 'ready' : 'disabled'} />
                  </div>
                ))}
                {Object.keys(data.runtime_flags).length === 0 && (
                  <p className="text-text-secondary text-xs">Runtime flag state is unavailable.</p>
                )}
              </div>
            </section>

            {/* Action hint */}
            <div className="rounded border border-surface-border bg-surface-surface p-4">
              <h2 className="mb-3 text-text-primary text-sm font-semibold">Next Steps</h2>
              <ul className="list-disc space-y-1 text-text-secondary text-sm">
                <li>If historical data is empty, check connector imports and SDK instrumentation.</li>
                <li>If SDK status is not_connected, verify SDK initialization and event delivery.</li>
                <li>Review open conflicts in the Identity Review Queue to resolve identity stitching issues.</li>
                <li>Use the restatement status and job counts above to see whether projection work is enabled, queued, running, or failing.</li>
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
