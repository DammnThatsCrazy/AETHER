import { useState, useMemo } from 'react';
import {
  Card, CardHeader, CardTitle, CardContent,
  Badge, SeverityBadge, StatusIndicator, Button,
  Tabs, TabsList, TabsTrigger, TabsContent,
  DataTable, GlyphIcon, TerminalSeparator, Toggle,
  ScrollArea,
} from '@shiki/components/system';
import { PageWrapper } from '@shiki/components/layout';
import { cn, formatRelativeTime, formatTimestamp } from '@shiki/lib/utils';
import { usePermissions, PermissionGate } from '@shiki/features/permissions';
import type { ErrorFingerprint, Severity, DependencyHealth, CircuitBreakerState, AdapterReadiness, EnvValidation, LagMetric } from '@shiki/types';
import { getMockSystemHealth } from '@shiki/fixtures/health';

const SEVERITY_ORDER: readonly Severity[] = ['P0', 'P1', 'P2', 'P3', 'info'];

const circuitBreakerColor: Record<string, string> = {
  closed: 'text-success',
  open: 'text-danger',
  'half-open': 'text-warning',
};

const circuitBreakerBg: Record<string, string> = {
  closed: 'border-success/30',
  open: 'border-danger/30',
  'half-open': 'border-warning/30',
};

const depTypeIcon: Record<string, string> = {
  database: 'db',
  cache: 'cache',
  queue: 'queue',
  api: 'api',
  graph: 'graph',
  storage: 'storage',
  analytics: 'analytics',
};

function LagCard({ title, lag }: { readonly title: string; readonly lag: LagMetric }) {
  const trendColor = lag.trend === 'improving' ? 'text-success' : lag.trend === 'degrading' ? 'text-danger' : 'text-text-secondary';
  const trendArrow = lag.trend === 'improving' ? '\u2193' : lag.trend === 'degrading' ? '\u2191' : '\u2194';

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <div className="text-2xl font-mono font-bold text-text-primary">{lag.currentMs}</div>
            <div className="text-xs text-text-secondary">Current (ms)</div>
          </div>
          <div>
            <div className="text-2xl font-mono font-bold text-text-secondary">{lag.avgMs}</div>
            <div className="text-xs text-text-secondary">Avg (ms)</div>
          </div>
          <div>
            <div className="text-2xl font-mono font-bold text-text-secondary">{lag.maxMs}</div>
            <div className="text-xs text-text-secondary">Max (ms)</div>
          </div>
        </div>
        <div className={cn('text-center mt-3 text-sm font-mono', trendColor)}>
          {trendArrow} {lag.trend}
        </div>
      </CardContent>
    </Card>
  );
}

