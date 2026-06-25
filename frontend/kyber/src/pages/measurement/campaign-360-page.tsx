import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { Tabs, TabsList, TabsTrigger, TabsContent, Badge, LoadingState, ErrorState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';
import { Campaign360Overview } from '@kyber/features/measurement/campaign360/campaign-360-overview';
import { Campaign360Population } from '@kyber/features/measurement/campaign360/campaign-360-population';
import { Campaign360Clusters } from '@kyber/features/measurement/campaign360/campaign-360-clusters';
import { Campaign360Entities } from '@kyber/features/measurement/campaign360/campaign-360-entities';
import { Campaign360Journeys } from '@kyber/features/measurement/campaign360/campaign-360-journeys';
import { Campaign360Conversions } from '@kyber/features/measurement/campaign360/campaign-360-conversions';
import { Campaign360Attribution } from '@kyber/features/measurement/campaign360/campaign-360-attribution';
import { Campaign360Graph } from '@kyber/features/measurement/campaign360/campaign-360-graph';
import { Campaign360Quality } from '@kyber/features/measurement/campaign360/campaign-360-quality';

const TABS = [
  { value: 'overview', label: 'Overview' },
  { value: 'population', label: 'Population' },
  { value: 'clusters', label: 'Clusters' },
  { value: 'entities', label: 'Entities' },
  { value: 'journeys', label: 'Journeys' },
  { value: 'conversions', label: 'Conversions' },
  { value: 'attribution', label: 'Attribution' },
  { value: 'graph', label: 'Graph' },
  { value: 'quality', label: 'Quality' },
];

type AnyRecord = Record<string, unknown>;

export function Campaign360Page() {
  const { campaignId } = useParams<{ campaignId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const tab = searchParams.get('tab') ?? 'overview';
  const timeStart = searchParams.get('start') ?? undefined;
  const timeEnd = searchParams.get('end') ?? undefined;
  const attributionModel = searchParams.get('attribution_model') ?? 'last_touch';
  const attributionRunId = searchParams.get('attribution_run_id') ?? undefined;

  const [campaign, setCampaign] = useState<AnyRecord | null>(null);
  const [campaignLoading, setCampaignLoading] = useState(true);
  const [campaignError, setCampaignError] = useState<string | null>(null);

  useEffect(() => {
    if (!campaignId) return;
    setCampaignLoading(true);
    setCampaignError(null);
    (api.campaigns.get(campaignId) as Promise<AnyRecord>)
      .then(d => setCampaign((d as AnyRecord)?.data as AnyRecord ?? d))
      .catch(e => setCampaignError(e instanceof Error ? e.message : String(e)))
      .finally(() => setCampaignLoading(false));
  }, [campaignId]);

  function setTab(value: string) {
    setSearchParams(prev => { prev.set('tab', value); return prev; }, { replace: true });
  }

  if (!campaignId) {
    return <PageWrapper title="Campaign 360"><ErrorState title="No campaign ID" message="Navigate to this page with a valid campaign ID." /></PageWrapper>;
  }

  const overviewParams = {
    campaignId,
    time_start: timeStart,
    time_end: timeEnd,
    attribution_model: attributionModel,
    attribution_run_id: attributionRunId,
  };

  return (
    <PageWrapper
      title={campaignLoading ? 'Campaign 360' : `Campaign 360 — ${String(campaign?.name ?? campaignId)}`}
      subtitle={campaign ? `${String(campaign.channel ?? '')} · ${String(campaign.status ?? '')}` : undefined}
      actions={
        <button
          onClick={() => navigate('/measurement/campaigns')}
          className="text-xs text-accent hover:underline"
        >
          ← All campaigns
        </button>
      }
    >
      {campaignLoading && <LoadingState lines={2} className="mb-4" />}
      {campaignError && <ErrorState title="Campaign not found" message={campaignError} className="mb-4" />}
      {campaign && (
        <div className="flex items-center gap-2 mb-4">
          <Badge variant="secondary">{String(campaign.channel ?? '—')}</Badge>
          <Badge variant={campaign.status === 'active' ? 'success' : 'secondary'}>{String(campaign.status ?? '—')}</Badge>
          {campaign.start_date && (
            <span className="text-xs text-text-muted">
              {String(campaign.start_date)} → {String(campaign.end_date ?? 'ongoing')}
            </span>
          )}
        </div>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex-wrap">
          {TABS.map(t => (
            <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview">
          <Campaign360Overview params={overviewParams} />
        </TabsContent>

        <TabsContent value="population">
          <Campaign360Population campaignId={campaignId} timeStart={timeStart} timeEnd={timeEnd} />
        </TabsContent>

        <TabsContent value="clusters">
          <Campaign360Clusters
            campaignId={campaignId}
            attributionRunId={attributionRunId}
            timeStart={timeStart}
            timeEnd={timeEnd}
          />
        </TabsContent>

        <TabsContent value="entities">
          <Campaign360Entities campaignId={campaignId} timeStart={timeStart} timeEnd={timeEnd} />
        </TabsContent>

        <TabsContent value="journeys">
          <Campaign360Journeys campaignId={campaignId} timeStart={timeStart} timeEnd={timeEnd} />
        </TabsContent>

        <TabsContent value="conversions">
          <Campaign360Conversions campaignId={campaignId} timeStart={timeStart} timeEnd={timeEnd} />
        </TabsContent>

        <TabsContent value="attribution">
          <Campaign360Attribution params={overviewParams} />
        </TabsContent>

        <TabsContent value="graph">
          <Campaign360Graph campaignId={campaignId} timeStart={timeStart} timeEnd={timeEnd} />
        </TabsContent>

        <TabsContent value="quality">
          <Campaign360Quality params={overviewParams} />
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
