import { useParams, useNavigate } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  DataTable, EmptyState, ErrorState, LoadingState, ScrollArea,
  Tabs, TabsList, TabsTrigger, TabsContent,
  formatDecimal, useTimeContext, type TimeContext,
} from '@aether/ui';
import { useCluster360 } from '@aether-app/features/cluster360/use-cluster360';
import type {
  ClusterMember, ClusterTimelineEvent, ClusterEconomicSummary,
  ClusterCampaignSummary, ClusterRiskSummary, ClusterGeographySummary,
} from '@aether-app/features/cluster360/use-cluster360';
import { ClusterTargetingImpactTab } from '@aether-app/features/targeting-intelligence';

// ── Helpers ───────────────────────────────────────────────────────────────────

function riskVariant(tier: string): 'danger' | 'warning' | 'success' {
  if (tier === 'high') return 'danger';
  if (tier === 'medium') return 'warning';
  return 'success';
}

function lifecycleBadge(state: string): 'success' | 'warning' | 'danger' | 'default' {
  if (state === 'active') return 'success';
  if (state === 'dormant' || state === 'decaying' || state === 'shrinking') return 'warning';
  if (state === 'revoked' || state === 'expired' || state === 'invalidated') return 'danger';
  return 'default';
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const d = Math.floor(diff / 86_400_000);
  if (d === 0) return 'Today';
  if (d === 1) return 'Yesterday';
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
}

