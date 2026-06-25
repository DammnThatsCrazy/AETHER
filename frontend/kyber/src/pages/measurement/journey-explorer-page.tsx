import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useJourneyExplorer } from '@kyber/features/measurement';
import { useState } from 'react';

type Row = Record<string, unknown>;

export function JourneyExplorerPage() {
  const [profileId, setProfileId] = useState('');
  const [campaignId, setCampaignId] = useState('');
  const [submitted, setSubmitted] = useState({ profile_id: '', campaign_id: '' });

  const { data, loading, error } = useJourneyExplorer({
    ...(submitted.profile_id ? { profile_id: submitted.profile_id } : {}),
    ...(submitted.campaign_id ? { campaign_id: submitted.campaign_id } : {}),
  });

  function handleSearch() {
    setSubmitted({ profile_id: profileId, campaign_id: campaignId });
  }

  function handleClear() {
    setProfileId('');
    setCampaignId('');
    setSubmitted({ profile_id: '', campaign_id: '' });
  }

  if (loading) return <PageWrapper title="Journey Explorer"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Journey Explorer"><ErrorState title="Unable to load journeys" message={error} /></PageWrapper>;

  const journeys = data.journeys as Row[];
  const hasFilters = submitted.profile_id || submitted.campaign_id;

  return (
    <PageWrapper
      title="Journey Explorer"
      subtitle="Versioned customer journeys — ordered touchpoint sequences from first exposure to conversion."
    >
      <div className="flex gap-2 mb-4 flex-wrap">
        <input
          value={profileId}
          onChange={e => setProfileId(e.target.value)}
          placeholder="Filter by profile ID…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-48"
        />
        <input
          value={campaignId}
          onChange={e => setCampaignId(e.target.value)}
          placeholder="Filter by campaign ID…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-48"
        />
        <button onClick={handleSearch} className="px-4 py-1.5 text-sm bg-accent text-white rounded">
          Search
        </button>
        {hasFilters && <button onClick={handleClear} className="px-4 py-1.5 text-sm border border-border rounded">Clear</button>}
      </div>

      <Card>
        <CardHeader><CardTitle>Active journey versions</CardTitle></CardHeader>
        <CardContent>
          {journeys.length === 0
            ? <EmptyState title="No journeys found" description="Journeys are compiled when touchpoints arrive. Try searching by profile ID." />
            : <DataTable data={journeys} keyExtractor={r => String(r.journey_id ?? r.journey_version_id)} columns={[
                { key: 'id', header: 'Journey ID', render: r => <span className="font-mono text-xs">{String(r.journey_id ?? '').slice(0, 8)}…</span> },
                { key: 'profile', header: 'Profile', render: r => <span className="font-mono text-xs">{String(r.profile_id ?? '—').slice(0, 12)}…</span> },
                { key: 'state', header: 'State', render: r => <Badge variant={r.journey_state === 'converted' ? 'success' : 'default'}>{String(r.journey_state ?? '—')}</Badge> },
                { key: 'touchpoints', header: 'Touchpoints', render: r => String((r.touchpoint_ids as unknown[] | undefined)?.length ?? 0) },
                { key: 'conversions', header: 'Conversions', render: r => String((r.conversion_ids as unknown[] | undefined)?.length ?? 0) },
                { key: 'channel_seq', header: 'Channel sequence', render: r => {
                  const seq = (r.channel_sequence as string[] | undefined) ?? [];
                  return <span className="text-xs text-text-muted">{seq.slice(0, 4).join(' → ')}{seq.length > 4 ? ' …' : ''}</span>;
                }},
                { key: 'started', header: 'Started', render: r => r.started_at ? new Date(String(r.started_at)).toLocaleDateString() : '—' },
              ]} />
          }
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
