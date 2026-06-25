import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState, ErrorState } from '@aether/ui';
import { useCampaign360Clusters } from '../use-campaign-360';

interface Props {
  campaignId: string;
  attributionRunId?: string;
  timeStart?: string;
  timeEnd?: string;
}

export function Campaign360Clusters({ campaignId, attributionRunId, timeStart, timeEnd }: Props) {
  const navigate = useNavigate();
  const { data, loading, error } = useCampaign360Clusters({
    campaignId,
    ...(attributionRunId !== undefined ? { attribution_run_id: attributionRunId } : {}),
    ...(timeStart !== undefined ? { time_start: timeStart } : {}),
    ...(timeEnd !== undefined ? { time_end: timeEnd } : {}),
    limit: 100,
  });

  const items = (data as Record<string, unknown>)?.items as Record<string, unknown>[] | undefined;

  if (loading) return <LoadingState lines={5} />;
  if (error) return <ErrorState title="Clusters unavailable" message={error} />;

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Cluster rollup</CardTitle></CardHeader>
      <CardContent>
        {!items?.length
          ? <EmptyState title="No clusters" description="No identity clusters found for this campaign." />
          : (
            <DataTable
              data={items}
              keyExtractor={r => String(r.cluster_id ?? Math.random())}
              columns={[
                { key: 'cluster_id', header: 'Cluster', render: r => (
                  r.cluster_id
                    ? (
                      <button
                        onClick={() => navigate(`/profile360/cluster/${r.cluster_id}`)}
                        className="font-mono text-xs text-accent hover:underline"
                      >
                        {String(r.cluster_id).slice(0, 16)}…
                      </button>
                    )
                    : <span className="text-text-muted text-xs">unresolved</span>
                )},
                { key: 'conversion_count', header: 'Conversions', render: r => Number(r.conversion_count ?? 0).toLocaleString() },
                { key: 'attributed_gross_revenue', header: 'Gross $', render: r => `$${Number(r.attributed_gross_revenue ?? 0).toFixed(2)}` },
                { key: 'attributed_net_revenue', header: 'Net $', render: r => `$${Number(r.attributed_net_revenue ?? 0).toFixed(2)}` },
                { key: 'identity_confidence', header: 'Confidence', render: r => r.identity_confidence != null ? `${(Number(r.identity_confidence) * 100).toFixed(0)}%` : '—' },
              ]}
            />
          )
        }
      </CardContent>
    </Card>
  );
}
