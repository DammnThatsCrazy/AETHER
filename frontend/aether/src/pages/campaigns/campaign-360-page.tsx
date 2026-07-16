import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, ErrorState, LoadingState, Tabs, TabsContent, TabsList, TabsTrigger } from '@aether/ui';
import { CardLinkedOutcomesTab } from './card-linked-outcomes-tab';
import { api } from '@aether-app/lib/api/endpoints';
import {
  useCampaign360Overview,
  useCampaign360Population,
  useCampaign360Clusters,
  useCampaign360Conversions,
  useCampaign360Attribution,
} from '@aether-app/features/campaigns/use-campaign-360';
import { CampaignTargetingIntelligenceTab } from '@aether-app/features/targeting-intelligence';

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

// ── Messages tab (Communications Intelligence) ────────────────────────────────

function MessageDetailDrawer({ campaignId, externalMessageId, onClose }: {
  campaignId: string;
  externalMessageId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    (api.campaigns.messageDetail(campaignId, externalMessageId) as Promise<AnyRecord>)
      .then(d => { if (active) setDetail(d as AnyRecord); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [campaignId, externalMessageId]);

  const message = (detail?.message as AnyRecord) ?? {};
  const stats = (detail?.stats as AnyRecord) ?? {};
  const links = (detail?.links as AnyRecord[]) ?? [];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Message detail: ${externalMessageId}`}
      className="fixed inset-y-0 right-0 z-40 w-full max-w-lg bg-surface-base border-l border-border-default shadow-xl overflow-y-auto"
    >
      <div className="flex items-center justify-between px-5 py-4 border-b border-border-default sticky top-0 bg-surface-base">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">{String(message.name ?? externalMessageId)}</h2>
          <p className="text-xs text-text-muted font-mono">{externalMessageId}</p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close message detail"
          className="text-xs px-2 py-1 rounded border border-border-default text-text-secondary hover:text-text-primary"
        >
          Close
        </button>
      </div>
      <div className="p-5 space-y-5">
        {loading && <LoadingState lines={6} />}
        {error && <ErrorState title="Message detail unavailable" message={error} />}
        {!loading && !error && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Metric label="Delivered" value={Number(stats.delivered ?? 0).toLocaleString()} />
              <Metric label="Human clicks" value={Number(stats.human_clicks ?? 0).toLocaleString()} />
              <Metric label="Replies" value={Number(stats.replies ?? 0).toLocaleString()} />
              <Metric label="Bounces" value={Number(stats.bounces ?? 0).toLocaleString()} />
              <Metric label="Machine events" value={Number(stats.machine_events ?? 0).toLocaleString()} />
              <Metric label="Sequence step" value={message.sequence_step != null ? String(message.sequence_step) : '—'} />
            </div>
            <div className="text-xs text-text-secondary space-y-1">
              <p>Provider: <span className="text-text-primary">{String(message.provider ?? '—')}</span></p>
              <p>Template: <span className="font-mono">{String(message.external_template_id ?? '—')}</span></p>
              <p>Variant: <span className="font-mono">{String(message.variant_id ?? '—')}</span></p>
              <p>Status: <Badge variant={message.status === 'active' ? 'success' : 'default'}>{String(message.status ?? '—')}</Badge></p>
              <p>First seen: {message.first_seen_at ? new Date(String(message.first_seen_at)).toLocaleString() : '—'}</p>
            </div>
            <div>
              <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-2">Links</h3>
              {!links.length
                ? <EmptyState title="No link activity" description="No human-qualified clicks recorded for this message yet." />
                : (
                  <DataTable
                    data={links}
                    keyExtractor={r => String(r.link_id)}
                    columns={[
                      { key: 'link_id', header: 'Link', render: r => <span className="font-mono text-xs break-all">{String(r.link_id ?? '')}</span> },
                      { key: 'human_clicks', header: 'Human clicks', render: r => Number(r.human_clicks ?? 0).toLocaleString() },
                    ]}
                  />
                )
              }
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const POPULATION_STAGES = ['all', 'attempted', 'delivered', 'engaged', 'replied'] as const;

function CommsRecipientsSection({ campaignId }: { campaignId: string }) {
  const [stage, setStage] = useState<(typeof POPULATION_STAGES)[number]>('all');
  const [rows, setRows] = useState<AnyRecord[]>([]);
  const [stageCounts, setStageCounts] = useState<AnyRecord>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    (api.campaigns.commsPopulation(campaignId, stage === 'all' ? { limit: 100 } : { stage, limit: 100 }) as Promise<AnyRecord>)
      .then(d => {
        if (!active) return;
        setRows(((d as AnyRecord).items as AnyRecord[]) ?? []);
        setStageCounts(((d as AnyRecord).stage_counts as AnyRecord) ?? {});
      })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [campaignId, stage]);

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Recipients</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-1 border border-border-default rounded-md p-0.5 w-fit" role="tablist" aria-label="Recipient stage">
          {POPULATION_STAGES.map(s => (
            <button
              key={s}
              role="tab"
              aria-selected={stage === s}
              onClick={() => setStage(s)}
              className={`px-3 py-1 text-xs rounded capitalize transition-colors ${stage === s ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'}`}
            >
              {s}{s !== 'all' && stageCounts[s] != null ? ` (${stageCounts[s]})` : ''}
            </button>
          ))}
        </div>
        {loading && <LoadingState lines={4} />}
        {error && <ErrorState title="Recipients unavailable" message={error} />}
        {!loading && !error && (
          !rows.length
            ? <EmptyState title="No recipients" description="No recipients match this stage yet." />
            : (
              <DataTable
                data={rows}
                keyExtractor={r => String(r.recipient_key)}
                columns={[
                  { key: 'recipient_display', header: 'Recipient', render: r => <span className="font-mono text-xs">{String(r.recipient_display ?? r.recipient_key ?? '').slice(0, 24)}</span> },
                  { key: 'stage', header: 'Stage', render: r => <Badge variant={r.stage === 'replied' ? 'success' : r.stage === 'engaged' ? 'success' : 'default'}>{String(r.stage)}</Badge> },
                  { key: 'delivered', header: 'Delivered', render: r => Number(r.delivered ?? 0).toLocaleString() },
                  { key: 'human_clicks', header: 'Human clicks', render: r => Number(r.human_clicks ?? 0).toLocaleString() },
                  { key: 'replies', header: 'Replies', render: r => Number(r.replies ?? 0).toLocaleString() },
                  {
                    key: 'flags', header: 'Flags',
                    render: r => (
                      <span className="flex gap-1">
                        {Boolean(r.bounced) && <Badge variant="danger" size="sm">bounced</Badge>}
                        {Boolean(r.complained) && <Badge variant="danger" size="sm">complained</Badge>}
                        {Boolean(r.unsubscribed) && <Badge variant="warning" size="sm">unsubscribed</Badge>}
                        {Boolean(r.suppressed) && <Badge variant="warning" size="sm">suppressed</Badge>}
                      </span>
                    ),
                  },
                  {
                    key: 'profile', header: 'Profile360',
                    render: r => r.entity_id
                      ? <a className="text-xs text-accent hover:underline" href={`/users/${String(r.entity_id)}`}>Open</a>
                      : <span className="text-text-muted text-xs">unresolved</span>,
                  },
                ]}
              />
            )
        )}
      </CardContent>
    </Card>
  );
}

