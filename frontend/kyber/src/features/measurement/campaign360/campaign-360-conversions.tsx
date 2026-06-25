import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState, ErrorState } from '@aether/ui';
import { useCampaign360Conversions } from '../use-campaign-360';

interface Props {
  campaignId: string;
  timeStart?: string;
  timeEnd?: string;
}

export function Campaign360Conversions({ campaignId, timeStart, timeEnd }: Props) {
  const [clusterId, setClusterId] = useState('');
  const [channel, setChannel] = useState('');
  const [includeUnattributed, setIncludeUnattributed] = useState(false);

  const { data, loading, error } = useCampaign360Conversions({
    campaignId,
    ...(clusterId ? { cluster_id: clusterId } : {}),
    ...(channel ? { channel } : {}),
    ...(timeStart !== undefined ? { after: timeStart } : {}),
    ...(timeEnd !== undefined ? { before: timeEnd } : {}),
    include_unattributed: includeUnattributed,
    limit: 100,
  });

  const items = (data as Record<string, unknown>)?.items as Record<string, unknown>[] | undefined;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <input
          value={clusterId}
          onChange={e => setClusterId(e.target.value)}
          placeholder="Cluster ID…"
          className="text-xs bg-surface-secondary border border-border rounded px-2 py-1 w-48 font-mono"
        />
        <input
          value={channel}
          onChange={e => setChannel(e.target.value)}
          placeholder="Channel…"
          className="text-xs bg-surface-secondary border border-border rounded px-2 py-1 w-32"
        />
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={includeUnattributed}
            onChange={e => setIncludeUnattributed(e.target.checked)}
            className="rounded"
          />
          Include unattributed
        </label>
      </div>

      {loading && <LoadingState lines={5} />}
      {error && <ErrorState title="Conversions unavailable" message={error} />}
      {!loading && !error && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Conversions</CardTitle></CardHeader>
          <CardContent>
            {!items?.length
              ? <EmptyState title="No conversions" description="No conversions found for this campaign with the selected filters." />
              : (
                <DataTable
                  data={items}
                  keyExtractor={r => String(r.conversion_id)}
                  columns={[
                    { key: 'conversion_id', header: 'ID', render: r => <span className="font-mono text-xs">{String(r.conversion_id ?? '').slice(0, 16)}…</span> },
                    { key: 'conversion_type', header: 'Type', render: r => String(r.conversion_type ?? '—') },
                    { key: 'status', header: 'Status', render: r => String(r.conversion_status ?? '—') },
                    { key: 'gross_value', header: 'Gross $', render: r => `$${Number(r.gross_value ?? 0).toFixed(2)}` },
                    { key: 'net_value', header: 'Net $', render: r => `$${Number(r.net_value ?? 0).toFixed(2)}` },
                    { key: 'occurred_at', header: 'Occurred', render: r => r.occurred_at ? new Date(String(r.occurred_at)).toLocaleDateString() : '—' },
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
