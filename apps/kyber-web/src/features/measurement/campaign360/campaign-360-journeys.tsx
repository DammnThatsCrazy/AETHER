import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState, ErrorState, Badge, formatDate, useTimeContext } from '@aether/ui';
import { useCampaign360Journeys } from '../use-campaign-360';

interface Props {
  campaignId: string;
  timeStart?: string;
  timeEnd?: string;
}

export function Campaign360Journeys({ campaignId, timeStart, timeEnd }: Props) {
  const navigate = useNavigate();
  const timeCtx = useTimeContext();
  const { data, loading, error } = useCampaign360Journeys({
    campaignId,
    ...(timeStart !== undefined ? { time_start: timeStart } : {}),
    ...(timeEnd !== undefined ? { time_end: timeEnd } : {}),
    limit: 50,
  });

  const items = (data as Record<string, unknown>)?.items as Record<string, unknown>[] | undefined;

  if (loading) return <LoadingState lines={5} />;
  if (error) return <ErrorState title="Journeys unavailable" message={error} />;

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Journeys</CardTitle></CardHeader>
      <CardContent>
        {!items?.length
          ? <EmptyState title="No journeys" description="No journeys include this campaign." />
          : (
            <DataTable
              data={items}
              keyExtractor={r => String(r.journey_id)}
              columns={[
                { key: 'journey_id', header: 'Journey', render: r => (
                  <button
                    onClick={() => navigate(`/measurement/journeys?journey_id=${r.journey_id}`)}
                    className="font-mono text-xs text-accent hover:underline"
                  >
                    {String(r.journey_id ?? '').slice(0, 16)}…
                  </button>
                )},
                { key: 'profile_id', header: 'Profile', render: r => r.profile_id
                  ? <button onClick={() => navigate(`/profile360/profile/${r.profile_id}`)} className="font-mono text-xs text-accent hover:underline">{String(r.profile_id).slice(0, 12)}…</button>
                  : '—'
                },
                { key: 'stage_count', header: 'Stages', render: r => Number(r.stage_count ?? 0) },
                { key: 'converted', header: 'Converted', render: r => r.converted ? <Badge variant="success">Yes</Badge> : <Badge variant="default">No</Badge> },
                { key: 'started_at', header: 'Started', render: r => r.started_at ? formatDate(String(r.started_at), timeCtx) : '—' },
                { key: 'completed_at', header: 'Completed', render: r => r.completed_at ? formatDate(String(r.completed_at), timeCtx) : '—' },
              ]}
            />
          )
        }
      </CardContent>
    </Card>
  );
}
