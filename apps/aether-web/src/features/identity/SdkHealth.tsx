/**
 * SDK Health — PR 8, blueprint §12.5.
 *
 * Surface showing SDK identity health per platform: active sessions, identify
 * event rates, anonymous-to-known binding status, and late-binding parity.
 */

import { RequireAuth } from '@aether-app/features/auth';
import { useAuth } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';
import { queryCache, useQuery } from '@aether/ui';
import type { FC, ReactNode } from 'react';

const STALE = 30_000;

interface SdkPlatformHealth {
  readonly platform: string;
  readonly active_sessions: number;
  readonly identify_events_rate: number;
  readonly anonymous_to_known_bindings: number;
  readonly late_binding_parity: string;
  readonly last_heartbeat_at: string | null;
  readonly status: string;
}

interface SdkHealthData {
  readonly tenant_id: string;
  readonly overall_status: string;
  readonly platforms: SdkPlatformHealth[];
  readonly computed_at: string;
}

async function fetchSdkHealth(tenantId: string): Promise<SdkHealthData> {
  const r = await api.identity.sdkHealth(tenantId);
  return r as SdkHealthData;
}

function statusBadge(status: string): string {
  switch (status) {
    case 'healthy':
      return 'inline-flex items-center gap-1 rounded-full bg-surface-success/20 px-2 py-0.5 text-xs font-medium text-theme-success';
    case 'degraded':
      return 'inline-flex items-center gap-1 rounded-full bg-theme-warning/20 px-2 py-0.5 text-xs font-medium text-theme-warning';
    case 'unhealthy':
      return 'inline-flex items-center gap-1 rounded-full bg-theme-danger/20 px-2 py-0.5 text-xs font-medium text-theme-danger';
    default:
      return 'inline-flex items-center gap-1 rounded-full bg-surface-elevated px-2 py-0.5 text-xs text-text-secondary';
  }
}

export const SdkHealth: FC<{ readonly className?: string; readonly children?: ReactNode }> = ({
  className = '',
  children,
}) => {
  const { user } = useAuth();
  const tenantId = user?.id ?? '';

  const { data, isLoading, error, refetch } = useQuery<SdkHealthData>({
    key: `sdk-health:${tenantId}`,
    fetcher: () => fetchSdkHealth(tenantId),
    enabled: !!tenantId,
    staleTime: STALE,
  });

  return (
    <RequireAuth>
      <div className={`flex flex-col bg-surface-base ${className}`}>
        <header className="flex h-14 items-center border-b border-surface-border bg-surface-surface px-4">
          <div className="flex items-center gap-2">
            <span className="text-text-primary text-sm font-medium">SDK Health</span>
            <span className="text-text-secondary text-xs">/ Identity Ingestion</span>
          </div>
        </header>

        <main className="flex-1 px-6 py-6">
          <div className="mx-auto max-w-5xl">
            {isLoading ? (
              <div className="flex h-48 items-center justify-center text-text-secondary text-sm">
                Loading SDK health...
              </div>
            ) : error || !data ? (
              <div className="flex h-48 flex-col items-center justify-center rounded border border-surface-border bg-surface-surface p-6 text-text-secondary text-sm">
                Unable to load SDK health.
                <button
                  className="mt-2 rounded bg-surface-accent px-3 py-1 text-xs text-text-on-accent"
                  onClick={() => { queryCache.invalidatePrefix('sdk-health'); refetch(); }}
                >
                  Retry
                </button>
              </div>
            ) : (
              <>
                <div className="mb-6 flex items-center justify-between">
                  <div>
                    <h1 className="text-text-primary text-xl font-semibold">SDK Health</h1>
                    <p className="text-text-secondary text-sm">Tenant {data.tenant_id}</p>
                  </div>
                  <span className={statusBadge(data.overall_status)}>
                    {data.overall_status}
                  </span>
                </div>

                <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded border border-surface-border bg-surface-surface p-4">
                    <div className="text-text-primary text-2xl font-semibold">
                      {data.platforms.length}
                    </div>
                    <div className="text-text-secondary text-xs">Platforms reporting</div>
                  </div>
                  <div className="rounded border border-surface-border bg-surface-surface p-4">
                    <div className="text-text-primary text-2xl font-semibold">
                      {data.platforms.reduce((s, p) => s + p.active_sessions, 0)}
                    </div>
                    <div className="text-text-secondary text-xs">Active sessions</div>
                  </div>
                  <div className="rounded border border-surface-border bg-surface-surface p-4">
                    <div className="text-text-primary text-2xl font-semibold">
                      {data.platforms.reduce((s, p) => s + p.anonymous_to_known_bindings, 0)}
                    </div>
                    <div className="text-text-secondary text-xs">Anon→Known bindings</div>
                  </div>
                  <div className="rounded border border-surface-border bg-surface-surface p-4">
                    <div className="text-text-primary text-2xl font-semibold">
                      {data.computed_at}
                    </div>
                    <div className="text-text-secondary text-xs">Computed at</div>
                  </div>
                </div>

                <div className="space-y-3">
                  {data.platforms.map((platform) => (
                    <div
                      key={platform.platform}
                      className="flex flex-col gap-2 rounded border border-surface-border bg-surface-surface p-4"
                    >
                      <div className="flex items-center justify-between gap-4">
                        <div className="flex items-center gap-2">
                          <span className="text-text-primary text-sm font-medium capitalize">
                            {platform.platform}
                          </span>
                          <span className={statusBadge(platform.status)}>{platform.status}</span>
                        </div>
                        <span className="text-xs text-text-muted">
                          Last heartbeat: {platform.last_heartbeat_at ?? 'never'}
                        </span>
                      </div>
                      <div className="grid grid-cols-3 gap-3 text-xs">
                        <div className="rounded bg-surface-elevated p-3 text-center">
                          <div className="text-text-primary text-lg font-semibold">
                            {platform.active_sessions}
                          </div>
                          <div className="text-text-secondary">Active sessions</div>
                        </div>
                        <div className="rounded bg-surface-elevated p-3 text-center">
                          <div className="text-text-primary text-lg font-semibold">
                            {platform.identify_events_rate.toFixed(1)}/
                          </div>
                          <div className="text-text-secondary">Identify events/s</div>
                        </div>
                        <div className="rounded bg-surface-elevated p-3 text-center">
                          <div className="text-text-primary text-lg font-semibold">
                            {platform.anonymous_to_known_bindings}
                          </div>
                          <div className="text-text-secondary">Anon→Known</div>
                        </div>
                      </div>
                      <div className="text-xs text-text-secondary">
                        Late-binding parity:{' '}
                        <span className={platform.late_binding_parity === 'parity'
                          ? 'text-theme-success'
                          : platform.late_binding_parity === 'partial'
                          ? 'text-theme-warning'
                          : 'text-theme-danger'}>
                          {platform.late_binding_parity}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-6 rounded border border-surface-border bg-surface-surface p-4">
                  <h2 className="text-text-primary text-sm font-medium mb-2">Guidance</h2>
                  <ul className="list-disc space-y-1 text-text-secondary text-sm">
                    <li>Healthy SDK health means all platforms are sending identity events and bindings.</li>
                    <li>Monitor anonymous-to-known bindings to track import-first SDK-later scenarios.</li>
                    <li>Low identify event rates may indicate SDK integration issues.</li>
                    <li>Late-binding parity should reach "parity" once all SDKs emit sufficient identity evidence.</li>
                  </ul>
                </div>
              </>
            )}
          </div>
          {children}
        </main>
      </div>
    </RequireAuth>
  );
};

export default SdkHealth;
