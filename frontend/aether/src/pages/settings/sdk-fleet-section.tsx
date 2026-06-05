import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  DataTable,
  EmptyState,
  ErrorState,
  Skeleton,
  StatusIndicator,
  useToast,
  queryCache,
} from '@aether/ui';
import {
  useSdkFleet,
  useSilentSdks,
  useSdkManifest,
  useSdkRollout,
  useRollbackManifest,
  usePublishManifest,
} from '@aether-app/features/sdk';
import type { SilentSDK } from '@aether-app/types/sdk';

function pct(n: number): string {
  return `${Math.round(n)}%`;
}

function StatTile({ label, value, tone }: { label: string; value: string | number; tone?: 'healthy' | 'degraded' | 'danger' | 'muted' }) {
  const color =
    tone === 'healthy' ? 'text-success'
    : tone === 'degraded' ? 'text-warning'
    : tone === 'danger' ? 'text-danger'
    : 'text-text-primary';
  return (
    <div className="flex flex-col gap-0.5 px-3 py-2 bg-surface-base border border-border-default rounded">
      <span className={`text-lg font-mono ${color}`}>{value}</span>
      <span className="text-xs text-text-muted">{label}</span>
    </div>
  );
}

function FleetOverview() {
  const { data: fleet, isLoading, error, refetch } = useSdkFleet();

  if (isLoading) return <Skeleton className="h-28 w-full" />;
  if (error) return <ErrorState message="Failed to load SDK fleet" onRetry={refetch} />;
  if (!fleet || fleet.total_instances === 0) {
    return (
      <EmptyState
        title="No SDKs reporting yet"
        description="Once you install and initialize an Aether SDK with one of your API keys, each instance reports its health here automatically."
      />
    );
  }

  const platforms = Object.entries(fleet.platforms ?? {});
  const versions = Object.entries(fleet.versions ?? {});
  const avgTone = fleet.avg_health_score >= 80 ? 'healthy' : fleet.avg_health_score >= 50 ? 'degraded' : 'danger';

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <StatTile label="Total" value={fleet.total_instances} />
        <StatTile label="Healthy" value={fleet.healthy_count} tone="healthy" />
        <StatTile label="Degraded" value={fleet.degraded_count} tone="degraded" />
        <StatTile label="Unhealthy" value={fleet.unhealthy_count} tone="danger" />
        <StatTile label="Silent" value={fleet.silent_count} tone="muted" />
        <StatTile label="Avg score" value={pct(fleet.avg_health_score)} tone={avgTone} />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Card>
          <CardContent>
            <span className="text-xs font-mono text-text-muted">By platform</span>
            <div className="flex flex-wrap gap-2 mt-2">
              {platforms.length === 0 && <span className="text-xs text-text-muted">—</span>}
              {platforms.map(([p, count]) => (
                <Badge key={p} variant="default" size="sm">{p}: {count}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <span className="text-xs font-mono text-text-muted">By SDK version</span>
            <div className="flex flex-wrap gap-2 mt-2">
              {versions.length === 0 && <span className="text-xs text-text-muted">—</span>}
              {versions.map(([v, count]) => (
                <Badge key={v} variant="default" size="sm">v{v}: {count}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function SilentSdks() {
  const { data: silent, isLoading } = useSilentSdks();
  if (isLoading || !silent || silent.length === 0) return null;
  return (
    <div className="space-y-2">
      <span className="text-xs font-mono text-warning">Silent SDKs ({silent.length})</span>
      <DataTable
        columns={[
          { key: 'sdk_id', header: 'SDK ID', render: (r: SilentSDK) => <span className="font-mono text-xs text-text-secondary">{r.sdk_id}</span> },
          { key: 'platform', header: 'Platform', render: (r: SilentSDK) => <Badge variant="default" size="sm">{r.platform ?? 'unknown'}</Badge> },
          { key: 'sdk_version', header: 'Version', render: (r: SilentSDK) => <span className="text-xs text-text-muted">{r.sdk_version ?? '—'}</span> },
          { key: 'status', header: '', render: () => <span className="flex items-center gap-1 text-xs"><StatusIndicator status="degraded" /><span className="text-text-muted">silent</span></span> },
        ]}
        data={silent}
        keyExtractor={(r: SilentSDK) => r.sdk_id}
      />
    </div>
  );
}

function RemoteConfig() {
  const { toast } = useToast();
  const { data: manifest, isLoading: mLoading } = useSdkManifest();
  const { data: rollout, isLoading: rLoading } = useSdkRollout();
  const { mutate: rollback, isLoading: rollingBack } = useRollbackManifest();
  const { mutate: publish, isLoading: publishing } = usePublishManifest();
  const [features, setFeatures] = useState<Record<string, boolean> | null>(null);

  if (mLoading || rLoading) return <Skeleton className="h-24 w-full" />;

  const activeFeatures = features ?? manifest?.features ?? {};
  const featureKeys = Object.keys(activeFeatures);

  async function handleRollback() {
    const res = await rollback();
    if (res && (res as { rolled_back?: boolean }).rolled_back) {
      queryCache.invalidate('sdk-manifest');
      queryCache.invalidate('sdk-rollout');
      toast.success('Rolled back to previous manifest');
    } else {
      toast.info((res as { message?: string })?.message ?? 'No previous manifest to roll back to');
    }
  }

  async function handlePublish() {
    if (!features) return;
    const res = await publish({ features });
    if (res) {
      queryCache.invalidate('sdk-manifest');
      queryCache.invalidate('sdk-rollout');
      setFeatures(null);
      toast.success('Published new SDK manifest');
    } else {
      toast.error('Publish failed — admin permission may be required');
    }
  }

  function toggleFeature(key: string) {
    const base = features ?? manifest?.features ?? {};
    setFeatures({ ...base, [key]: !base[key] });
  }

  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-mono text-text-muted">Remote config</span>
          {manifest && <Badge variant="default" size="sm">v{manifest.manifest_version}</Badge>}
        </div>

        {!manifest && (
          <p className="text-xs text-text-muted">No manifest published yet. SDKs run with built-in defaults.</p>
        )}

        {manifest && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div><span className="text-text-muted">Schema</span><div className="font-mono text-text-secondary">{manifest.schema_version}</div></div>
            <div><span className="text-text-muted">Min SDK</span><div className="font-mono text-text-secondary">{manifest.min_sdk_version}</div></div>
            <div><span className="text-text-muted">Rollout</span><div className="font-mono text-text-secondary">{pct(manifest.rollout_percentage)}</div></div>
            <div><span className="text-text-muted">Published</span><div className="font-mono text-text-secondary">{manifest.published_at ? new Date(manifest.published_at).toLocaleDateString() : '—'}</div></div>
          </div>
        )}

        {featureKeys.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-text-secondary">SDK features</span>
            <div className="flex flex-wrap gap-2">
              {featureKeys.map(key => (
                <button
                  key={key}
                  type="button"
                  role="switch"
                  aria-checked={activeFeatures[key]}
                  onClick={() => toggleFeature(key)}
                  className={`px-2 py-1 rounded text-xs font-mono border transition-colors ${
                    activeFeatures[key]
                      ? 'bg-accent/20 border-accent text-accent'
                      : 'bg-surface-base border-border-default text-text-muted'
                  }`}
                >
                  {key}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-2 pt-1">
          <Button
            variant="primary"
            size="sm"
            disabled={!features || publishing}
            onClick={() => { void handlePublish(); }}
          >
            {publishing ? '[···]' : 'Publish changes'}
          </Button>
          {rollout?.has_rollback_available && (
            <Button
              variant="ghost"
              size="sm"
              disabled={rollingBack}
              onClick={() => { void handleRollback(); }}
            >
              {rollingBack ? '[···]' : `Roll back to v${rollout.previous_version ?? ''}`}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * Tenant-facing SDK fleet management: see every installed SDK across
 * platforms, its health, which have gone silent, and control the remote
 * config / feature rollout delivered to them.
 */
export function SdkFleetSection() {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-mono text-text-muted">SDK Fleet</span>
      </div>
      <FleetOverview />
      <SilentSdks />
      <RemoteConfig />
    </section>
  );
}
