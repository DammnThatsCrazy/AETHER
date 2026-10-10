import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState, formatDate, formatDateTime, useTimeContext } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useJourneyExplorer, useJourneySteps, useJourneyTransitions, useJourneyExplain, useJourneyHealth } from '@kyber/features/measurement';
import { useState } from 'react';
import { api } from '@kyber/lib/api';

type Row = Record<string, unknown>;

const FAMILY_COLORS: Record<string, string> = {
  web2: 'text-blue-600',
  web3: 'text-violet-600',
  campaign: 'text-amber-600',
  commerce: 'text-green-600',
  agent: 'text-cyan-600',
  x402: 'text-rose-600',
  outcome: 'text-emerald-600',
};

function StepsPanel({ journeyId }: { journeyId: string }) {
  const [family, setFamily] = useState('');
  const timeCtx = useTimeContext();
  const { data, loading, error, loadMore } = useJourneySteps(journeyId, family ? { family } : {});

  return (
    <div>
      <div className="flex gap-2 mb-3">
        {['', 'web2', 'web3', 'campaign', 'commerce', 'agent', 'x402', 'outcome'].map(f => (
          <button
            key={f}
            onClick={() => setFamily(f)}
            className={`text-xs px-2 py-1 rounded border transition-colors ${family === f ? 'bg-accent text-white border-accent' : 'border-border'}`}
            aria-pressed={family === f}
          >
            {f || 'All'}
          </button>
        ))}
      </div>
      {loading && data.steps.length === 0 && <LoadingState lines={4} />}
      {error && <ErrorState title="Steps error" message={error} />}
      {!loading && data.steps.length === 0 && <EmptyState title="No steps" description="No steps found for these filters." />}
      {data.steps.length > 0 && (
        <DataTable
          data={data.steps as Row[]}
          keyExtractor={r => String(r.step_id ?? r.step_position)}
          columns={[
            { key: 'pos', header: '#', render: r => String(r.step_position ?? '—') },
            { key: 'family', header: 'Family', render: r => (
              <span className={`font-medium text-xs ${FAMILY_COLORS[String(r.activity_family)] ?? ''}`}>
                {String(r.activity_family ?? '—')}
              </span>
            )},
            { key: 'type', header: 'Type', render: r => <span className="text-xs">{String(r.activity_type ?? '—')}</span> },
            { key: 'status', header: 'Status', render: r => (
              <Badge variant={r.activity_status === 'confirmed' || r.activity_status === 'finalized' ? 'success' : r.activity_status === 'failed' || r.activity_status === 'reverted' ? 'danger' : 'default'}>
                {String(r.activity_status ?? '—')}
              </Badge>
            )},
            { key: 'transition', header: 'Transition', render: r => <span className="text-xs text-text-muted">{String(r.transition_type ?? '—')}</span> },
            { key: 'occurred', header: 'When', render: r => r.occurred_at ? formatDateTime(String(r.occurred_at), timeCtx) : '—' },
            { key: 'confidence', header: 'ID conf.', render: r => r.identity_confidence != null ? `${(Number(r.identity_confidence) * 100).toFixed(0)}%` : '—' },
          ]}
        />
      )}
      {data.hasMore && (
        <button onClick={loadMore} disabled={loading} className="mt-2 text-xs text-accent underline disabled:opacity-50">
          {loading ? 'Loading…' : 'Load more steps'}
        </button>
      )}
    </div>
  );
}

