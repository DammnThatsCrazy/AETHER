import { useEffect, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';

type AnyRecord = Record<string, unknown>;

const OBSERVABILITY_COPY =
  'Aether observes deployments — it does not publish, host, or execute agents.';

interface FleetRow {
  readonly tenant_id: string;
  readonly id: string;
  readonly display_name: string;
  readonly external_platform: string;
  readonly environment: string;
  readonly status: string;
  readonly event_count_24h: number;
  readonly accepted_count_24h: number;
  readonly rejected_count_24h: number;
  readonly error_count_24h: number;
  readonly consent_blocked_count_24h: number;
  readonly health_score: number | null;
  readonly last_event_at: string | null;
}

function Metric({ label, value }: { readonly label: string; readonly value: unknown }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? 0)}</div>
      </CardContent>
    </Card>
  );
}

function statusColor(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'active') return 'success';
  if (status === 'paused') return 'warning';
  if (status === 'error' || status === 'revoked') return 'danger';
  return 'default';
}

function formatTs(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function CountBreakdown({ title, counts }: { readonly title: string; readonly counts: Record<string, number> }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="text-xs font-mono">
        {Object.keys(counts).length === 0 ? <EmptyState title="No deployments" /> : (
          <div className="grid gap-1 md:grid-cols-3">
            {Object.entries(counts).map(([k, n]) => (
              <div key={k} className="flex justify-between rounded border border-border-default px-2 py-1">
                <Badge variant={statusColor(k)}>{k}</Badge>
                <span>{n}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface DetailDrawerProps {
  readonly tenantId: string;
  readonly deploymentId: string;
  readonly onClose: () => void;
}

function DeploymentDetailDrawer({ tenantId, deploymentId, onClose }: DetailDrawerProps) {
  const [detail, setDetail] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail(null);
    api.admin.kyber.agentTelemetryDeployment(tenantId, deploymentId)
      .then((d) => { if (!cancelled) setDetail(d as AnyRecord); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tenantId, deploymentId]);

  const deployment = (detail?.deployment ?? {}) as AnyRecord;
  const health = (detail?.health ?? {}) as Record<string, number | null>;
  const diagnostics = (detail?.diagnostics ?? {}) as AnyRecord;
  const rejectionReasons = (diagnostics.rejection_reasons ?? {}) as Record<string, number>;
  const recentActivity = (detail?.recent_activity ?? []) as AnyRecord[];

  return (
    <div className="fixed inset-y-0 right-0 z-40 w-[480px] max-w-full border-l border-border-default bg-surface-sunken shadow-xl overflow-y-auto p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-mono font-bold text-text-primary">Deployment diagnostics</div>
          <div className="text-[10px] text-text-muted font-mono">{tenantId} / {deploymentId}</div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>[x] Close</Button>
      </div>

      {loading ? <LoadingState lines={6} /> : error ? (
        <EmptyState title="Unable to load deployment diagnostics" description={error} />
      ) : (
        <>
          <Card>
            <CardHeader><CardTitle>Deployment</CardTitle></CardHeader>
            <CardContent className="text-xs font-mono space-y-1">
              <div className="flex justify-between"><span className="text-text-muted">Name</span><span className="text-text-primary">{String(deployment.display_name ?? '—')}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Platform</span><Badge variant="info">{String(deployment.external_platform ?? '—')}</Badge></div>
              <div className="flex justify-between"><span className="text-text-muted">Environment</span><span>{String(deployment.environment ?? '—')}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Status</span><Badge variant={statusColor(String(deployment.status ?? ''))}>{String(deployment.status ?? '—')}</Badge></div>
              <div className="flex justify-between"><span className="text-text-muted">Consent mode</span><span>{String(deployment.consent_mode ?? '—')}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Last event</span><span>{formatTs(deployment.last_event_at as string | null)}</span></div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Health (24h)</CardTitle></CardHeader>
            <CardContent className="text-xs font-mono space-y-1">
              <div className="flex justify-between"><span className="text-text-muted">Events</span><span>{health.event_count_24h ?? 0}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Accepted</span><span className="text-success">{health.accepted_count_24h ?? 0}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Rejected</span><span className="text-warning">{health.rejected_count_24h ?? 0}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Errors</span><span className="text-danger">{health.error_count_24h ?? 0}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Consent blocked</span><span>{health.consent_blocked_count_24h ?? 0}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Health score</span><span>{health.health_score ?? '—'}</span></div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Rejection reasons</CardTitle></CardHeader>
            <CardContent className="text-xs font-mono">
              {Object.keys(rejectionReasons).length === 0 ? (
                <div className="text-text-muted">No rejections in the last 24h.</div>
              ) : (
                <div className="space-y-1">
                  {Object.entries(rejectionReasons).map(([reason, count]) => (
                    <div key={reason} className="flex justify-between">
                      <span className="text-text-secondary">{reason}</span>
                      <span className="text-warning">{count}</span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Recent activity</CardTitle></CardHeader>
            <CardContent className="text-xs font-mono">
              {recentActivity.length === 0 ? (
                <div className="text-text-muted">No recent lifecycle activity.</div>
              ) : (
                <div className="space-y-1">
                  {recentActivity.map((entry, i) => (
                    <div key={String(entry.id ?? i)} className="flex justify-between border-b border-border-subtle last:border-0 py-1">
                      <span className="text-text-primary">{String(entry.action ?? '—')}</span>
                      <span className="text-text-muted">{formatTs(entry.occurred_at as string | null)}</span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

export function AgentTelemetryPage() {
  const enabled = isFeatureEnabled('enableExternalAgentTelemetry');
  const [data, setData] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ tenantId: string; deploymentId: string } | null>(null);

  useEffect(() => {
    if (!enabled) return;
    api.admin.kyber.agentTelemetryDeployments()
      .then((d) => setData(d as AnyRecord))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [enabled]);

  if (!enabled) {
    return (
      <PageWrapper title="Agent Telemetry" subtitle={OBSERVABILITY_COPY}>
        <EmptyState
          title="External agent telemetry is disabled"
          description='Enable the "enableExternalAgentTelemetry" feature flag (VITE_FEATURE_FLAGS) to view fleet-wide external agent deployment observability.'
        />
      </PageWrapper>
    );
  }

  if (loading) return <PageWrapper title="Agent Telemetry"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Agent Telemetry"><EmptyState title="Unable to load agent telemetry" description={error} /></PageWrapper>;

  const d = data ?? {};
  const byStatus = (d.counts_by_status ?? {}) as Record<string, number>;
  const byPlatform = (d.counts_by_platform ?? {}) as Record<string, number>;
  const rows = (d.deployments ?? []) as FleetRow[];

  return (
    <PageWrapper
      title="Agent Telemetry"
      subtitle={`Fleet-wide, cross-tenant view of external agent deployment telemetry health. ${OBSERVABILITY_COPY}`}
    >
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Total deployments" value={d.total_deployments ?? rows.length} />
        <Metric label="Active" value={d.active_deployments ?? byStatus.active} />
        <Metric label="Tenants with deployments" value={d.tenants_with_deployments} />
        <Metric label="Events 24h" value={d.events_24h} />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <CountBreakdown title="Deployments by status" counts={byStatus} />
        <CountBreakdown title="Deployments by platform" counts={byPlatform} />
      </div>

      <Card>
        <CardHeader><CardTitle>Per-deployment telemetry (24h)</CardTitle></CardHeader>
        <CardContent>
          {rows.length === 0 ? (
            <EmptyState
              title="No external agent deployments"
              description="No tenant has registered an external agent deployment yet."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono border-collapse">
                <thead>
                  <tr className="border-b border-border-default text-text-muted">
                    <th className="py-2 px-2 text-left">Tenant</th>
                    <th className="py-2 px-2 text-left">Deployment</th>
                    <th className="py-2 px-2 text-left">Platform</th>
                    <th className="py-2 px-2 text-left">Status</th>
                    <th className="py-2 px-2 text-right">Accepted</th>
                    <th className="py-2 px-2 text-right">Rejected</th>
                    <th className="py-2 px-2 text-right">Consent blocked</th>
                    <th className="py-2 px-2 text-right">Health</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={`${row.tenant_id}:${row.id}`}
                      className="border-b border-border-subtle hover:bg-surface-hover cursor-pointer"
                      onClick={() => setSelected({ tenantId: row.tenant_id, deploymentId: row.id })}
                    >
                      <td className="py-2 px-2 text-text-muted">{row.tenant_id}</td>
                      <td className="py-2 px-2">
                        <div className="font-semibold text-text-primary">{row.display_name}</div>
                        <div className="text-text-faint">{row.id}</div>
                      </td>
                      <td className="py-2 px-2"><Badge variant="info">{row.external_platform}</Badge></td>
                      <td className="py-2 px-2"><Badge variant={statusColor(row.status)}>{row.status}</Badge></td>
                      <td className="py-2 px-2 text-right text-success">{row.accepted_count_24h}</td>
                      <td className="py-2 px-2 text-right text-warning">{row.rejected_count_24h}</td>
                      <td className="py-2 px-2 text-right">{row.consent_blocked_count_24h}</td>
                      <td className="py-2 px-2 text-right">{row.health_score ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {selected && (
        <DeploymentDetailDrawer
          tenantId={selected.tenantId}
          deploymentId={selected.deploymentId}
          onClose={() => setSelected(null)}
        />
      )}
    </PageWrapper>
  );
}
