import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState, ErrorState } from '@aether/ui';
import { useCampaign360Population } from '../use-campaign-360';
import type { PopulationType } from '@aether/shared';

const POPULATION_TYPES: { value: PopulationType; label: string }[] = [
  { value: 'observed', label: 'Observed' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'engaged', label: 'Engaged' },
  { value: 'converted', label: 'Converted' },
  { value: 'attributed', label: 'Attributed' },
];

interface Props {
  campaignId: string;
  timeStart?: string;
  timeEnd?: string;
}

export function Campaign360Population({ campaignId, timeStart, timeEnd }: Props) {
  const [population, setPopulation] = useState<PopulationType>('observed');
  const [channel, setChannel] = useState('');

  const { data, loading, error } = useCampaign360Population({
    campaignId,
    population,
    ...(channel ? { channel } : {}),
    ...(timeStart !== undefined ? { time_start: timeStart } : {}),
    ...(timeEnd !== undefined ? { time_end: timeEnd } : {}),
    limit: 100,
  });

  const items = (data as Record<string, unknown>)?.items as Record<string, unknown>[] | undefined;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1 border border-border rounded-md p-0.5">
          {POPULATION_TYPES.map(pt => (
            <button
              key={pt.value}
              onClick={() => setPopulation(pt.value)}
              className={`px-3 py-1 text-xs rounded transition-colors ${population === pt.value ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'}`}
            >
              {pt.label}
            </button>
          ))}
        </div>
        <input
          value={channel}
          onChange={e => setChannel(e.target.value)}
          placeholder="Channel filter…"
          className="text-xs bg-surface-secondary border border-border rounded px-2 py-1 w-40"
        />
      </div>

      {loading && <LoadingState lines={5} />}
      {error && <ErrorState title="Population unavailable" message={error} />}
      {!loading && !error && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm capitalize">{population} population</CardTitle>
          </CardHeader>
          <CardContent>
            {!items?.length
              ? <EmptyState title="No entities" description={`No ${population} entities found for this campaign.`} />
              : (
                <DataTable
                  data={items}
                  keyExtractor={r => String(r.entity_id)}
                  columns={[
                    { key: 'entity_id', header: 'Entity', render: r => <span className="font-mono text-xs">{String(r.entity_id ?? '').slice(0, 16)}…</span> },
                    { key: 'entity_type', header: 'Type', render: r => String(r.entity_type ?? '—') },
                    { key: 'cluster_id', header: 'Cluster', render: r => r.cluster_id ? <span className="font-mono text-xs">{String(r.cluster_id).slice(0, 12)}…</span> : '—' },
                    { key: 'touchpoint_count', header: 'Touchpoints', render: r => Number(r.touchpoint_count ?? 0).toLocaleString() },
                    { key: 'conversion_count', header: 'Conversions', render: r => Number(r.conversion_count ?? 0).toLocaleString() },
                    { key: 'attributed_revenue', header: 'Attributed $', render: r => `$${Number(r.attributed_revenue ?? 0).toFixed(2)}` },
                    { key: 'channels', header: 'Channels', render: r => (Array.isArray(r.channels) ? r.channels.join(', ') : '—') },
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