function TransitionsPanel({ journeyId }: { journeyId: string }) {
  const { data, loading, error } = useJourneyTransitions(journeyId);
  if (loading) return <LoadingState lines={3} />;
  if (error) return <ErrorState title="Transitions error" message={error} />;
  if (!data) return null;
  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-xs font-medium text-text-muted mb-1">Transition types</h4>
        <div className="grid grid-cols-2 gap-1 text-xs">
          {Object.entries(data.transitions).map(([k, v]) => (
            <div key={k} className="flex justify-between">
              <span className="text-text-muted">{k}</span>
              <span className="font-medium">{v}</span>
            </div>
          ))}
          {Object.keys(data.transitions).length === 0 && <span className="text-text-muted col-span-2">None</span>}
        </div>
      </div>
      <div>
        <h4 className="text-xs font-medium text-text-muted mb-1">Activity families</h4>
        <div className="grid grid-cols-2 gap-1 text-xs">
          {Object.entries(data.families).map(([k, v]) => (
            <div key={k} className="flex justify-between">
              <span className={FAMILY_COLORS[k] ?? 'text-text-muted'}>{k}</span>
              <span className="font-medium">{v}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="flex gap-3 text-xs">
        {data.has_web3 && <Badge variant="default">has Web3</Badge>}
        {data.has_agent && <Badge variant="default">has Agent</Badge>}
        {data.has_x402 && <Badge variant="default">has x402</Badge>}
      </div>
    </div>
  );
}

function ExplainPanel({ journeyId }: { journeyId: string }) {
  const { data, loading, error } = useJourneyExplain(journeyId);
  if (loading) return <LoadingState lines={3} />;
  if (error) return <ErrorState title="Explain error" message={error} />;
  if (!data) return null;
  const identity = (data.identity ?? {}) as Record<string, unknown>;
  const rails = (data.rails ?? {}) as Record<string, unknown>;
  const dq = (data.data_quality ?? {}) as Record<string, unknown>;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
      <dt className="text-text-muted">Compiler</dt><dd className="font-mono">{String(data.compiler_version ?? '—')}</dd>
      <dt className="text-text-muted">Rebuild reason</dt><dd>{String(data.rebuild_reason ?? '—')}</dd>
      <dt className="text-text-muted">Step count</dt><dd>{String(data.step_count ?? 0)}</dd>
      <dt className="text-text-muted">Avg confidence</dt><dd>{identity.avg_confidence != null ? `${(Number(identity.avg_confidence) * 100).toFixed(1)}%` : '—'}</dd>
      <dt className="text-text-muted">Min confidence</dt><dd>{identity.min_confidence != null ? `${(Number(identity.min_confidence) * 100).toFixed(1)}%` : '—'}</dd>
      <dt className="text-text-muted">Web3 steps</dt><dd>{String(rails.web3_steps ?? 0)}</dd>
      <dt className="text-text-muted">Agent steps</dt><dd>{String(rails.agent_steps ?? 0)}</dd>
      <dt className="text-text-muted">x402 steps</dt><dd>{String(rails.x402_steps ?? 0)}</dd>
      <dt className="text-text-muted">Quality</dt>
      <dd>
        <Badge variant={dq.status === 'complete' ? 'success' : dq.status === 'partial' ? 'warning' : 'default'}>
          {String(dq.status ?? '—')}
        </Badge>
      </dd>
      {Boolean(dq.message) && (
        <><dt className="text-text-muted col-span-2 mt-1" /><dd className="text-amber-700 text-[10px] col-span-2">{String(dq.message ?? '')}</dd></>
      )}
    </dl>
  );
}

function RebuildButton({ journeyId, onRebuilt }: { journeyId: string; onRebuilt: () => void }) {
  const [rebuilding, setRebuilding] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  async function handleRebuild() {
    setRebuilding(true);
    setLastResult(null);
    try {
      await api.journeysMeasurement.rebuild(journeyId, 'operator_manual');
      setLastResult('Rebuild triggered successfully.');
      onRebuilt();
    } catch (e) {
      setLastResult(`Rebuild failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRebuilding(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={handleRebuild}
        disabled={rebuilding}
        className="px-3 py-1.5 text-xs bg-accent text-white rounded disabled:opacity-50 hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-accent"
        aria-label="Trigger journey rebuild for this profile"
      >
        {rebuilding ? 'Rebuilding…' : 'Rebuild journey'}
      </button>
      {lastResult && <span className="text-xs text-text-muted">{lastResult}</span>}
    </div>
  );
}

function HealthPanel() {
  const { data, loading, error, refresh } = useJourneyHealth();
  const timeCtx = useTimeContext();
  if (loading) return <LoadingState lines={3} />;
  if (error) return <ErrorState title="Health fetch failed" message={error} />;
  const s = data.summary;
  const QUALITY_VARIANT: Record<string, 'success' | 'warning' | 'danger' | 'default'> = {
    complete: 'success', partial: 'warning', empty: 'danger', not_provisioned: 'default',
  };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        <div className="bg-surface-secondary rounded p-3">
          <div className="text-text-muted mb-0.5">Total journeys</div>
          <div className="text-lg font-semibold">{s.total_journeys}</div>
        </div>
        <div className="bg-surface-secondary rounded p-3">
          <div className="text-text-muted mb-0.5">Avg steps</div>
          <div className="text-lg font-semibold">{s.avg_steps_per_journey}</div>
        </div>
        <div className="bg-surface-secondary rounded p-3">
          <div className="text-text-muted mb-0.5">Rebuild queue</div>
          <div className="text-lg font-semibold">{data.rebuild_queue_depth ?? '—'}</div>
        </div>
        <div className="bg-surface-secondary rounded p-3">
          <div className="text-text-muted mb-0.5">Web3 finality backlog</div>
          <div className="text-lg font-semibold">{data.web3_finality_backlog ?? '—'}</div>
        </div>
      </div>
      <div>
        <h4 className="text-xs font-medium text-text-muted mb-2">Quality breakdown</h4>
        <div className="flex gap-2 flex-wrap">
          {Object.entries(s.quality_breakdown).map(([status, count]) => (
            <div key={status} className="flex items-center gap-1 text-xs">
              <Badge variant={QUALITY_VARIANT[status] ?? 'default'}>{status}</Badge>
              <span className="font-medium">{count}</span>
            </div>
          ))}
          {Object.keys(s.quality_breakdown).length === 0 && <span className="text-text-muted text-xs">No data</span>}
        </div>
      </div>
      <div>
        <h4 className="text-xs font-medium text-text-muted mb-2">Compiler versions</h4>
        <div className="flex gap-3 flex-wrap text-xs">
          {Object.entries(s.compiler_versions).map(([v, count]) => (
            <span key={v} className="font-mono text-text-muted">{v}: <strong className="text-text">{count}</strong></span>
          ))}
          {Object.keys(s.compiler_versions).length === 0 && <span className="text-text-muted">No data</span>}
        </div>
      </div>
      {data.failed_or_partial.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-text-muted mb-2">Failed / partial journeys</h4>
          <DataTable
            data={data.failed_or_partial as Row[]}
            keyExtractor={r => String(r.journey_id ?? r.profile_id ?? `${r.started_at ?? 'undated'}:${r.status ?? 'unknown'}`)}
            columns={[
              { key: 'profile', header: 'Profile', render: r => <span className="font-mono text-xs">{String(r.profile_id ?? '—').slice(0, 12)}…</span> },
              { key: 'quality', header: 'Quality', render: r => <Badge variant={QUALITY_VARIANT[String(r.quality_status)] ?? 'default'}>{String(r.quality_status ?? '—')}</Badge> },
              { key: 'compiler', header: 'Compiler', render: r => <span className="font-mono text-xs">{String(r.compiler_version ?? '—')}</span> },
              { key: 'computed', header: 'Last compiled', render: r => r.computed_at ? formatDateTime(String(r.computed_at), timeCtx) : '—' },
            ]}
          />
        </div>
      )}
      <button onClick={refresh} className="text-xs text-accent underline mt-1">Refresh</button>
    </div>
  );
}

export function JourneyExplorerPage() {
  const [profileId, setProfileId] = useState('');
  const [campaignId, setCampaignId] = useState('');
  const [submitted, setSubmitted] = useState({ profile_id: '', campaign_id: '' });
  const [selectedJourneyId, setSelectedJourneyId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<'steps' | 'transitions' | 'explain'>('steps');
  const [refreshKey, setRefreshKey] = useState(0);

  const { data, loading, error } = useJourneyExplorer({
    ...(submitted.profile_id ? { profile_id: submitted.profile_id } : {}),
    ...(submitted.campaign_id ? { campaign_id: submitted.campaign_id } : {}),
  });
  const timeCtx = useTimeContext();

  function handleSearch() {
    setSubmitted({ profile_id: profileId, campaign_id: campaignId });
    setSelectedJourneyId(null);
  }

  function handleClear() {
    setProfileId('');
    setCampaignId('');
    setSubmitted({ profile_id: '', campaign_id: '' });
    setSelectedJourneyId(null);
  }

  if (loading) return <PageWrapper title="Journey Explorer"><LoadingState lines={6} /></PageWrapper>;
  if (error) return <PageWrapper title="Journey Explorer"><ErrorState title="Unable to load journeys" message={error} /></PageWrapper>;

  const journeys = data.journeys as Row[];
  const hasFilters = submitted.profile_id || submitted.campaign_id;

  return (
    <PageWrapper
      title="Journey Explorer"
      subtitle="Unified cross-rail journey versions — Web2, Web3, campaign, agent, x402, and outcome steps interleaved."
    >
      <div className="flex gap-2 mb-4 flex-wrap">
        <input
          value={profileId}
          onChange={e => setProfileId(e.target.value)}
          placeholder="Filter by profile ID…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-48"
          aria-label="Profile ID filter"
        />
        <input
          value={campaignId}
          onChange={e => setCampaignId(e.target.value)}
          placeholder="Filter by campaign ID…"
          className="text-sm bg-surface-secondary border border-border rounded px-3 py-1.5 w-48"
          aria-label="Campaign ID filter"
        />
        <button onClick={handleSearch} className="px-4 py-1.5 text-sm bg-accent text-white rounded hover:bg-accent/90">
          Search
        </button>
        {hasFilters && <button onClick={handleClear} className="px-4 py-1.5 text-sm border border-border rounded">Clear</button>}
      </div>

      <Card className="mb-4">
        <CardHeader><CardTitle>Compiler health</CardTitle></CardHeader>
        <CardContent><HealthPanel /></CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card>
          <CardHeader><CardTitle>Journey versions</CardTitle></CardHeader>
          <CardContent>
            {journeys.length === 0
              ? <EmptyState title="No journeys found" description="Journeys are compiled when activity arrives. Search by profile ID." />
              : <DataTable
                  data={journeys}
                  keyExtractor={r => String(r.journey_id ?? r.journey_version_id)}
                  onRowClick={r => setSelectedJourneyId(String(r.journey_id ?? ''))}
                  columns={[
                    { key: 'id', header: 'Journey ID', render: r => <span className="font-mono text-xs">{String(r.journey_id ?? '').slice(0, 8)}…</span> },
                    { key: 'profile', header: 'Profile', render: r => <span className="font-mono text-xs">{String(r.profile_id ?? '—').slice(0, 12)}…</span> },
                    { key: 'state', header: 'State', render: r => <Badge variant={r.journey_state === 'converted' ? 'success' : 'default'}>{String(r.journey_state ?? '—')}</Badge> },
                    { key: 'steps', header: 'Steps', render: r => String(r.step_count ?? (r.touchpoint_ids as unknown[] | undefined)?.length ?? 0) },
                    { key: 'compiler', header: 'Compiler', render: r => <span className="font-mono text-xs">{String(r.compiler_version ?? '—')}</span> },
                    { key: 'started', header: 'Started', render: r => r.started_at ? formatDate(String(r.started_at), timeCtx) : '—' },
                  ]}
                />
            }
          </CardContent>
        </Card>

        {selectedJourneyId && (
          <Card>
            <CardHeader>
              <CardTitle>Journey detail</CardTitle>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                {(['steps', 'transitions', 'explain'] as const).map(tab => (
                  <button
                    key={tab}
                    onClick={() => setDetailTab(tab)}
                    className={`text-xs px-3 py-1 rounded border ${detailTab === tab ? 'bg-accent text-white border-accent' : 'border-border'}`}
                    aria-selected={detailTab === tab}
                  >
                    {tab.charAt(0).toUpperCase() + tab.slice(1)}
                  </button>
                ))}
                <div className="ml-auto">
                  <RebuildButton
                    journeyId={selectedJourneyId}
                    onRebuilt={() => setRefreshKey(k => k + 1)}
                  />
                </div>
              </div>
            </CardHeader>
            <CardContent key={`${selectedJourneyId}-${refreshKey}`}>
              {detailTab === 'steps' && <StepsPanel journeyId={selectedJourneyId} />}
              {detailTab === 'transitions' && <TransitionsPanel journeyId={selectedJourneyId} />}
              {detailTab === 'explain' && <ExplainPanel journeyId={selectedJourneyId} />}
            </CardContent>
          </Card>
        )}
      </div>
    </PageWrapper>
  );
}
