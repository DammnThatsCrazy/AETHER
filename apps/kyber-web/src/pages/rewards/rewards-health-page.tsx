import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

// ─── Types ────────────────────────────────────────────────────────────────────

interface RewardsHealthData {
  summary: AnyRecord;
  topTenants: AnyRecord[];
  recentDecisions: AnyRecord[];
  blockedDecisions: AnyRecord[];
  actionStatusBreakdown: AnyRecord;
  failedDeliveries: AnyRecord[];
  railStats: AnyRecord[];
  fraudSummary: AnyRecord;
}

const EMPTY_DATA: RewardsHealthData = {
  summary: {},
  topTenants: [],
  recentDecisions: [],
  blockedDecisions: [],
  actionStatusBreakdown: {},
  failedDeliveries: [],
  railStats: [],
  fraudSummary: {},
};

// ─── Data fetcher ─────────────────────────────────────────────────────────────

async function fetchRewardsHealth(): Promise<RewardsHealthData> {
  const d = await api.admin.kyber.rewardsHealth() as AnyRecord;
  return {
    summary: (d.summary ?? {}) as AnyRecord,
    topTenants: (d.top_tenants ?? d.topTenants ?? []) as AnyRecord[],
    recentDecisions: (d.recent_decisions ?? d.recentDecisions ?? []) as AnyRecord[],
    blockedDecisions: (d.blocked_decisions ?? d.blockedDecisions ?? []) as AnyRecord[],
    actionStatusBreakdown: (d.action_status_breakdown ?? d.actionStatusBreakdown ?? {}) as AnyRecord,
    failedDeliveries: (d.failed_deliveries ?? d.failedDeliveries ?? []) as AnyRecord[],
    railStats: (d.rail_stats ?? d.railStats ?? []) as AnyRecord[],
    fraudSummary: (d.fraud_summary ?? d.fraudSummary ?? {}) as AnyRecord,
  };
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

function useRewardsHealth() {
  const [data, setData] = useState<RewardsHealthData>(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchRewardsHealth()
      .then(d => setData(d))
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  return { data, loading, error, reload: load };
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ label, value, variant }: {
  readonly label: string;
  readonly value: unknown;
  readonly variant?: 'default' | 'danger' | 'warning';
}) {
  const valueClass = variant === 'danger'
    ? 'text-red-500'
    : variant === 'warning'
    ? 'text-yellow-500'
    : 'text-text-primary';
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className={`mt-1 text-2xl font-semibold ${valueClass}`}>{value == null ? 'Unavailable' : String(value)}</div>
      </CardContent>
    </Card>
  );
}

function decisionVariant(decision: string): 'success' | 'warning' | 'danger' | 'default' {
  if (decision === 'eligible') return 'success';
  if (decision === 'ineligible') return 'default';
  if (decision === 'blocked_fraud' || decision === 'blocked') return 'danger';
  return 'default';
}

function actionStatusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'delivered') return 'success';
  if (status === 'pending_approval' || status === 'ready') return 'warning';
  if (status === 'failed' || status === 'dead_lettered') return 'danger';
  return 'default';
}

