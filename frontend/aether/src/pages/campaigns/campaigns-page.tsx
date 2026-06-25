import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader,
  DataTable, EmptyState, ErrorState, LoadingState, Skeleton, Tabs,
  TabsContent, TabsList, TabsTrigger,
} from '@aether/ui';
import { useCampaigns, usePlatformOverview, useAutomationInsights } from '@aether-app/features/campaigns/use-campaigns';

// ── helpers ────────────────────────────────────────────────────────────────────

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function fmtPct(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function fmtUsd(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function relTime(iso: string | undefined | null): string {
  if (!iso) return '—';
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (d === 0) return 'Today';
  if (d === 1) return 'Yesterday';
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
}

function statusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'active') return 'success';
  if (status === 'paused') return 'warning';
  if (status === 'ended' || status === 'archived') return 'danger';
  return 'default';
}

// ── Stat tile ─────────────────────────────────────────────────────────────────

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className="text-xl font-semibold text-text-primary mt-0.5">{value}</p>
      {sub && <p className="text-xs text-text-muted mt-0.5">{sub}</p>}
    </div>
  );
}

// ── Funnel bar ────────────────────────────────────────────────────────────────

function FunnelBar({ label, value, max, variant = 'default' }: {
  label: string;
  value: number;
  max: number;
  variant?: 'success' | 'warning' | 'danger' | 'default';
}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  const barColor = variant === 'success' ? 'bg-success' : variant === 'warning' ? 'bg-warning' : variant === 'danger' ? 'bg-danger' : 'bg-accent';
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-text-secondary">{label}</span>
        <span className="text-text-primary font-medium">{value.toLocaleString()} <span className="text-text-muted">({pct}%)</span></span>
      </div>
      <div className="h-1.5 bg-surface-overlay rounded-full">
        <div className={`h-1.5 rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── Campaign detail panel ─────────────────────────────────────────────────────

function CampaignRow({ campaign }: { campaign: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const metrics = asRecord(campaign.metrics);
  const funnel = asRecord(campaign.funnel ?? metrics.funnel);
  const channels = asList(campaign.top_channels ?? metrics.top_channels);
  const name = fmt(campaign.name ?? campaign.campaign_id ?? campaign.id);
  const status = fmt(campaign.status);
  const convRate = metrics.conversion_rate ?? campaign.conversion_rate;
  const fraudBlocked = metrics.fraud_blocked ?? campaign.fraud_blocked;

  const entered = Number(funnel.entered ?? campaign.impressions ?? 0);
  const clicked = Number(funnel.clicked ?? campaign.clicks ?? 0);
  const converted = Number(funnel.converted ?? campaign.conversions ?? 0);
  const dropped = Number(funnel.dropped ?? 0);
  const abandoned = Number(funnel.abandoned ?? 0);
  const dropOffRate = funnel.drop_off_rate ?? campaign.drop_off_rate;
  const abandonmentRate = funnel.abandonment_rate ?? campaign.abandonment_rate;

  return (
    <div className="border border-border-default rounded-lg overflow-hidden">
      {/* Header row */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-surface-raised transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-text-primary text-sm">{name}</span>
            <Badge variant={statusVariant(status)} size="sm">{status}</Badge>
            {!!campaign.type && <Badge variant="default" size="sm">{fmt(campaign.type)}</Badge>}
          </div>
          <div className="flex items-center gap-4 mt-1 text-xs text-text-muted">
            <span>Started {relTime(campaign.start_date as string ?? campaign.created_at as string)}</span>
            {!!campaign.end_date && <span>Ends {relTime(campaign.end_date as string)}</span>}
            <code className="font-mono">{fmt(campaign.id ?? campaign.campaign_id)}</code>
          </div>
        </div>
        {/* Quick stats */}
        <div className="flex items-center gap-6 text-right shrink-0">
          {convRate !== undefined && (
            <div>
              <p className="text-xs text-text-secondary">Conv. rate</p>
              <p className="text-sm font-semibold text-success">{fmtPct(convRate)}</p>
            </div>
          )}
          {converted > 0 && (
            <div>
              <p className="text-xs text-text-secondary">Conversions</p>
              <p className="text-sm font-semibold text-text-primary">{converted.toLocaleString()}</p>
            </div>
          )}
          {fraudBlocked !== undefined && Number(fraudBlocked) > 0 && (
            <div>
              <p className="text-xs text-text-secondary">Fraud blocked</p>
              <p className="text-sm font-semibold text-danger">{Number(fraudBlocked).toLocaleString()}</p>
            </div>
          )}
          <button
            onClick={e => { e.stopPropagation(); navigate(`/campaigns/${String(campaign.id ?? campaign.campaign_id)}`); }}
            className="text-xs text-accent hover:underline whitespace-nowrap"
          >
            360 →
          </button>
          <span className="text-text-muted text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {/* Expanded detail */}
      {open && (
        <div className="border-t border-border-default px-4 py-4 space-y-5 bg-surface-raised">
          {/* Funnel */}
          {entered > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-medium text-text-secondary uppercase tracking-wide">Funnel</h4>
              <FunnelBar label="Entered" value={entered} max={entered} variant="default" />
              {clicked > 0 && <FunnelBar label="Clicked" value={clicked} max={entered} variant="default" />}
              <FunnelBar label="Converted" value={converted} max={entered} variant="success" />
              {dropped > 0 && <FunnelBar label="Dropped off" value={dropped} max={entered} variant="warning" />}
              {abandoned > 0 && <FunnelBar label="Abandoned" value={abandoned} max={entered} variant="danger" />}
              {(dropOffRate !== undefined || abandonmentRate !== undefined) && (
                <div className="flex gap-4 pt-1 text-xs text-text-muted">
                  {dropOffRate !== undefined && <span>Drop-off rate: <span className="text-warning font-medium">{fmtPct(dropOffRate)}</span></span>}
                  {abandonmentRate !== undefined && <span>Abandonment: <span className="text-danger font-medium">{fmtPct(abandonmentRate)}</span></span>}
                </div>
              )}
            </div>
          )}

          {/* Top channels */}
          {channels.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-2">Top channels</h4>
              <div className="space-y-1.5">
                {channels.slice(0, 6).map((ch, i) => {
                  const c = typeof ch === 'object' && ch ? (ch as Record<string, unknown>) : { channel: String(ch), conversions: 0 };
                  return (
                    <div key={i} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <Badge variant="default" size="sm">{fmt(c.channel ?? c.name)}</Badge>
                        {!!c.source && <span className="text-text-muted">{fmt(c.source)}</span>}
                      </div>
                      <div className="flex items-center gap-4 text-right">
                        {c.conversions !== undefined && <span className="text-text-primary">{Number(c.conversions).toLocaleString()} conv.</span>}
                        {c.revenue_usd !== undefined && <span className="text-success">{fmtUsd(c.revenue_usd)}</span>}
                        {c.conversion_rate !== undefined && <span className="text-text-secondary">{fmtPct(c.conversion_rate)}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Revenue */}
          {(campaign.revenue_usd ?? metrics.revenue_usd) !== undefined && (
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Revenue" value={fmtUsd(campaign.revenue_usd ?? metrics.revenue_usd)} />
              {(campaign.cost_usd ?? metrics.cost_usd) !== undefined && (
                <Stat label="Cost" value={fmtUsd(campaign.cost_usd ?? metrics.cost_usd)} />
              )}
              {(campaign.roas ?? metrics.roas) !== undefined && (
                <Stat label="ROAS" value={`${Number(campaign.roas ?? metrics.roas).toFixed(2)}x`} />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function OverviewTab({ hours }: { hours: number }) {
  const { data, isLoading, error } = usePlatformOverview(hours);
  const { data: insightsData } = useAutomationInsights();
  const ov = asRecord(data);
  const web2 = asRecord(ov.web2);
  const web3 = asRecord(ov.web3);
  const insights = asList(insightsData ?? ov.insights);

  if (error) return <ErrorState title="Failed to load overview" message={String(error)} />;
  if (isLoading) return <LoadingState lines={6} />;

  return (
    <div className="space-y-6">
      {/* Top-level metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat
          label="Total sessions"
          value={ov.total_sessions !== undefined ? Number(ov.total_sessions).toLocaleString() : (isLoading ? <Skeleton className="h-5 w-16" /> : '—')}
          sub={`Last ${hours}h`}
        />
        <Stat
          label="Conversion rate"
          value={ov.conversion_rate !== undefined ? fmtPct(ov.conversion_rate) : '—'}
        />
        <Stat
          label="Fraud blocked"
          value={ov.fraud_blocked !== undefined ? Number(ov.fraud_blocked).toLocaleString() : '—'}
        />
        <Stat
          label="Active campaigns"
          value={ov.active_campaigns !== undefined ? Number(ov.active_campaigns).toLocaleString() : '—'}
        />
      </div>

      {/* Web2 vs Web3 split */}
      {(web2.sessions !== undefined || web3.sessions !== undefined) && (
        <div>
          <h3 className="text-sm font-medium text-text-secondary mb-3">Web2 vs Web3 breakdown</h3>
          <div className="grid grid-cols-2 gap-4">
            <Card>
              <CardHeader><span className="text-sm font-medium text-text-primary">Web2</span></CardHeader>
              <CardContent className="grid grid-cols-2 gap-3">
                <Stat label="Sessions" value={web2.sessions !== undefined ? Number(web2.sessions).toLocaleString() : '—'} />
                <Stat label="Conv. rate" value={fmtPct(web2.conversion_rate)} />
                <Stat label="Revenue" value={fmtUsd(web2.revenue_usd)} />
                <Stat label="Avg. LTV" value={fmtUsd(web2.avg_ltv_usd)} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader><span className="text-sm font-medium text-text-primary">Web3</span></CardHeader>
              <CardContent className="grid grid-cols-2 gap-3">
                <Stat label="Wallet sessions" value={web3.sessions !== undefined ? Number(web3.sessions).toLocaleString() : '—'} />
                <Stat label="Conv. rate" value={fmtPct(web3.conversion_rate)} />
                <Stat label="On-chain vol." value={fmtUsd(web3.volume_usd)} />
                <Stat label="Wallets active" value={web3.active_wallets !== undefined ? Number(web3.active_wallets).toLocaleString() : '—'} />
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* Insights */}
      {insights.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-text-secondary mb-3">Automation insights</h3>
          <div className="space-y-2">
            {insights.map((insight, i) => {
              const ins = asRecord(insight);
              return (
                <div key={i} className="border border-border-default rounded-md p-3 flex items-start gap-3">
                  {!!ins.severity && (
                    <Badge
                      variant={ins.severity === 'high' ? 'danger' : ins.severity === 'medium' ? 'warning' : 'default'}
                      size="sm"
                    >
                      {fmt(ins.severity)}
                    </Badge>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text-primary">{fmt(ins.message ?? ins.description ?? insight)}</p>
                    {!!ins.recommendation && (
                      <p className="text-xs text-text-muted mt-0.5">{fmt(ins.recommendation)}</p>
                    )}
                  </div>
                  {!!ins.metric && (
                    <span className="text-xs text-text-secondary shrink-0">{fmt(ins.metric)}: {fmt(ins.value)}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Campaigns list tab ────────────────────────────────────────────────────────

function CampaignListTab({ status }: { status?: string }) {
  const { data, isLoading, error } = useCampaigns(status ? { status, limit: 50 } : { limit: 50 });
  const d = asRecord(data);
  const campaigns = asList(d.campaigns ?? data);

  if (error) {
    return (
      <ErrorState
        title="Failed to load campaigns"
        message={String(error)}
      />
    );
  }

  if (isLoading) return <LoadingState lines={8} />;

  if (campaigns.length === 0) {
    return (
      <EmptyState
        title="No campaigns"
        description={status ? `No ${status} campaigns found.` : 'No campaigns have been created yet.'}
      />
    );
  }

  return (
    <div className="space-y-3">
      {campaigns.map((campaign, i) => (
        <CampaignRow key={String(asRecord(campaign).id ?? asRecord(campaign).campaign_id ?? i)} campaign={asRecord(campaign)} />
      ))}
    </div>
  );
}

// ── Attribution overview ──────────────────────────────────────────────────────

function AttributionOverviewTab() {
  const { data: allData } = useCampaigns({ limit: 50 });
  const d = asRecord(allData);
  const campaigns = asList(d.campaigns ?? allData);

  type Row = Record<string, unknown>;

  const rows: Row[] = campaigns.flatMap(c => {
    const cr = asRecord(c);
    const channels = asList(cr.top_channels ?? asRecord(cr.metrics).top_channels);
    return channels.map(ch => {
      const channelRow = asRecord(ch);
      return {
        campaign_name: cr.name ?? cr.campaign_id ?? cr.id,
        channel: channelRow.channel ?? channelRow.name ?? ch,
        source: channelRow.source,
        conversions: channelRow.conversions,
        revenue_usd: channelRow.revenue_usd,
        conversion_rate: channelRow.conversion_rate,
        weight: channelRow.weight,
      } as Row;
    });
  });

  if (rows.length === 0) {
    return <EmptyState title="No attribution data" description="Attribution data will appear once campaigns have recorded touchpoints." />;
  }

  return (
    <DataTable<Row>
      keyExtractor={r => `${String(r.campaign_name)}-${String(r.channel)}-${String(r.source ?? '')}`}
      data={rows}
      columns={[
        { key: 'campaign', header: 'Campaign', render: r => <span className="text-text-primary">{fmt(r.campaign_name)}</span> },
        { key: 'channel', header: 'Channel', render: r => <Badge variant="default" size="sm">{fmt(r.channel)}</Badge> },
        { key: 'source', header: 'Source', render: r => r.source ? <span className="text-text-secondary">{fmt(r.source)}</span> : <span className="text-text-muted">—</span> },
        { key: 'conversions', header: 'Conversions', render: r => fmt(r.conversions) },
        { key: 'revenue', header: 'Revenue', render: r => r.revenue_usd !== undefined ? <span className="text-success">{fmtUsd(r.revenue_usd)}</span> : <span className="text-text-muted">—</span> },
        { key: 'conv_rate', header: 'Conv. rate', render: r => r.conversion_rate !== undefined ? fmtPct(r.conversion_rate) : <span className="text-text-muted">—</span> },
        { key: 'weight', header: 'Attribution weight', render: r => r.weight !== undefined ? fmtPct(r.weight) : <span className="text-text-muted">—</span> },
      ]}
    />
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function CampaignsPage() {
  const navigate = useNavigate();
  const [hours, setHours] = useState(24);

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Campaigns</h1>
          <p className="text-sm text-text-secondary mt-0.5">
            Conversion funnels, drop-off rates, attribution channels
          </p>
        </div>
        <div className="flex items-center gap-2">
          {([6, 24, 72] as const).map(h => (
            <Button
              key={h}
              variant={hours === h ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setHours(h)}
            >
              {h}h
            </Button>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="active">Active</TabsTrigger>
          <TabsTrigger value="all">All campaigns</TabsTrigger>
          <TabsTrigger value="attribution">Attribution</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab hours={hours} />
        </TabsContent>

        <TabsContent value="active">
          <CampaignListTab status="active" />
        </TabsContent>

        <TabsContent value="all">
          <CampaignListTab />
        </TabsContent>

        <TabsContent value="attribution">
          <AttributionOverviewTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
