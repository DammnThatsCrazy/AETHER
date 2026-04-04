import { useState } from 'react';
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Badge,
  SeverityBadge,
  StatusIndicator,
  EnvironmentBadge,
  Button,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  EmptyState,
  ScrollArea,
  GlyphIcon,
  TerminalSeparator,
  LoadingState,
  ErrorState,
} from '@shiki/components/system';
import { PageWrapper } from '@shiki/components/layout';
import { cn, formatRelativeTime, formatCompactNumber, formatPercentage } from '@shiki/lib/utils';
import { getEnvironment, getRuntimeMode } from '@shiki/lib/env';
import { useMissionData } from '@shiki/features/mission';
import { useDiagnosticsData } from '@shiki/features/diagnostics';
import type { KeyChange, Severity } from '@shiki/types';

const SEVERITY_COLORS: Record<string, string> = {
  P0: 'border-l-danger',
  P1: 'border-l-warning',
  P2: 'border-l-caution',
  P3: 'border-l-info',
  info: 'border-l-accent',
};

const ACTION_CLASS_LABELS: Record<number, string> = {
  0: 'Observation',
  1: 'Informational',
  2: 'Assistive',
  3: 'Operational',
  4: 'Structural',
  5: 'Irreversible',
};

const HEALTH_STATUS_VARIANT: Record<string, string> = {
  healthy: 'success',
  degraded: 'warning',
  unhealthy: 'danger',
  unknown: 'muted',
};

function KeyChangeItem({ change }: { readonly change: KeyChange }) {
  return (
    <div className={cn('flex items-start gap-3 p-2 border-l-2 bg-surface-raised rounded-r', SEVERITY_COLORS[change.severity])}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <SeverityBadge severity={change.severity} />
          <Badge>{change.controller}</Badge>
          {change.entityType && <Badge variant="default">{change.entityType}</Badge>}
        </div>
        <div className="text-xs text-text-primary">{change.description}</div>
        <div className="text-[10px] text-text-muted mt-1">{formatRelativeTime(change.timestamp)}</div>
      </div>
    </div>
  );
}

