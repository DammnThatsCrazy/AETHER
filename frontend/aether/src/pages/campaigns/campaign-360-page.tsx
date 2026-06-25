import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState, Tabs, TabsContent, TabsList, TabsTrigger } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import {
  useCampaign360Overview,
  useCampaign360Population,
  useCampaign360Clusters,
  useCampaign360Conversions,
  useCampaign360Attribution,
} from '@aether-app/features/campaigns/use-campaign-360';

type AnyRecord = Record<string, unknown>;

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className="text-xl font-semibold text-text-primary mt-0.5">{value}</p>
    </div>
  );
}

function fmtUSD(n: number) {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function OverviewTab({ campaignId, timeStart, timeEnd, attributionModel }: { campaignId: string; timeStart?: string; timeEnd?: string; attributionModel: string }) {
  const { data, loading, error } = useCampaign360Overview(campaignId, {
    ...(timeStart !== undefined ? { time_start: timeStart } : {}),
    ...(timeEnd !== undefined ? { time_end: timeEnd } : {}),
    attribution_model: attributionModel,
  });

  if (loading) return <LoadingState lines={6} />;
  if (error) return <ErrorState title="Overview unavailable" message={error} />;
  if (!data) return null;

  const d = data as AnyRecord;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Metric label="Spend" value={fmtUSD(Number(d.spend_usd ?? 0))} />
        <Metric label="Impressions" value={Number(d.impressions ?? 0).toLocaleString()} />
        <Metric label="Clicks" value={Number(d.clicks ?? 0).toLocaleString()} />
        <Metric label="ROAS" value={d.roas != null ? `${Number(d.roas).toFixed(2)}x` : '—'} />
        <Metric label="Gross revenue" value={fmtUSD(Number(d.gross_attributed_revenue ?? 0))} />
        <Metric label="Net revenue" value={fmtUSD(Number(d.net_attributed_revenue ?? 0))} />
      </div>

      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-2">Population funnel</h3>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {[
            { label: 'Observed', key: 'observed_count' },
            { label: 'Resolved', key: 'resolved_count' },
            { label: 'Engaged', key: 'engaged_count' },
            { label: 'Converted', key: 'converted_count' },
            { label: 'Attributed', key: 'attributed_count' },
          ].map(({ label, key }) => (
            <Metric key={key} label={label} value={Number(d[key] ?? 0).toLocaleString()} />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Metric label="Attribution model" value={String(d.attribution_model ?? 'last_touch')} />
        <Metric label="Resolution rate" value={fmtPct(d.identity_resolution_rate as number | null)} />
        <Metric label="Touchpoints" value={Number(d.touchpoint_count ?? 0).toLocaleString()} />
      </div>
    </div>
  );
}

// ── Population tab ────────────────────────────────────────────────────────────

function PopulationTab({ campaignId, timeStart, timeEnd }: { campaignId: string; timeStart?: string; timeEnd?: string }) {
  const [population, setPopulation] = useState('observed');
  const { data, loading, error } = useCampaign360Population(campaignId, {
    population,
    ...(timeStart !== undefined ? { time_start: timeStart } : {}),
    ...(timeEnd !== undefined ? { time_end: timeEnd } : {}),
    limit: 50,
  });
  const items = (data as AnyRecord)?.items as AnyRecord[] | undefined;

  return (
    <div className="space-y-4">
      <div className="flex gap-1 border border-border-default rounded-md p-0.5 w-fit">
        {['observed', 'resolved', 'engaged', 'converted', 'attributed'].map(p => (
          <button key={p} onClick={() => setPopulation(p)} className={`px-3 py-1 text-xs rounded capitalize transition-colors ${population === p ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'}`}>{p}</button>
        ))}
      </div>
      {loading && <LoadingState lines={4} />}
      {error && <ErrorState title="Population unavailable" message={error} />}
      {!loading && !error && (
        <Card>
          <CardHeader><CardTitle className="text-sm capitalize">{population} entities</CardTitle></CardHeader>
          <CardContent>
            {!items?.length
              ? <EmptyState title="No entities" description={`No ${population} entities found.`} />
              : (
                <DataTable
                  data={items}
                  keyExtractor={r => String(r.entity_id)}
                  columns={[
                    { key: 'entity_id', header: 'Entity', render: r => <span className="font-mono text-xs">{String(r.entity_id ?? '').slice(0, 16)}…</span> },
                    { key: 'entity_type', header: 'Type', render: r => String(r.entity_type ?? '—') },
                    { key: 'touchpoint_count', header: 'Touchpoints', render: r => Number(r.touchpoint_count ?? 0).toLocaleString() },
                    { key: 'conversion_count', header: 'Conversions', render: r => Number(r.conversion_count ?? 0).toLocaleString() },
                    { key: 'attributed_revenue', header: 'Attributed $', render: r => fmtUSD(Number(r.attributed_revenue ?? 0)) },
                    { key: 'last_activity_at', header: 'Last active', render: r => r.last_activity_at ? new Date(String(r.last_activity_at)).toLocaleDateString() : '—' },
                  ]}
                />
              )
            }
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Clusters tab ──────────────────────────────────────────────────────────────

function ClustersTab({ campaignId }: { campaignId: string }) {
  const { data, loading, error } = useCampaign360Clusters(campaignId, { limit: 50 });
  const items = (data as AnyRecord)?.items as AnyRecord[] | undefined;

  if (loading) return <LoadingState lines={4} />;
  if (error) return <ErrorState title="Clusters unavailable" message={error} />;

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Identity clusters</CardTitle></CardHeader>
      <CardContent>
        {!items?.length
          ? <EmptyState title="No clusters" description="No identity clusters found for this campaign." />
          : (
            <DataTable
              data={items}
              keyExtractor={r => String(r.cluster_id ?? Math.random())}
              columns={[
                { key: 'cluster_id', header: 'Cluster', render: r => r.cluster_id ? <span className="font-mono text-xs">{String(r.cluster_id).slice(0, 16)}…</span> : <span className="text-text-muted text-xs">unresolved</span> },
                { key: 'conversion_count', header: 'Conversions', render: r => Number(r.conversion_count ?? 0).toLocaleString() },
                { key: 'attributed_gross_revenue', header: 'Gross $', render: r => fmtUSD(Number(r.attributed_gross_revenue ?? 0)) },
                { key: 'attributed_net_revenue', header: 'Net $', render: r => fmtUSD(Number(r.attributed_net_revenue ?? 0)) },
              ]}
            />
          )
        }
      </CardContent>
    </Card>
  );
}

// ── Conversions tab ───────────────────────────────────────────────────────────

function ConversionsTab({ campaignId, timeStart, timeEnd }: { campaignId: string; timeStart?: string; timeEnd?: string }) {
  const { data, loading, error } = useCampaign360Conversions(campaignId, {
    ...(timeStart !== undefined ? { after: timeStart } : {}),
    ...(timeEnd !== undefined ? { before: timeEnd } : {}),
    limit: 50,
  });
  const items = (data as AnyRecord)?.items as AnyRecord[] | undefined;

  if (loading) return <LoadingState lines={4} />;
  if (error) return <ErrorState title="Conversions unavailable" message={error} />;

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Conversions</CardTitle></CardHeader>
      <CardContent>
        {!items?.length
          ? <EmptyState title="No conversions" description="No attributed conversions found for this campaign." />
          : (
            <DataTable
              data={items}
              keyExtractor={r => String(r.conversion_id)}
              columns={[
                { key: 'conversion_id', header: 'ID', render: r => <span className="font-mono text-xs">{String(r.conversion_id ?? '').slice(0, 16)}…</span> },
                { key: 'conversion_type', header: 'Type', render: r => String(r.conversion_type ?? '—') },
                { key: 'gross_value', header: 'Gross $', render: r => fmtUSD(Number(r.gross_value ?? 0)) },
                { key: 'net_value', header: 'Net $', render: r => fmtUSD(Number(r.net_value ?? 0)) },
                { key: 'occurred_at', header: 'Date', render: r => r.occurred_at ? new Date(String(r.occurred_at)).toLocaleDateString() : '—' },
              ]}
            />
          )
        }
      </CardContent>
    </Card>
  );
}

// ── Attribution tab ───────────────────────────────────────────────────────────

function AttributionTab({ campaignId }: { campaignId: string }) {
  const { data, loading, error } = useCampaign360Attribution(campaignId, { model: 'last_touch' });
  if (loading) return <LoadingState lines={4} />;
  if (error) return <ErrorState title="Attribution unavailable" message={error} />;
  if (!data) return null;

  const d = data as AnyRecord;
  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Attribution credits</CardTitle></CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
          <Metric label="Conversions" value={String(d.conversions ?? '—')} />
          <Metric label="Gross revenue" value={d.attributed_gross_revenue != null ? fmtUSD(Number(d.attributed_gross_revenue)) : '—'} />
          <Metric label="Net revenue" value={d.attributed_net_revenue != null ? fmtUSD(Number(d.attributed_net_revenue)) : '—'} />
        </div>
        <div className="text-xs text-text-muted">
          Model: <strong>{String(d.model ?? 'last_touch')}</strong>
          {' · '}
          Quality: <strong>{String((d.quality as AnyRecord)?.status ?? d.data_quality ?? '—')}</strong>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const TABS = [
  { value: 'overview', label: 'Overview' },
  { value: 'population', label: 'Population' },
  { value: 'clusters', label: 'Clusters' },
  { value: 'conversions', label: 'Conversions' },
  { value: 'attribution', label: 'Attribution' },
];

export function Campaign360Page() {
  const { id: campaignId } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const tab = searchParams.get('tab') ?? 'overview';
  const timeStart = searchParams.get('start') ?? undefined;
  const timeEnd = searchParams.get('end') ?? undefined;
  const attributionModel = searchParams.get('attribution_model') ?? 'last_touch';

  const [campaign, setCampaign] = useState<AnyRecord | null>(null);
  const [campaignLoading, setCampaignLoading] = useState(true);

  useEffect(() => {
    if (!campaignId) return;
    setCampaignLoading(true);
    (api.campaigns.get(campaignId) as Promise<AnyRecord>)
      .then(d => setCampaign((d as AnyRecord)?.data as AnyRecord ?? d))
      .finally(() => setCampaignLoading(false));
  }, [campaignId]);

  function setTab(value: string) {
    setSearchParams(prev => { prev.set('tab', value); return prev; }, { replace: true });
  }

  if (!campaignId) return null;

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/campaigns')} className="text-xs text-text-muted hover:text-text-primary">
          ← Campaigns
        </button>
        {campaignLoading && <span className="text-sm text-text-muted">Loading…</span>}
        {campaign && (
          <>
            <h1 className="text-xl font-semibold text-text-primary">{String(campaign.name ?? campaignId)}</h1>
            <Badge variant={campaign.status === 'active' ? 'success' : 'default'}>{String(campaign.status ?? '—')}</Badge>
            <Badge variant="default">{String(campaign.channel ?? '—')}</Badge>
          </>
        )}
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          {TABS.map(t => (
            <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab
            campaignId={campaignId}
            {...(timeStart !== undefined ? { timeStart } : {})}
            {...(timeEnd !== undefined ? { timeEnd } : {})}
            attributionModel={attributionModel}
          />
        </TabsContent>

        <TabsContent value="population">
          <PopulationTab
            campaignId={campaignId}
            {...(timeStart !== undefined ? { timeStart } : {})}
            {...(timeEnd !== undefined ? { timeEnd } : {})}
          />
        </TabsContent>

        <TabsContent value="clusters">
          <ClustersTab campaignId={campaignId} />
        </TabsContent>

        <TabsContent value="conversions">
          <ConversionsTab
            campaignId={campaignId}
            {...(timeStart !== undefined ? { timeStart } : {})}
            {...(timeEnd !== undefined ? { timeEnd } : {})}
          />
        </TabsContent>

        <TabsContent value="attribution">
          <AttributionTab campaignId={campaignId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
