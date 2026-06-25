import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, LoadingState, ErrorState } from '@aether/ui';
import { useCampaign360Entities } from '../use-campaign-360';

const ENTITY_TYPES = ['', 'profile', 'cluster', 'account', 'organization', 'anonymous'];

interface Props {
  campaignId: string;
  timeStart?: string;
  timeEnd?: string;
}

export function Campaign360Entities({ campaignId, timeStart, timeEnd }: Props) {
  const [entityType, setEntityType] = useState('');
  const navigate = useNavigate();

  const { data, loading, error } = useCampaign360Entities({
    campaignId,
    entity_type: entityType || undefined,
    time_start: timeStart,
    time_end: timeEnd,
    limit: 100,
  });

  const items = (data as Record<string, unknown>)?.items as Record<string, unknown>[] | undefined;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-xs text-text-muted">Entity type:</span>
        <select
          value={entityType}
          onChange={e => setEntityType(e.target.value)}
          className="text-xs bg-surface-secondary border border-border rounded px-2 py-1"
        >
          {ENTITY_TYPES.map(t => (
            <option key={t} value={t}>{t || 'All'}</option>
          ))}
        </select>
      </div>

      {loading && <LoadingState lines={5} />}
      {error && <ErrorState title="Entities unavailable" message={error} />}
      {!loading && !error && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Entities</CardTitle></CardHeader>
          <CardContent>
            {!items?.length
              ? <EmptyState title="No entities" description="No entities found for this campaign with the selected filter." />
              : (
                <DataTable
                  data={items}
                  keyExtractor={r => String(r.canonical_id)}
                  columns={[
                    { key: 'canonical_id', header: 'ID', render: r => (
                      <button
                        onClick={() => navigate(`/profile360/${r.entity_type}/${r.canonical_id}`)}
                        className="font-mono text-xs text-accent hover:underline"
                      >
                        {String(r.canonical_id ?? '').slice(0, 16)}…
                      </button>
                    )},
                    { key: 'entity_type', header: 'Type', render: r => String(r.entity_type ?? '—') },
                    { key: 'cluster_id', header: 'Cluster', render: r => r.cluster_id ? <span className="font-mono text-xs">{String(r.cluster_id).slice(0, 12)}…</span> : '—' },
                    { key: 'touchpoint_count', header: 'Touchpoints', render: r => Number(r.touchpoint_count ?? 0).toLocaleString() },
                    { key: 'conversion_count', header: 'Conversions', render: r => Number(r.conversion_count ?? 0).toLocaleString() },
                    { key: 'attributed_revenue', header: 'Attributed $', render: r => `$${Number(r.attributed_revenue ?? 0).toFixed(2)}` },
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