function BarSegment({ label, count, total }: {
  readonly label: string;
  readonly count: number;
  readonly total: number;
}) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-text-secondary font-mono">{label}</span>
        <span className="text-text-primary font-semibold">{count} <span className="text-text-muted">({pct}%)</span></span>
      </div>
      <div className="h-2 rounded bg-bg-subtle overflow-hidden">
        <div className="h-full rounded bg-accent" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function RewardsHealthPage() {
  const { data, loading, error, reload } = useRewardsHealth();

  if (loading) {
    return (
      <PageWrapper title="Reward Health Dashboard">
        <LoadingState lines={8} />
      </PageWrapper>
    );
  }

  if (error) {
    return (
      <PageWrapper title="Reward Health Dashboard">
        <ErrorState
          title="Unable to load reward health data"
          message={error}
          onRetry={reload}
        />
      </PageWrapper>
    );
  }

  const { summary, topTenants, recentDecisions, blockedDecisions, actionStatusBreakdown, failedDeliveries, railStats, fraudSummary } = data;

  const totalActions: number = Object.values(actionStatusBreakdown).reduce((acc: number, v) => acc + (Number(v) || 0), 0);
  const topFraudReasons = (fraudSummary.top_reasons ?? []) as AnyRecord[];

  return (
    <PageWrapper
      title="Reward Health Dashboard"
      subtitle="Operator view of eligibility decisions, action payloads, webhook delivery, and fraud blocks across all tenants. Aether verifies eligibility only — tenant rails execute."
      actions={<Button onClick={reload} variant="ghost" size="sm">Refresh</Button>}
    >
      {/* Stats row */}
      <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Active Campaigns" value={summary.active_campaigns} />
        <StatCard label="Eligible Decisions (24h)" value={summary.eligible_decisions_24h} />
        <StatCard
          label="Blocked (fraud) (24h)"
          value={summary.blocked_fraud_24h}
          variant={(summary.blocked_fraud_24h ?? 0) > 20 ? 'danger' : 'default'}
        />
        <StatCard
          label="Pending Approvals"
          value={summary.pending_approvals}
          variant={(summary.pending_approvals ?? 0) > 0 ? 'warning' : 'default'}
        />
        <StatCard
          label="Webhook Failures (24h)"
          value={summary.webhook_delivery_failures_24h}
          variant={(summary.webhook_delivery_failures_24h ?? 0) > 0 ? 'warning' : 'default'}
        />
        <StatCard
          label="Dead Letter Queue"
          value={summary.dead_letter_queue_depth}
          variant={(summary.dead_letter_queue_depth ?? 0) > 5 ? 'danger' : 'default'}
        />
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="decisions">Decisions</TabsTrigger>
          <TabsTrigger value="actions">Actions</TabsTrigger>
          <TabsTrigger value="rails">Rails</TabsTrigger>
          <TabsTrigger value="fraud">Fraud Analysis</TabsTrigger>
        </TabsList>

        {/* ── Overview ───────────────────────────────────────────────────────── */}
        <TabsContent value="overview">
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Top 5 Tenants by Activity</CardTitle></CardHeader>
              <CardContent>
                {topTenants.length === 0 ? (
                  <EmptyState title="No tenant activity" description="No reward activity recorded across tenants in the current window." />
                ) : (
                  <DataTable
                    data={topTenants}
                    keyExtractor={(r) => String(r.tenant_id)}
                    columns={[
                      { key: 'tenant_id', header: 'Tenant', render: (r) => <span className="font-mono text-xs">{String(r.tenant_id ?? '—')}</span> },
                      { key: 'campaigns', header: 'Campaigns', render: (r) => r.campaigns == null ? '—' : String(r.campaigns) },
                      { key: 'decisions_24h', header: 'Decisions (24h)', render: (r) => r.decisions_24h == null ? '—' : String(r.decisions_24h) },
                      { key: 'eligible_rate', header: 'Eligible Rate', render: (r) => String(r.eligible_rate ?? '—') },
                      { key: 'pending_approvals', header: 'Pending Approvals', render: (r) => {
                        if (r.pending_approvals == null) return '—';
                        const n = Number(r.pending_approvals);
                        return n > 0 ? <Badge variant="warning">{n}</Badge> : <span className="text-text-muted">0</span>;
                      }},
                    ]}
                  />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>Recent Eligibility Decisions</CardTitle></CardHeader>
              <CardContent>
                {recentDecisions.length === 0 ? (
                  <EmptyState title="No recent decisions" description="No eligibility decisions recorded yet." />
                ) : (
                  <div className="space-y-2">
                    {recentDecisions.map((dec) => (
                      <div
                        key={String(dec.id ?? dec.decision_id)}
                        className="flex items-center justify-between rounded border border-border-default px-3 py-2 text-xs"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <Badge variant={decisionVariant(String(dec.decision ?? ''))}>
                            {String(dec.decision ?? 'unknown')}
                          </Badge>
                          <span className="font-mono text-text-muted truncate">{String(dec.wallet_address ?? '—')}</span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0 ml-2">
                          <span className="text-text-muted font-mono">{String(dec.campaign_id ?? '—')}</span>
                          <span className="text-text-muted">{String(dec.created_at ?? '').replace('T', ' ').slice(0, 19)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ── Decisions ──────────────────────────────────────────────────────── */}
        <TabsContent value="decisions">
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Decision Outcome Breakdown (24h)</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {(() => {
                  const eligible = summary.eligible_decisions_24h == null ? null : Number(summary.eligible_decisions_24h);
                  const blocked = summary.blocked_fraud_24h == null ? null : Number(summary.blocked_fraud_24h);
                  if (eligible === null || blocked === null) {
                    return <EmptyState title="Decision breakdown unavailable" description="The backend did not return a complete measured breakdown." />;
                  }
                  const total = eligible + blocked;
                  return (
                    <>
                      <BarSegment label="Eligible" count={eligible} total={total} />
                      <BarSegment label="Blocked (fraud)" count={blocked} total={total} />
                    </>
                  );
                })()}
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>Recent Blocked Decisions</CardTitle></CardHeader>
              <CardContent>
                {blockedDecisions.length === 0 ? (
                  <EmptyState title="No blocked decisions" description="No fraud-blocked eligibility decisions in the current window." />
                ) : (
                  <DataTable
                    data={blockedDecisions}
                    keyExtractor={(r) => String(r.id ?? r.decision_id)}
                    columns={[
                      { key: 'campaign_id', header: 'Campaign', render: (r) => <span className="font-mono text-xs">{String(r.campaign_id ?? '—')}</span> },
                      { key: 'wallet_address', header: 'Wallet', render: (r) => <span className="font-mono text-xs">{String(r.wallet_address ?? '—')}</span> },
                      { key: 'fraud_score', header: 'Fraud Score', render: (r) => {
                        if (r.fraud_score == null) return '—';
                        const score = Number(r.fraud_score);
                        return <Badge variant={score > 0.85 ? 'danger' : 'warning'}>{score.toFixed(2)}</Badge>;
                      }},
                      { key: 'reason', header: 'Reason', render: (r) => String(r.reason ?? '—') },
                      { key: 'created_at', header: 'When', render: (r) => String(r.created_at ?? '').replace('T', ' ').slice(0, 19) },
                    ]}
                  />
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ── Actions ────────────────────────────────────────────────────────── */}
        <TabsContent value="actions">
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Action Payload Status Breakdown</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {totalActions === 0 ? (
                  <EmptyState title="No action payloads" description="No action payloads have been generated yet." />
                ) : (
                  Object.entries(actionStatusBreakdown).map(([status, count]) => (
                    <div key={status} className="flex items-center justify-between">
                      <Badge variant={actionStatusVariant(status)}>{status.replace(/_/g, ' ')}</Badge>
                      <BarSegment label="" count={Number(count)} total={totalActions} />
                    </div>
                  ))
                )}
                <p className="text-xs text-text-muted">
                  Action payloads are produced by Aether for tenant rails to execute. Aether does not distribute rewards directly.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>Recent Failed Deliveries</CardTitle></CardHeader>
              <CardContent>
                {failedDeliveries.length === 0 ? (
                  <EmptyState title="No failed deliveries" description="All action payload deliveries completed successfully." />
                ) : (
                  <DataTable
                    data={failedDeliveries}
                    keyExtractor={(r) => String(r.id ?? r.action_id)}
                    columns={[
                      { key: 'rail', header: 'Rail', render: (r) => <span className="font-mono text-xs">{String(r.rail ?? '—')}</span> },
                      { key: 'status', header: 'Status', render: (r) => <Badge variant={actionStatusVariant(String(r.status ?? ''))}>{String(r.status ?? '—')}</Badge> },
                      { key: 'delivery_attempts', header: 'Attempts', render: (r) => r.delivery_attempts == null ? '—' : String(r.delivery_attempts) },
                      { key: 'error', header: 'Error', render: (r) => <span className="text-xs text-red-500">{String(r.error ?? '—')}</span> },
                      { key: 'created_at', header: 'When', render: (r) => String(r.created_at ?? '').replace('T', ' ').slice(0, 19) },
                    ]}
                  />
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ── Rails ──────────────────────────────────────────────────────────── */}
        <TabsContent value="rails">
          <Card>
            <CardHeader>
              <CardTitle>Per-Rail Delivery Statistics</CardTitle>
            </CardHeader>
            <CardContent>
              {railStats.length === 0 ? (
                <EmptyState title="No rail statistics" description="No action payloads have been sent to tenant rails yet." />
              ) : (
                <DataTable
                  data={railStats}
                  keyExtractor={(r) => String(r.rail)}
                  columns={[
                    { key: 'rail', header: 'Rail', render: (r) => <span className="font-mono text-xs font-semibold">{String(r.rail ?? '—')}</span> },
                    { key: 'total', header: 'Total Actions', render: (r) => r.total == null ? '—' : String(r.total) },
                    { key: 'delivered', header: 'Delivered', render: (r) => <span className="text-green-600 font-semibold">{r.delivered == null ? '—' : String(r.delivered)}</span> },
                    { key: 'failed', header: 'Failed', render: (r) => {
                      if (r.failed == null) return '—';
                      const n = Number(r.failed);
                      return n > 0 ? <Badge variant="danger">{n}</Badge> : <span className="text-text-muted">0</span>;
                    }},
                    { key: 'dead_lettered', header: 'Dead-lettered', render: (r) => {
                      if (r.dead_lettered == null) return '—';
                      const n = Number(r.dead_lettered);
                      return n > 0 ? <Badge variant="danger">{n}</Badge> : <span className="text-text-muted">0</span>;
                    }},
                    { key: 'avg_latency_ms', header: 'Avg Latency (ms)', render: (r) => {
                      if (r.avg_latency_ms == null) return '—';
                      const ms = Number(r.avg_latency_ms);
                      const cls = ms > 1000 ? 'text-yellow-500' : 'text-text-primary';
                      return <span className={cls}>{ms}</span>;
                    }},
                  ]}
                />
              )}
              <p className="mt-3 text-xs text-text-muted">
                Rails are tenant-owned delivery channels. Aether produces action payloads; tenant infrastructure executes on these rails.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Fraud Analysis ─────────────────────────────────────────────────── */}
        <TabsContent value="fraud">
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Fraud Block Summary (24h)</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="text-xs text-text-muted font-mono">Total Blocked</div>
                    <div className="mt-1 text-2xl font-semibold text-red-500">{fraudSummary.total_blocked_24h == null ? 'Unavailable' : String(fraudSummary.total_blocked_24h)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-text-muted font-mono">Avg Fraud Score</div>
                    <div className="mt-1 text-2xl font-semibold text-text-primary">{fraudSummary.avg_fraud_score_blocked == null ? 'Unavailable' : Number(fraudSummary.avg_fraud_score_blocked).toFixed(2)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-text-muted font-mono">Est. False Positive Rate</div>
                    <div className="mt-1 text-lg font-semibold text-text-primary">{String(fraudSummary.false_positive_rate_est ?? '—')}</div>
                  </div>
                </div>
                <p className="text-xs text-text-muted">
                  Fraud signals feed into eligibility decisions. Blocked decisions produce no action payloads for tenant rails.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>Top Block Reasons</CardTitle></CardHeader>
              <CardContent>
                {topFraudReasons.length === 0 ? (
                  <EmptyState title="No fraud signals" description="No fraud-blocked decisions in the current window." />
                ) : (
                  <div className="space-y-3">
                    {topFraudReasons.map((item) => {
                      const total = Number(fraudSummary.total_blocked_24h ?? 1);
                      return (
                        <BarSegment
                          key={String(item.reason)}
                          label={String(item.reason ?? '').replace(/_/g, ' ')}
                          count={Number(item.count ?? 0)}
                          total={total}
                        />
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