function fmt(n: number, ctx: TimeContext, decimals = 2): string {
  return formatDecimal(n, ctx, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// ── Overview Tab ──────────────────────────────────────────────────────────────

function OverviewTab({ cluster }: { cluster: NonNullable<ReturnType<typeof useCluster360>['cluster']> }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {[
          ['Type', cluster.cluster_type],
          ['State', <Badge key="state" variant={lifecycleBadge(cluster.lifecycle_state)}>{cluster.lifecycle_state}</Badge>],
          ['Members', cluster.member_count],
          ['Confidence', `${(cluster.confidence * 100).toFixed(1)}%`],
          ['Created', relativeTime(cluster.created_at)],
          ['Updated', relativeTime(cluster.updated_at)],
        ].map(([label, val]) => (
          <div key={String(label)} className="space-y-0.5">
            <p className="text-xs text-text-muted">{label}</p>
            <p className="text-sm text-text-primary font-medium">{val}</p>
          </div>
        ))}
      </div>
      {cluster.formation_reason && (
        <div>
          <p className="text-xs text-text-muted mb-1">Formation reason</p>
          <p className="text-sm text-text-secondary">{cluster.formation_reason}</p>
        </div>
      )}
      {cluster.risk_score != null && (
        <div>
          <p className="text-xs text-text-muted mb-1">Risk score</p>
          <div className="flex items-center gap-2">
            <div className="h-1.5 flex-1 bg-surface-overlay rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${cluster.risk_score * 100}%`,
                  backgroundColor: cluster.risk_score >= 0.7 ? '#ef4444' : cluster.risk_score >= 0.4 ? '#eab308' : '#22c55e',
                }}
              />
            </div>
            <span className="text-xs font-mono text-text-primary">{(cluster.risk_score * 100).toFixed(1)}</span>
          </div>
        </div>
      )}
      {Object.keys(cluster.properties).length > 0 && (
        <div>
          <p className="text-xs font-medium text-text-secondary mb-2">Properties</p>
          <div className="space-y-1">
            {Object.entries(cluster.properties).slice(0, 10).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs">
                <span className="text-text-muted">{k}</span>
                <span className="text-text-primary font-mono truncate max-w-[160px]">{String(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Members Tab ───────────────────────────────────────────────────────────────

const MEMBER_COLUMNS = [
  { key: 'label', header: 'Label', render: (m: ClusterMember) => <span className="font-mono text-xs text-text-primary truncate">{m.label}</span> },
  { key: 'entity_type', header: 'Type', render: (m: ClusterMember) => <Badge size="sm">{m.entity_type}</Badge> },
  { key: 'confidence', header: 'Confidence', render: (m: ClusterMember) => <span className="font-mono text-xs">{(m.membership_confidence * 100).toFixed(0)}%</span> },
  { key: 'joined_at', header: 'Joined', render: (m: ClusterMember) => <span className="text-xs text-text-muted">{relativeTime(m.joined_at)}</span> },
  { key: 'entity_id', header: 'ID', render: (m: ClusterMember) => <code className="text-[10px] text-text-muted truncate max-w-[100px] block">{m.entity_id}</code> },
];

function MembersTab({ members }: { members: ClusterMember[] }) {
  if (members.length === 0) {
    return <EmptyState title="No members" description="No entity members found for this cluster." />;
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-text-secondary">{members.length} member{members.length !== 1 ? 's' : ''}</p>
      <DataTable<ClusterMember> columns={MEMBER_COLUMNS} data={members} keyExtractor={m => m.entity_id} />
    </div>
  );
}

// ── Timeline Tab ──────────────────────────────────────────────────────────────

const EVENT_TYPE_BADGE: Record<string, 'success' | 'info' | 'warning' | 'danger' | 'default'> = {
  created: 'info',
  merged: 'warning',
  split: 'warning',
  member_added: 'success',
  member_removed: 'danger',
  risk_change: 'danger',
  growth: 'success',
};

function TimelineTab({ events }: { events: ClusterTimelineEvent[] }) {
  if (events.length === 0) return <EmptyState title="No events" description="No timeline events recorded." />;
  return (
    <div className="space-y-3">
      {events.map(ev => (
        <div key={ev.event_id} className="flex items-start gap-3 pb-3 border-b border-border-subtle last:border-0">
          <div className="flex-shrink-0 mt-0.5">
            <Badge variant={EVENT_TYPE_BADGE[ev.event_type] ?? 'default'} size="sm">{ev.event_type}</Badge>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-text-primary">{ev.description}</p>
            <p className="text-xs text-text-muted mt-0.5">{relativeTime(ev.timestamp)}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Economic Tab ──────────────────────────────────────────────────────────────

function EconomicTab({ economic }: { economic: ClusterEconomicSummary | null }) {
  const timeCtx = useTimeContext();
  if (!economic) return <EmptyState title="No economic data" description="Economic data not available." />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {[
          ['Total Revenue', `${economic.currency} ${fmt(economic.total_revenue, timeCtx)}`],
          ['Total Spend', `${economic.currency} ${fmt(economic.total_spend, timeCtx)}`],
          ['LTV Estimate', `${economic.currency} ${fmt(economic.ltv_estimate, timeCtx)}`],
          ['Transactions', economic.transaction_count],
          ['Value Tier', <Badge key="tier" variant={economic.value_tier === 'high' ? 'success' : economic.value_tier === 'medium' ? 'warning' : 'default'}>{economic.value_tier}</Badge>],
        ].map(([label, val]) => (
          <div key={String(label)} className="space-y-0.5">
            <p className="text-xs text-text-muted">{label}</p>
            <p className="text-sm text-text-primary font-medium">{val}</p>
          </div>
        ))}
      </div>
      {economic.member_economic_summaries.length > 0 && (
        <div>
          <p className="text-xs font-medium text-text-secondary mb-2">Top members by revenue</p>
          <div className="space-y-1">
            {economic.member_economic_summaries
              .sort((a, b) => b.revenue - a.revenue)
              .slice(0, 5)
              .map(m => (
                <div key={m.entity_id} className="flex justify-between text-xs">
                  <code className="text-text-muted truncate max-w-[140px]">{m.entity_id}</code>
                  <span className="text-text-primary font-mono">{economic.currency} {fmt(m.revenue, timeCtx)}</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Campaign Tab ──────────────────────────────────────────────────────────────

function CampaignTab({ campaigns }: { campaigns: ClusterCampaignSummary | null }) {
  const timeCtx = useTimeContext();
  if (!campaigns || campaigns.attributed_campaigns.length === 0) {
    return <EmptyState title="No campaigns" description="No campaign attribution data found." />;
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {[
          ['Attributed Revenue', `$${fmt(campaigns.total_attributed_revenue, timeCtx)}`],
          ['Top Channel', campaigns.top_acquisition_channel ?? '—'],
          ['Conversion Rate', campaigns.conversion_rate !== null ? `${((campaigns.conversion_rate ?? 0) * 100).toFixed(1)}%` : '—'],
          ['Campaigns', campaigns.attributed_campaigns.length],
        ].map(([label, val]) => (
          <div key={String(label)} className="space-y-0.5">
            <p className="text-xs text-text-muted">{label}</p>
            <p className="text-sm text-text-primary font-medium">{val}</p>
          </div>
        ))}
      </div>
      <div>
        <p className="text-xs font-medium text-text-secondary mb-2">Campaign attribution</p>
        <div className="space-y-1">
          {campaigns.attributed_campaigns.slice(0, 10).map(c => (
            <div key={c.campaign_id} className="flex justify-between text-xs">
              <code className="text-text-muted truncate max-w-[160px]">{c.campaign_id}</code>
              <span className="text-text-primary font-mono">${fmt(c.attributed_revenue, timeCtx)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Risk Tab ──────────────────────────────────────────────────────────────────

function RiskTab({ risk }: { risk: ClusterRiskSummary | null }) {
  if (!risk) return <EmptyState title="No risk data" description="Risk data not available." />;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div>
          <p className="text-xs text-text-muted mb-0.5">Aggregate risk</p>
          <div className="flex items-center gap-2">
            <div className="h-2 w-24 bg-surface-overlay rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${risk.aggregate_risk_score * 100}%`,
                  backgroundColor: risk.aggregate_risk_score >= 0.7 ? '#ef4444' : risk.aggregate_risk_score >= 0.4 ? '#eab308' : '#22c55e',
                }}
              />
            </div>
            <span className="font-mono text-sm">{(risk.aggregate_risk_score * 100).toFixed(1)}</span>
          </div>
        </div>
        <Badge variant={riskVariant(risk.risk_tier)}>{risk.risk_tier} risk</Badge>
      </div>
      {risk.fraud_network_id && (
        <div className="p-3 rounded-md border border-border-default bg-surface-raised space-y-1">
          <p className="text-xs font-medium text-text-secondary">Fraud network</p>
          <code className="text-xs text-text-primary">{risk.fraud_network_id}</code>
          {risk.fraud_network_type && <Badge variant="danger" size="sm">{risk.fraud_network_type}</Badge>}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-0.5">
          <p className="text-xs text-text-muted">Alerts</p>
          <p className="text-sm font-medium text-text-primary">{risk.alert_count}</p>
        </div>
        <div className="space-y-0.5">
          <p className="text-xs text-text-muted">High-risk members</p>
          <p className="text-sm font-medium text-text-primary">{risk.high_risk_members.length}</p>
        </div>
      </div>
      {risk.evidence_refs.length > 0 && (
        <div>
          <p className="text-xs font-medium text-text-secondary mb-1">Evidence</p>
          <div className="space-y-1">
            {risk.evidence_refs.slice(0, 5).map(ref => (
              <code key={ref} className="text-xs text-text-muted block">{ref}</code>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Geography Tab ─────────────────────────────────────────────────────────────

function GeographyTab({ geography }: { geography: ClusterGeographySummary | null }) {
  if (!geography || Object.keys(geography.country_distribution).length === 0) {
    return <EmptyState title="No geography data" description="No geographic data available for cluster members." />;
  }
  const countries = Object.entries(geography.country_distribution).sort(([, a], [, b]) => b - a);
  const total = countries.reduce((s, [, c]) => s + c, 0);
  return (
    <div className="space-y-4">
      {geography.primary_country && (
        <div className="flex items-center gap-2">
          <p className="text-xs text-text-muted">Primary country</p>
          <Badge>{geography.primary_country}</Badge>
          <span className="text-xs text-text-secondary">
            ({(geography.geo_concentration_score * 100).toFixed(0)}% concentration)
          </span>
        </div>
      )}
      <div>
        <p className="text-xs font-medium text-text-secondary mb-2">Country distribution</p>
        <div className="space-y-2">
          {countries.slice(0, 10).map(([country, count]) => (
            <div key={country}>
              <div className="flex justify-between text-xs mb-0.5">
                <span className="text-text-primary">{country}</span>
                <span className="text-text-muted font-mono">{count} ({total > 0 ? ((count / total) * 100).toFixed(1) : 0}%)</span>
              </div>
              <div className="h-1.5 w-full bg-surface-overlay rounded-full overflow-hidden">
                <div
                  className="h-full bg-accent rounded-full"
                  style={{ width: total > 0 ? `${(count / total) * 100}%` : '0%' }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Cluster360Page() {
  const { clusterId } = useParams<{ clusterId: string }>();
  const navigate = useNavigate();
  const {
    cluster, members, timeline, economic, campaigns, risk, geography,
    isLoading, error,
  } = useCluster360(clusterId ?? null);

  if (isLoading) {
    return (
      <div className="p-8">
        <LoadingState lines={8} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <ErrorState title="Failed to load cluster" message={error} />
      </div>
    );
  }

  if (!cluster) {
    return (
      <div className="p-8">
        <EmptyState
          title="Cluster not found"
          description={`No cluster with ID "${clusterId}" exists in this tenant.`}
          action={<Button onClick={() => navigate('/graph')}>Back to Graph</Button>}
        />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>← Back</Button>
            <Badge variant="accent">{cluster.cluster_type}</Badge>
            <Badge variant={lifecycleBadge(cluster.lifecycle_state)}>{cluster.lifecycle_state}</Badge>
          </div>
          <h1 className="text-xl font-semibold text-text-primary truncate">{cluster.label}</h1>
          <code className="text-xs text-text-muted">{cluster.cluster_id}</code>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <Badge variant="accent">{cluster.member_count} members</Badge>
          <Button variant="ghost" size="sm" onClick={() => navigate(`/graph?cluster=${cluster.cluster_id}`)}>
            View in Graph
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <Card>
        <CardContent className="pt-4">
          <Tabs defaultValue="overview">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="members">Members ({cluster.member_count})</TabsTrigger>
              <TabsTrigger value="timeline">Timeline</TabsTrigger>
              <TabsTrigger value="economic">Economic</TabsTrigger>
              <TabsTrigger value="campaigns">Campaigns</TabsTrigger>
              <TabsTrigger value="targeting-impact">Targeting Impact</TabsTrigger>
              <TabsTrigger value="risk">Risk</TabsTrigger>
              <TabsTrigger value="geography">Geography</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="mt-4">
              <OverviewTab cluster={cluster} />
            </TabsContent>

            <TabsContent value="members" className="mt-4">
              <MembersTab members={members} />
            </TabsContent>

            <TabsContent value="timeline" className="mt-4">
              <ScrollArea maxHeight="400px">
                <TimelineTab events={timeline} />
              </ScrollArea>
            </TabsContent>

            <TabsContent value="economic" className="mt-4">
              <EconomicTab economic={economic} />
            </TabsContent>

            <TabsContent value="campaigns" className="mt-4">
              <CampaignTab campaigns={campaigns} />
            </TabsContent>

            <TabsContent value="targeting-impact" className="mt-4">
              <ClusterTargetingImpactTab clusterId={cluster.cluster_id} />
            </TabsContent>

            <TabsContent value="risk" className="mt-4">
              <RiskTab risk={risk} />
            </TabsContent>

            <TabsContent value="geography" className="mt-4">
              <GeographyTab geography={geography} />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
