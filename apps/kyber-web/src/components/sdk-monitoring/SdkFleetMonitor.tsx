import { useState } from 'react';
import { Card, CardContent } from '@aether/ui';
import { useSdkHealth } from '@kyber/features/sdk-health';
import { SdkHealthCard } from './SdkHealthCard';
import { SdkDriftAlert } from './SdkDriftAlert';
import type { SDKFleetStatus } from '@kyber/types/sdk-health';

interface SdkFleetMonitorProps {
  readonly className?: string;
}

function FleetSummaryBadge({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 px-3">
      <span className={`text-2xl font-bold tabular-nums ${color}`}>{count}</span>
      <span className="text-[10px] text-text-muted uppercase tracking-wide">{label}</span>
    </div>
  );
}

function VersionDistribution({ versions }: { versions: Record<string, number> }) {
  const entries = Object.entries(versions).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return null;
  return (
    <div className="text-[11px] space-y-1">
      <div className="text-text-muted uppercase tracking-wide text-[10px] mb-1">SDK Versions</div>
      {entries.map(([v, count]) => (
        <div key={v} className="flex items-center justify-between">
          <span className="font-mono text-text-secondary">{v}</span>
          <span className="text-text-muted">{count}</span>
        </div>
      ))}
    </div>
  );
}

export function SdkFleetMonitor({ className }: SdkFleetMonitorProps) {
  const [selectedSdkId, setSelectedSdkId] = useState<string | undefined>();
  const { fleet, driftIncidents, selectedScore, rolloutStatus, isLoading, error, refresh } =
    useSdkHealth(selectedSdkId);

  if (isLoading && fleet === null) {
    return (
      <div className={`p-4 text-xs text-text-muted animate-pulse ${className ?? ''}`}>
        Loading SDK fleet data…
      </div>
    );
  }

  if (error) {
    return (
      <div className={`p-4 text-xs text-red-400 ${className ?? ''}`}>
        Error: {error}
        <button onClick={refresh} className="ml-2 underline hover:no-underline">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className={`space-y-4 ${className ?? ''}`}>
      {/* Fleet Summary Bar */}
      {fleet && <FleetSummaryBar fleet={fleet} onRefresh={refresh} />}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Drift Incidents */}
        <div className="lg:col-span-2 space-y-2">
          <SectionHeader title="Drift Incidents" count={driftIncidents.length} />
          <SdkDriftAlert incidents={driftIncidents} />
        </div>

        {/* Version Distribution + Rollout */}
        <div className="space-y-4">
          {fleet && <VersionDistribution versions={fleet.versions} />}
          {rolloutStatus && (
            <div className="text-[11px] space-y-1">
              <div className="text-text-muted uppercase tracking-wide text-[10px] mb-1">Rollout</div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Current version</span>
                <span className="font-mono">{rolloutStatus.current_version ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Rollout %</span>
                <span className="font-mono">{rolloutStatus.current_rollout_pct ?? '—'}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Rollback available</span>
                <span className={rolloutStatus.has_rollback_available ? 'text-green-400' : 'text-text-muted'}>
                  {rolloutStatus.has_rollback_available ? 'Yes' : 'No'}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Selected SDK Drill-Down */}
      {selectedSdkId && selectedScore && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <SectionHeader title="Selected SDK" />
            <button
              onClick={() => setSelectedSdkId(undefined)}
              className="text-[10px] text-text-muted hover:text-text-primary"
            >
              ✕ Clear
            </button>
          </div>
          <SdkHealthCard score={selectedScore} />
        </div>
      )}
    </div>
  );
}

function FleetSummaryBar({ fleet, onRefresh }: { fleet: SDKFleetStatus; onRefresh: () => void }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between py-3 px-4">
        <div className="flex items-center divide-x divide-border-subtle">
          <FleetSummaryBadge label="Total" count={fleet.total_instances} color="text-text-primary" />
          <FleetSummaryBadge label="Healthy" count={fleet.healthy_count} color="text-green-400" />
          <FleetSummaryBadge label="Degraded" count={fleet.degraded_count} color="text-yellow-400" />
          <FleetSummaryBadge label="Unhealthy" count={fleet.unhealthy_count} color="text-red-400" />
          <FleetSummaryBadge label="Silent" count={fleet.silent_count} color="text-text-muted" />
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-lg font-bold tabular-nums text-text-primary">
              {fleet.avg_health_score.toFixed(0)}
            </div>
            <div className="text-[10px] text-text-muted">Avg Score</div>
          </div>
          <button
            onClick={onRefresh}
            className="text-[10px] text-text-muted hover:text-text-primary border border-border-subtle rounded px-2 py-1"
          >
            ↺ Refresh
          </button>
        </div>
      </CardContent>
    </Card>
  );
}

function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium text-text-primary">{title}</span>
      {count !== undefined && (
        <span className="text-[10px] bg-surface-subtle text-text-muted rounded-full px-1.5 py-0.5">
          {count}
        </span>
      )}
    </div>
  );
}