function MessagesTab({ campaignId }: { campaignId: string }) {
  const [funnel, setFunnel] = useState<AnyRecord | null>(null);
  const [messages, setMessages] = useState<AnyRecord[] | null>(null);
  const [links, setLinks] = useState<AnyRecord[] | null>(null);
  const [mode, setMode] = useState<'provider_reported' | 'human_qualified'>('human_qualified');
  const [selectedMessage, setSelectedMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      api.campaigns.commsFunnel(campaignId) as Promise<AnyRecord>,
      api.campaigns.messages(campaignId) as Promise<AnyRecord>,
      api.campaigns.links(campaignId) as Promise<AnyRecord>,
    ])
      .then(([f, m, l]) => {
        if (!active) return;
        setFunnel(f as AnyRecord);
        setMessages(((m as AnyRecord)?.items as AnyRecord[]) ?? []);
        setLinks(((l as AnyRecord)?.items as AnyRecord[]) ?? []);
      })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [campaignId]);

  if (loading) return <LoadingState lines={6} />;
  if (error) return <ErrorState title="Messages unavailable" message={error} />;

  const modes = (funnel?.modes as AnyRecord) ?? {};
  const selected = (modes[mode] as AnyRecord) ?? {};
  const delivery = (funnel?.delivery as AnyRecord) ?? {};
  const quality = (funnel?.quality as AnyRecord) ?? {};
  const rateResults = [
    selected.open_rate_result,
    selected.click_rate_result,
    mode === 'human_qualified' ? selected.reply_rate_result : null,
  ].filter(Boolean) as AnyRecord[];
  const limitedRates = rateResults.filter(
    result => String(result.value_state ?? 'observed') !== 'observed',
  );

  return (
    <div className="space-y-4">
      <div
        className="flex gap-1 border border-border-default rounded-md p-0.5 w-fit"
        role="tablist"
        aria-label="Engagement funnel mode"
      >
        {([
          ['human_qualified', 'Human qualified'],
          ['provider_reported', 'Provider reported'],
        ] as const).map(([value, label]) => (
          <button
            key={value}
            role="tab"
            aria-selected={mode === value}
            onClick={() => setMode(value)}
            className={`px-3 py-1 text-xs rounded transition-colors ${mode === value ? 'bg-accent text-white' : 'text-text-secondary hover:text-text-primary'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="text-xs text-text-muted">
        {mode === 'human_qualified'
          ? 'Human-qualified engagement excludes suspected machine activity (security scanners, image proxies) and automated replies.'
          : 'Provider-reported numbers count every provider event, including machine-generated opens and clicks.'}
      </p>

      {limitedRates.length > 0 && (
        <div className="rounded-md border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-xs text-text-secondary">
          Rate values are withheld until the governed minimum sample is met.
          Current states: {limitedRates.map(result => String(result.value_state)).join(', ')}.
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <Metric label="Sent" value={Number(selected.sent ?? 0).toLocaleString()} />
        <Metric label="Delivered" value={Number(selected.delivered ?? 0).toLocaleString()} />
        <Metric label={mode === 'human_qualified' ? 'Human opens' : 'Reported opens'} value={Number(selected.opens ?? 0).toLocaleString()} />
        <Metric label={mode === 'human_qualified' ? 'Human clicks' : 'Reported clicks'} value={Number(selected.clicks ?? 0).toLocaleString()} />
        <Metric label="Replies" value={Number(((modes.human_qualified as AnyRecord) ?? {}).replies ?? 0).toLocaleString()} />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Metric label="Open rate" value={fmtPct(selected.open_rate as number | null)} />
        <Metric label="Click rate" value={fmtPct(selected.click_rate as number | null)} />
        <Metric label="Reply rate" value={fmtPct(selected.reply_rate as number | null)} />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Metric label="Hard bounces" value={Number(delivery.hard_bounces ?? 0).toLocaleString()} />
        <Metric label="Complaints" value={Number(delivery.complaints ?? 0).toLocaleString()} />
        <Metric label="Unsubscribes" value={Number(delivery.unsubscribes ?? 0).toLocaleString()} />
        <Metric label="Suspected machine events" value={fmtPct(quality.machine_event_rate as number | null)} />
      </div>

      <Card>
        <CardHeader><CardTitle className="text-sm">Messages</CardTitle></CardHeader>
        <CardContent>
          {!messages?.length
            ? <EmptyState title="No messages" description="No provider messages observed for this campaign yet." />
            : (
              <DataTable
                data={messages}
                keyExtractor={r => String(r.external_message_id)}
                columns={[
                  { key: 'name', header: 'Message', render: r => String(r.name ?? r.external_message_id ?? '—') },
                  { key: 'sequence_step', header: 'Step', render: r => r.sequence_step != null ? String(r.sequence_step) : '—' },
                  { key: 'status', header: 'Status', render: r => <Badge variant={r.status === 'active' ? 'success' : 'default'}>{String(r.status ?? '—')}</Badge> },
                  { key: 'delivered', header: 'Delivered', render: r => Number(r.delivered ?? 0).toLocaleString() },
                  { key: 'human_clicks', header: 'Human clicks', render: r => Number(r.human_clicks ?? 0).toLocaleString() },
                  { key: 'replies', header: 'Replies', render: r => Number(r.replies ?? 0).toLocaleString() },
                  { key: 'bounces', header: 'Bounces', render: r => Number(r.bounces ?? 0).toLocaleString() },
                  { key: 'machine_events', header: 'Machine', render: r => Number(r.machine_events ?? 0).toLocaleString() },
                  {
                    key: 'detail', header: '',
                    render: r => (
                      <button
                        onClick={() => setSelectedMessage(String(r.external_message_id))}
                        className="text-xs text-accent hover:underline"
                        aria-label={`Open detail for message ${String(r.name ?? r.external_message_id)}`}
                      >
                        Detail
                      </button>
                    ),
                  },
                ]}
              />
            )
          }
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Link performance</CardTitle></CardHeader>
        <CardContent>
          {!links?.length
            ? <EmptyState title="No link activity" description="No human-qualified link clicks observed yet." />
            : (
              <DataTable
                data={links}
                keyExtractor={r => String(r.link_id)}
                columns={[
                  { key: 'link_id', header: 'Link', render: r => <span className="font-mono text-xs break-all">{String(r.link_id ?? '')}</span> },
                  { key: 'external_message_id', header: 'Message', render: r => String(r.external_message_id ?? '—') },
                  { key: 'human_clicks', header: 'Human clicks', render: r => Number(r.human_clicks ?? 0).toLocaleString() },
                  { key: 'unique_clickers', header: 'Unique clickers', render: r => r.unique_clickers != null ? Number(r.unique_clickers).toLocaleString() : '—' },
                ]}
              />
            )
          }
        </CardContent>
      </Card>

      <CommsRecipientsSection campaignId={campaignId} />

      {selectedMessage && (
        <MessageDetailDrawer
          campaignId={campaignId}
          externalMessageId={selectedMessage}
          onClose={() => setSelectedMessage(null)}
        />
      )}
    </div>
  );
}

// ── Attribution tab ───────────────────────────────────────────────────────────

function AttributionTab({ campaignId }: { campaignId: string }) {
  const { data, loading, error } = useCampaign360Attribution(campaignId, { model: 'last_touch' });
  if (loading) return <LoadingState lines={4} />;
  if (error) return <ErrorState title="Attribution unavailable" message={error} />;
  if (!data) return null;

  const d = data as AnyRecord;
  const rawDimensionRollups = d.dimension_rollups;
  const dimensionRollups = (
    Array.isArray(rawDimensionRollups)
      ? rawDimensionRollups
      : Array.isArray((rawDimensionRollups as AnyRecord | null)?.items)
        ? (rawDimensionRollups as AnyRecord).items
        : []
  ) as AnyRecord[];

  return (
    <div className="space-y-4">
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

      <Card>
        <CardHeader><CardTitle className="text-sm">AI referral attribution dimensions</CardTitle></CardHeader>
        <CardContent>
          {dimensionRollups.length === 0
            ? <EmptyState title="No dimension rollups" description="Provider, product, mediation, actor, and journey-role credits appear after classified touchpoints are attributed." />
            : (
              <DataTable
                data={dimensionRollups}
                keyExtractor={r => String(r.dimension_key ?? [
                  r.source_class,
                  r.ai_provider ?? r.provider,
                  r.ai_product ?? r.product,
                  r.referral_mediation_type ?? r.mediation,
                  r.actor_type ?? r.actor,
                  r.journey_role ?? r.role,
                  r.verification_level,
                ].join('|'))}
                columns={[
                  { key: 'source_class', header: 'Source class', render: r => String(r.source_class ?? '—') },
                  { key: 'provider', header: 'Provider', render: r => String(r.ai_provider ?? r.provider ?? '—') },
                  { key: 'product', header: 'Product', render: r => String(r.ai_product ?? r.product ?? '—') },
                  { key: 'mediation', header: 'Mediation', render: r => String(r.referral_mediation_type ?? r.mediation ?? '—') },
                  { key: 'actor', header: 'Actor', render: r => String(r.actor_type ?? r.actor ?? '—') },
                  { key: 'role', header: 'Journey role', render: r => String(r.journey_role ?? r.role ?? '—') },
                  { key: 'verification', header: 'Verification', render: r => String(r.verification_level ?? '—') },
                  { key: 'conversions', header: 'Conversions', render: r => Number(r.conversions ?? r.attributed_conversions ?? 0).toLocaleString() },
                  { key: 'net_revenue', header: 'Net revenue', render: r => fmtUSD(Number(r.attributed_net_revenue ?? r.net_revenue ?? 0)) },
                ]}
              />
            )
          }
        </CardContent>
      </Card>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const TABS = [
  { value: 'overview', label: 'Overview' },
  { value: 'messages', label: 'Messages' },
  { value: 'population', label: 'Population' },
  { value: 'clusters', label: 'Clusters' },
  { value: 'conversions', label: 'Conversions' },
  { value: 'attribution', label: 'Attribution' },
  { value: 'targeting', label: 'Targeting Intelligence' },
  { value: 'card-linked', label: 'Card-linked Outcomes' },
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

        <TabsContent value="messages">
          <MessagesTab campaignId={campaignId} />
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

        <TabsContent value="targeting">
          <CampaignTargetingIntelligenceTab campaignId={campaignId} />
        </TabsContent>

        <TabsContent value="card-linked">
          <CardLinkedOutcomesTab campaignId={campaignId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