export function DiagnosticsPage() {
  const health = useMemo(() => getMockSystemHealth(), []);
  const { canDiagnose } = usePermissions();

  const [fingerprints, setFingerprints] = useState<ErrorFingerprint[]>(
    () => [...health.errorFingerprints] as ErrorFingerprint[],
  );

  const handleToggleSuppress = (fp: string) => {
    setFingerprints(prev =>
      prev.map(e =>
        e.fingerprint === fp ? { ...e, suppressed: !e.suppressed } : e,
      ),
    );
  };

  const fingerprintColumns = useMemo(() => [
    {
      key: 'fingerprint',
      header: 'Fingerprint',
      render: (row: ErrorFingerprint) => (
        <span className="font-mono text-accent">{row.fingerprint}</span>
      ),
    },
    {
      key: 'message',
      header: 'Message',
      render: (row: ErrorFingerprint) => (
        <span className="text-text-primary max-w-xs truncate block">{row.message}</span>
      ),
      className: 'max-w-xs',
    },
    {
      key: 'count',
      header: 'Count',
      render: (row: ErrorFingerprint) => (
        <span className="font-mono font-bold">{row.count}</span>
      ),
    },
    {
      key: 'severity',
      header: 'Severity',
      render: (row: ErrorFingerprint) => <SeverityBadge severity={row.severity} />,
    },
    {
      key: 'firstSeen',
      header: 'First Seen',
      render: (row: ErrorFingerprint) => (
        <span className="text-text-secondary">{formatRelativeTime(row.firstSeen)}</span>
      ),
    },
    {
      key: 'lastSeen',
      header: 'Last Seen',
      render: (row: ErrorFingerprint) => (
        <span className="text-text-secondary">{formatRelativeTime(row.lastSeen)}</span>
      ),
    },
    {
      key: 'suppressed',
      header: 'Suppress',
      render: (row: ErrorFingerprint) => (
        <PermissionGate
          requires="canDiagnose"
          fallback={
            <span className={cn('text-xs font-mono', row.suppressed ? 'text-warning' : 'text-text-muted')}>
              {row.suppressed ? 'suppressed' : '--'}
            </span>
          }
        >
          <Toggle
            checked={row.suppressed}
            onChange={() => handleToggleSuppress(row.fingerprint)}
            label={row.suppressed ? 'Suppressed' : 'Active'}
          />
        </PermissionGate>
      ),
    },
  ], [canDiagnose]);

  const overallStatus = health.overall.status;

  return (
    <PageWrapper
      title="System Diagnostics"
      subtitle="Infrastructure health, circuit breakers, error fingerprints, and environment validation"
      actions={
        <Badge variant={overallStatus === 'healthy' ? 'success' : overallStatus === 'degraded' ? 'warning' : 'danger'}>
          {overallStatus.toUpperCase()}
        </Badge>
      }
    >
      {/* Overall Health */}
      <Card>
        <CardContent>
          <div className="flex items-center gap-4 py-2">
            <StatusIndicator status={overallStatus} size="md" />
            <div>
              <div className="text-lg font-mono font-bold text-text-primary capitalize">{overallStatus}</div>
              {health.overall.message && (
                <div className="text-sm text-text-secondary">{health.overall.message}</div>
              )}
              <div className="text-xs text-text-muted mt-1">
                Last checked: {formatTimestamp(health.overall.lastChecked)}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="dependencies">
        <TabsList>
          <TabsTrigger value="dependencies">Dependencies</TabsTrigger>
          <TabsTrigger value="breakers">Circuit Breakers</TabsTrigger>
          <TabsTrigger value="errors">Error Fingerprints</TabsTrigger>
          <TabsTrigger value="metrics">Lag Metrics</TabsTrigger>
          <TabsTrigger value="adapters">Adapters & Connectivity</TabsTrigger>
          <TabsTrigger value="env">Environment</TabsTrigger>
        </TabsList>

        {/* Dependencies Tab */}
        <TabsContent value="dependencies">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            {health.dependencies.map((dep: DependencyHealth) => (
              <Card key={dep.name}>
                <CardHeader>
                  <CardTitle>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <GlyphIcon glyph={depTypeIcon[dep.type] ?? 'default'} className="text-text-muted" />
                        <span className="font-mono">{dep.name}</span>
                      </div>
                      <StatusIndicator status={dep.status.status} size="sm" />
                    </div>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-text-secondary">Type</span>
                      <Badge>{dep.type}</Badge>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-secondary">Latency</span>
                      <span className={cn(
                        'font-mono',
                        dep.latencyMs < 0 ? 'text-danger' : dep.latencyMs > 30 ? 'text-warning' : 'text-success',
                      )}>
                        {dep.latencyMs < 0 ? 'N/A' : `${dep.latencyMs}ms`}
                      </span>
                    </div>
                    {dep.status.message && (
                      <div className="text-warning text-xs mt-1">{dep.status.message}</div>
                    )}
                    {dep.lastError && (
                      <div className="text-danger text-xs mt-1 break-all">{dep.lastError}</div>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        {/* Circuit Breakers Tab */}
        <TabsContent value="breakers">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {health.circuitBreakers.map((cb: CircuitBreakerState) => (
              <Card key={cb.name} className={cn('border', circuitBreakerBg[cb.state])}>
                <CardHeader>
                  <CardTitle>
                    <div className="flex items-center justify-between">
                      <span className="font-mono">{cb.name}</span>
                      <span className={cn('text-xs font-mono font-bold uppercase', circuitBreakerColor[cb.state])}>
                        {cb.state}
                      </span>
                    </div>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-text-secondary">Failure Count</span>
                      <span className={cn('font-mono', cb.failureCount > 0 ? 'text-danger font-bold' : 'text-text-muted')}>
                        {cb.failureCount}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-secondary">Last Failure</span>
                      <span className="text-text-secondary font-mono">
                        {cb.lastFailure ? formatRelativeTime(cb.lastFailure) : 'Never'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-secondary">Next Retry</span>
                      <span className="text-text-secondary font-mono">
                        {cb.nextRetry ? formatRelativeTime(cb.nextRetry) : 'N/A'}
                      </span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        {/* Error Fingerprints Tab */}
        <TabsContent value="errors">
          {/* Severity Distribution */}
          <Card className="mb-4">
            <CardHeader>
              <CardTitle>Severity Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-end gap-4">
                {SEVERITY_ORDER.map((sev) => {
                  const count = health.severityDistribution[sev];
                  const maxCount = Math.max(...Object.values(health.severityDistribution));
                  const heightPct = maxCount > 0 ? (count / maxCount) * 100 : 0;
                  return (
                    <div key={sev} className="flex flex-col items-center gap-1 flex-1">
                      <span className="text-xs font-mono font-bold text-text-primary">{count}</span>
                      <div className="w-full bg-surface-raised rounded-t relative" style={{ height: '80px' }}>
                        <div
                          className={cn(
                            'absolute bottom-0 w-full rounded-t',
                            sev === 'P0' ? 'bg-danger' : sev === 'P1' ? 'bg-warning' : sev === 'P2' ? 'bg-info' : sev === 'P3' ? 'bg-accent' : 'bg-text-muted',
                          )}
                          style={{ height: `${heightPct}%` }}
                        />
                      </div>
                      <SeverityBadge severity={sev} />
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          <TerminalSeparator />

          {/* Error Fingerprint Table */}
          <Card>
            <CardHeader>
              <CardTitle>Error Fingerprints</CardTitle>
            </CardHeader>
            <CardContent>
              <ScrollArea maxHeight="400px">
                <DataTable
                  columns={fingerprintColumns}
                  data={fingerprints}
                  keyExtractor={(row) => row.fingerprint}
                />
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Lag Metrics Tab */}
        <TabsContent value="metrics">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <LagCard title="Event Processing Lag" lag={health.eventLag} />
            <LagCard title="Graph Synchronization Lag" lag={health.graphLag} />
          </div>
        </TabsContent>

        {/* Adapters & Connectivity Tab */}
        <TabsContent value="adapters">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Connectivity Checks */}
            <Card>
              <CardHeader>
                <CardTitle>Connectivity</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {health.adapterReadiness
                    .filter((a: AdapterReadiness) => a.type !== 'mock')
                    .map((adapter: AdapterReadiness) => (
                      <div key={adapter.name} className="flex items-center justify-between py-2 border-b border-border-subtle last:border-0">
                        <div className="flex items-center gap-2">
                          <StatusIndicator status={adapter.ready ? 'healthy' : 'unhealthy'} size="sm" />
                          <span className="font-mono text-sm text-text-primary">{adapter.name}</span>
                        </div>
                        <Badge variant={adapter.ready ? 'success' : 'danger'}>
                          {adapter.ready ? 'Ready' : 'Not Ready'}
                        </Badge>
                      </div>
                    ))}
                </div>
              </CardContent>
            </Card>

            {/* All Adapter Readiness */}
            <Card>
              <CardHeader>
                <CardTitle>Adapter Readiness</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {health.adapterReadiness.map((adapter: AdapterReadiness) => (
                    <div key={adapter.name} className="flex items-center justify-between py-2 border-b border-border-subtle last:border-0">
                      <div>
                        <div className="flex items-center gap-2">
                          <StatusIndicator status={adapter.ready ? 'healthy' : 'unhealthy'} size="sm" />
                          <span className="font-mono text-sm text-text-primary">{adapter.name}</span>
                        </div>
                        <div className="text-xs text-text-muted ml-5">
                          Type: {adapter.type} | Checked: {formatRelativeTime(adapter.lastCheck)}
                        </div>
                      </div>
                      <Badge variant={adapter.ready ? 'success' : 'danger'}>
                        {adapter.ready ? 'Ready' : 'Error'}
                      </Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Environment Validation Tab */}
        <TabsContent value="env">
          <Card>
            <CardHeader>
              <CardTitle>Environment Variables</CardTitle>
            </CardHeader>
            <CardContent>
              <ScrollArea maxHeight="500px">
                <div className="space-y-2">
                  {health.environmentValidation.map((env: EnvValidation) => (
                    <div
                      key={env.variable}
                      className={cn(
                        'flex items-center justify-between py-2 px-3 rounded border',
                        env.valid
                          ? 'border-border-subtle bg-surface-default'
                          : env.required
                            ? 'border-danger/30 bg-danger/5'
                            : 'border-warning/30 bg-warning/5',
                      )}
                    >
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm text-text-primary">{env.variable}</span>
                          {env.required && <Badge variant="warning">required</Badge>}
                        </div>
                        {env.message && (
                          <div className="text-xs text-text-muted mt-0.5">{env.message}</div>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-xs">
                        <span className={cn('font-mono', env.present ? 'text-success' : 'text-danger')}>
                          {env.present ? 'present' : 'missing'}
                        </span>
                        <span className={cn('font-mono', env.valid ? 'text-success' : 'text-danger')}>
                          {env.valid ? 'valid' : 'invalid'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