export function MissionPage() {
  const environment = getEnvironment();
  const mode = getRuntimeMode();
  const { data, isLoading, error } = useMissionData();
  const { health: systemHealth, isLoading: healthLoading, error: healthError } = useDiagnosticsData();
  const [keyChangeTab, setKeyChangeTab] = useState<'1h' | '24h' | '7d'>('1h');

  if (isLoading || healthLoading) {
    return <PageWrapper title="Mission" subtitle="Executive command brief and system posture overview"><LoadingState lines={5} /></PageWrapper>;
  }

  if (error || healthError) {
    return <PageWrapper title="Mission" subtitle="Executive command brief and system posture overview"><ErrorState message={error ?? healthError ?? 'Unknown error'} /></PageWrapper>;
  }

  if (!data || !systemHealth) {
    return <PageWrapper title="Mission" subtitle="Executive command brief and system posture overview"><EmptyState title="No data available" /></PageWrapper>;
  }

  const keyChangesMap: Record<string, readonly KeyChange[]> = {
    '1h': data.keyChanges1h,
    '24h': data.keyChanges24h,
    '7d': data.keyChanges7d,
  };
  const activeKeyChanges = keyChangesMap[keyChangeTab] ?? [];

  const circuitBreakerSummary = {
    closed: systemHealth.circuitBreakers.filter(cb => cb.state === 'closed').length,
    open: systemHealth.circuitBreakers.filter(cb => cb.state === 'open').length,
    halfOpen: systemHealth.circuitBreakers.filter(cb => cb.state === 'half-open').length,
  };

  const topError = systemHealth.errorFingerprints
    .filter(e => !e.suppressed)
    .sort((a, b) => {
      const order: Record<Severity, number> = { P0: 0, P1: 1, P2: 2, P3: 3, info: 4 };
      return (order[a.severity] ?? 4) - (order[b.severity] ?? 4);
    })[0];

  return (
    <PageWrapper
      title="Mission"
      subtitle="Executive command brief and system posture overview"
      actions={
        <div className="flex items-center gap-2">
          <EnvironmentBadge environment={environment} />
          <Badge variant={mode === 'mocked' ? 'warning' : 'info'}>
            {mode.toUpperCase()}
          </Badge>
        </div>
      }
    >
      {/* ---- Row 1: Health Summary Cards ---- */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        {/* Global Health */}
        <Card>
          <CardHeader>
            <CardTitle>Global Health</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 mb-2">
              <StatusIndicator status={data.globalHealth.status} />
              <span className={cn('text-sm font-bold font-mono', {
                'text-success': data.globalHealth.status === 'healthy',
                'text-warning': data.globalHealth.status === 'degraded',
                'text-danger': data.globalHealth.status === 'unhealthy',
                'text-text-muted': data.globalHealth.status === 'unknown',
              })}>
                {data.globalHealth.status.toUpperCase()}
              </span>
            </div>
            {data.globalHealth.message && (
              <p className="text-[11px] text-text-secondary">{data.globalHealth.message}</p>
            )}
            <div className="text-[10px] text-text-muted mt-1">
              Checked {formatRelativeTime(data.globalHealth.lastChecked)}
            </div>
          </CardContent>
        </Card>

        {/* Customer Health */}
        <Card>
          <CardHeader>
            <CardTitle>Customer Health</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 mb-2">
              <StatusIndicator status={data.customerHealth.status.status} />
              <span className="text-sm font-bold font-mono">
                {data.customerHealth.healthy}/{data.customerHealth.total}
              </span>
              <span className="text-[11px] text-text-muted">healthy</span>
            </div>
            <div className="flex gap-3 text-[11px]">
              {data.customerHealth.degraded > 0 && (
                <span className="text-warning">{data.customerHealth.degraded} degraded</span>
              )}
              {data.customerHealth.unhealthy > 0 && (
                <span className="text-danger">{data.customerHealth.unhealthy} unhealthy</span>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Agent Health */}
        <Card>
          <CardHeader>
            <CardTitle>Agent Health</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 mb-2">
              <StatusIndicator status={data.agentHealth.status.status} />
              <span className="text-sm font-bold font-mono">
                {data.agentHealth.active}/{data.agentHealth.total}
              </span>
              <span className="text-[11px] text-text-muted">active</span>
            </div>
            <div className="flex gap-3 text-[11px]">
              {data.agentHealth.stuck > 0 && (
                <span className="text-danger">{data.agentHealth.stuck} stuck</span>
              )}
              {data.agentHealth.idle > 0 && (
                <span className="text-text-muted">{data.agentHealth.idle} idle</span>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Graph Health */}
        <Card>
          <CardHeader>
            <CardTitle>Graph Health</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 mb-2">
              <StatusIndicator status={data.graphHealth.status.status} />
              <span className={cn('text-sm font-bold font-mono', {
                'text-success': data.graphHealth.status.status === 'healthy',
                'text-warning': data.graphHealth.status.status === 'degraded',
                'text-danger': data.graphHealth.status.status === 'unhealthy',
              })}>
                {data.graphHealth.status.status.toUpperCase()}
              </span>
            </div>
            <div className="text-[11px] text-text-secondary">
              {formatCompactNumber(data.graphHealth.nodeCount)} nodes / {formatCompactNumber(data.graphHealth.edgeCount)} edges
            </div>
            <div className="text-[10px] text-text-muted mt-1">
              Last mutation {formatRelativeTime(data.graphHealth.lastMutation)}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ---- Row 2: Pending Approvals, Active Alerts, Throughput ---- */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* Pending Approvals */}
        <Card className="cursor-pointer hover:border-accent transition-colors" onClick={() => window.location.href = '/review'}>
          <CardHeader>
            <CardTitle>Pending Approvals</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-3">
              <span className="text-3xl font-bold font-mono text-accent">{data.pendingApprovals}</span>
              <span className="text-xs text-text-secondary">batches awaiting review</span>
            </div>
            <div className="text-[10px] text-accent mt-2 font-mono">{'\u2192'} Go to Review Queue</div>
          </CardContent>
        </Card>

        {/* Active Alerts */}
        <Card>
          <CardHeader>
            <CardTitle>Active Alerts</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-3 mb-2">
              <span className="text-3xl font-bold font-mono text-danger">{data.activeAlerts.total}</span>
              <span className="text-xs text-text-secondary">total active</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {(Object.entries(data.activeAlerts.bySeverity) as [Severity, number][]).map(([sev, count]) =>
                count > 0 ? (
                  <div key={sev} className="flex items-center gap-1">
                    <SeverityBadge severity={sev} />
                    <span className="text-[11px] text-text-secondary font-mono">{count}</span>
                  </div>
                ) : null
              )}
            </div>
          </CardContent>
        </Card>

        {/* Throughput */}
        <Card>
          <CardHeader>
            <CardTitle>Live Throughput</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-3xl font-bold font-mono text-text-primary">
                {formatCompactNumber(data.throughput.eventsPerSecond)}
              </span>
              <span className="text-xs text-text-muted">evt/s</span>
              <span className={cn('text-xs font-mono', {
                'text-success': data.throughput.trend === 'up',
                'text-danger': data.throughput.trend === 'down',
                'text-text-muted': data.throughput.trend === 'stable',
              })}>
                {data.throughput.trend === 'up' ? '\u2191' : data.throughput.trend === 'down' ? '\u2193' : '\u2192'}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px] text-text-secondary">
              <div>{formatCompactNumber(data.throughput.eventsPerMinute)} evt/min</div>
              <div>{formatCompactNumber(data.throughput.totalLast1h)} last 1h</div>
              <div>{formatCompactNumber(data.throughput.totalLast24h)} last 24h</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ---- Row 3: Command Brief ---- */}
      <Card>
        <CardHeader>
          <CardTitle>
            <GlyphIcon glyph="terminal" className="inline mr-2" />
            AI Command Brief
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="bg-surface-sunken border border-border-subtle rounded p-4 font-mono text-xs text-text-secondary leading-relaxed whitespace-pre-wrap">
            {data.commandBrief}
          </div>
        </CardContent>
      </Card>

      <TerminalSeparator />

      {/* ---- Row 4: Key Changes + Recommended Actions ---- */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {/* Key Changes */}
        <Card>
          <CardHeader>
            <CardTitle>Key Changes</CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="1h" onChange={(v) => setKeyChangeTab(v as '1h' | '24h' | '7d')}>
              <TabsList>
                <TabsTrigger value="1h">Last 1h</TabsTrigger>
                <TabsTrigger value="24h">Last 24h</TabsTrigger>
                <TabsTrigger value="7d">Last 7d</TabsTrigger>
              </TabsList>
              <TabsContent value={keyChangeTab}>
                {activeKeyChanges.length === 0 ? (
                  <EmptyState title="No key changes" icon={'\u2713'} />
                ) : (
                  <ScrollArea maxHeight="320px">
                    <div className="space-y-2">
                      {activeKeyChanges.map(change => (
                        <KeyChangeItem key={change.id} change={change} />
                      ))}
                    </div>
                  </ScrollArea>
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        {/* Recommended Actions */}
        <Card>
          <CardHeader>
            <CardTitle>Recommended Next Actions</CardTitle>
          </CardHeader>
          <CardContent>
            {data.recommendedActions.length === 0 ? (
              <EmptyState title="No recommended actions" icon={'\u2713'} />
            ) : (
              <ScrollArea maxHeight="320px">
                <div className="space-y-2">
                  {data.recommendedActions.map(action => (
                    <div
                      key={action.id}
                      className="p-3 border border-border-subtle rounded bg-surface-raised"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant={action.actionClass >= 3 ? 'warning' : 'info'}>
                          Class {action.actionClass}: {ACTION_CLASS_LABELS[action.actionClass]}
                        </Badge>
                        <Badge>{action.controller}</Badge>
                        {action.reversible && <Badge variant="success">Reversible</Badge>}
                        {!action.reversible && <Badge variant="danger">Irreversible</Badge>}
                      </div>
                      <div className="text-xs font-medium text-text-primary mb-1">{action.title}</div>
                      <div className="text-[11px] text-text-secondary mb-1">{action.description}</div>
                      <div className="flex items-center gap-3 text-[10px] text-text-muted">
                        <span>Confidence: {formatPercentage(action.confidence)}</span>
                        <span>{action.rationale}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ---- Row 5: Needs Help (Customers + Agents) ---- */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {/* Customers Needing Help */}
        <Card>
          <CardHeader>
            <CardTitle>Customers Needing Help</CardTitle>
            {data.customersNeedingHelp.length > 0 && (
              <Badge variant="danger">{data.customersNeedingHelp.length}</Badge>
            )}
          </CardHeader>
          <CardContent>
            {data.customersNeedingHelp.length === 0 ? (
              <EmptyState title="All customers healthy" icon={'\u2713'} />
            ) : (
              <div className="space-y-3">
                {data.customersNeedingHelp.map(card => (
                  <div
                    key={card.entityId}
                    className={cn('p-3 border-l-2 rounded bg-surface-raised', SEVERITY_COLORS[card.severity])}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <SeverityBadge severity={card.severity} />
                      <span className="text-xs font-bold text-text-primary">{card.entityName}</span>
                      <span className="text-[10px] text-text-muted">({card.entityId})</span>
                    </div>
                    <div className="text-[11px] text-text-secondary mb-2">{card.reason}</div>
                    <div className="text-[10px] text-text-muted mb-1">Evidence:</div>
                    <ul className="list-disc list-inside text-[10px] text-text-secondary space-y-0.5 mb-2">
                      {card.evidence.map((e, i) => <li key={i}>{e}</li>)}
                    </ul>
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-text-muted">
                        Confidence: {formatPercentage(card.confidence)}
                      </span>
                      <span className="text-[10px] text-text-muted">
                        Flagged {formatRelativeTime(card.flaggedAt)}
                      </span>
                    </div>
                    <div className="mt-1.5 text-[10px] text-accent font-mono">
                      {'\u2192'} {card.recommendedAction}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Agents Needing Help */}
        <Card>
          <CardHeader>
            <CardTitle>Agents Needing Help</CardTitle>
            {data.agentsNeedingHelp.length > 0 && (
              <Badge variant="danger">{data.agentsNeedingHelp.length}</Badge>
            )}
          </CardHeader>
          <CardContent>
            {data.agentsNeedingHelp.length === 0 ? (
              <EmptyState title="All agents operating normally" icon={'\u2713'} />
            ) : (
              <div className="space-y-3">
                {data.agentsNeedingHelp.map(card => (
                  <div
                    key={card.entityId}
                    className={cn('p-3 border-l-2 rounded bg-surface-raised', SEVERITY_COLORS[card.severity])}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <SeverityBadge severity={card.severity} />
                      <span className="text-xs font-bold text-text-primary font-mono">{card.entityName}</span>
                    </div>
                    <div className="text-[11px] text-text-secondary mb-2">{card.reason}</div>
                    <div className="text-[10px] text-text-muted mb-1">Evidence:</div>
                    <ul className="list-disc list-inside text-[10px] text-text-secondary space-y-0.5 mb-2">
                      {card.evidence.map((e, i) => <li key={i}>{e}</li>)}
                    </ul>
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-text-muted">
                        Confidence: {formatPercentage(card.confidence)}
                      </span>
                      <span className="text-[10px] text-text-muted">
                        Flagged {formatRelativeTime(card.flaggedAt)}
                      </span>
                    </div>
                    <div className="mt-1.5 text-[10px] text-accent font-mono">
                      {'\u2192'} {card.recommendedAction}
                    </div>
                    {card.reversible && (
                      <Badge variant="success" className="mt-1">Reversible</Badge>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ---- Row 6: Recent Interventions ---- */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Interventions & Reversions</CardTitle>
        </CardHeader>
        <CardContent>
          {data.recentInterventions.length === 0 ? (
            <EmptyState title="No recent interventions" icon={'\u2713'} />
          ) : (
            <ScrollArea maxHeight="260px">
              <div className="space-y-2">
                {data.recentInterventions.map(intervention => (
                  <div
                    key={intervention.id}
                    className="flex items-start gap-3 p-2 border border-border-subtle rounded bg-surface-raised"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <Badge>{intervention.type}</Badge>
                        {intervention.revertId && <Badge variant="warning">Has Revert</Badge>}
                      </div>
                      <div className="text-xs text-text-primary">{intervention.description}</div>
                      <div className="flex items-center gap-3 mt-1 text-[10px] text-text-muted">
                        <span>By: {intervention.performedBy}</span>
                        <span>{'\u00B7'}</span>
                        <span>{formatRelativeTime(intervention.performedAt)}</span>
                      </div>
                      {intervention.outcome && (
                        <div className="text-[10px] text-text-secondary mt-1">
                          Outcome: {intervention.outcome}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>

      {/* ---- Row 7: Diagnostics Snapshot + Graph Mini-Map ---- */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {/* Compact Diagnostics Snapshot */}
        <Card>
          <CardHeader>
            <CardTitle>Diagnostics Snapshot</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-3 mb-3">
              <div className="text-center p-2 bg-surface-sunken rounded">
                <div className="text-lg font-bold font-mono text-text-primary">
                  {systemHealth.dependencies.length}
                </div>
                <div className="text-[10px] text-text-muted">Dependencies</div>
              </div>
              <div className="text-center p-2 bg-surface-sunken rounded">
                <div className="text-lg font-bold font-mono text-text-primary">
                  {circuitBreakerSummary.closed}/{systemHealth.circuitBreakers.length}
                </div>
                <div className="text-[10px] text-text-muted">CBs Closed</div>
              </div>
              <div className="text-center p-2 bg-surface-sunken rounded">
                <div className={cn('text-lg font-bold font-mono', {
                  'text-danger': circuitBreakerSummary.open > 0,
                  'text-warning': circuitBreakerSummary.open === 0 && circuitBreakerSummary.halfOpen > 0,
                  'text-success': circuitBreakerSummary.open === 0 && circuitBreakerSummary.halfOpen === 0,
                })}>
                  {circuitBreakerSummary.open > 0
                    ? `${circuitBreakerSummary.open} OPEN`
                    : circuitBreakerSummary.halfOpen > 0
                      ? `${circuitBreakerSummary.halfOpen} HALF`
                      : 'ALL OK'}
                </div>
                <div className="text-[10px] text-text-muted">CB State</div>
              </div>
            </div>
            {topError && (
              <div className={cn('p-2 border-l-2 rounded bg-surface-raised text-[11px]', SEVERITY_COLORS[topError.severity])}>
                <div className="flex items-center gap-2 mb-0.5">
                  <SeverityBadge severity={topError.severity} />
                  <span className="text-text-muted font-mono">{topError.fingerprint}</span>
                  <span className="text-text-muted">{'\u00D7'}{topError.count}</span>
                </div>
                <div className="text-text-secondary">{topError.message}</div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Graph Mini-Map Teaser */}
        <Card className="cursor-pointer hover:border-accent transition-colors" onClick={() => window.location.href = '/gouf'}>
          <CardHeader>
            <CardTitle>Graph Overview</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center justify-center p-6 bg-surface-sunken rounded border border-border-subtle">
              <div className="flex items-center gap-6 mb-3">
                <div className="text-center">
                  <div className="text-2xl font-bold font-mono text-text-primary">
                    {formatCompactNumber(data.graphHealth.nodeCount)}
                  </div>
                  <div className="text-[10px] text-text-muted">Nodes</div>
                </div>
                <div className="text-text-muted text-xl">{'\u2194'}</div>
                <div className="text-center">
                  <div className="text-2xl font-bold font-mono text-text-primary">
                    {formatCompactNumber(data.graphHealth.edgeCount)}
                  </div>
                  <div className="text-[10px] text-text-muted">Edges</div>
                </div>
              </div>
              <div className="text-xs text-text-secondary mb-1">
                <StatusIndicator status={data.graphHealth.status.status} />
                <span className="ml-2">{data.graphHealth.status.message}</span>
              </div>
              <div className="text-[10px] text-accent font-mono mt-2">{'\u2192'} Open GOUF Graph Explorer</div>
            </div>
          </CardContent>
        </Card>
      </div>
    </PageWrapper>
  );
}
