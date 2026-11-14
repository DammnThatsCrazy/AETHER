import { useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { formatCount, useTimeContext } from '@aether/ui';
import { GlassPage } from '@aether-app/components/app-shell';
import { BrandMark } from '@aether-app/components/brand-mark';
import { Eyebrow, InlineNotice } from '@aether-app/components/ae-ui';
import {
  EmptySlot, GlassSearch, LoadingRow, SegmentedTabs, type SegmentOption,
} from '@aether-app/components/ae-campaigns-geo-ui';
import { useCommsHealth, useCommsIndex } from '@aether-app/features/communications/use-communications';
import { asRecord, num, shortDate } from '@aether-app/pages/campaigns/campaign-model';
import {
  CHANNELS, channelLabel, communicationHref, eventSplit, matchesQuery, messageRows,
  type ChannelKey, type CommsMessageRow,
} from './communications-model';

type ChannelFilter = 'all' | ChannelKey;

function Figure({ value, label, color }: { readonly value: string; readonly label: string; readonly color?: string }) {
  return (
    <span className="flex flex-col">
      <span className="ae-mono text-[14px] font-medium" style={{ color: value === '—' ? 'var(--ae-faint)' : color }}>{value}</span>
      <span className="text-[10px]" style={{ color: 'var(--ae-faint)' }}>{label}</span>
    </span>
  );
}

/** Human-qualified vs suspected machine events for one message (counts, not a rate). */
export function EventSplitBar({ human, machine, className }: { readonly human: number; readonly machine: number; readonly className?: string }) {
  const total = human + machine;
  if (total <= 0) return null;
  return (
    <span
      className={`flex h-1.5 max-w-[240px] gap-0.5 overflow-hidden rounded-full ${className ?? ''}`}
      role="img"
      aria-label={`${human} human-qualified events, ${machine} suspected machine events`}
    >
      {human > 0 && <span style={{ flex: human, background: 'var(--ae-blue)' }} />}
      {machine > 0 && <span style={{ flex: machine, background: 'var(--ae-edge)' }} />}
    </span>
  );
}

function CommunicationCard({ row }: { readonly row: CommsMessageRow }) {
  const navigate = useNavigate();
  const timeCtx = useTimeContext();
  const split = eventSplit(row);
  const count = (v: number | null) => (v === null ? '—' : formatCount(v, timeCtx));
  const href = communicationHref(row);
  return (
    <article
      className="ae-glass-card flex cursor-pointer flex-wrap items-center gap-x-[18px] gap-y-3.5 rounded-[24px] px-5 py-4 transition-colors"
      data-testid="communication-card"
      data-channel={row.channel ?? 'unknown'}
      onClick={() => void navigate(href)}
    >
      <BrandMark token={row.provider ?? row.rawChannel ?? 'aether'} {...(row.provider ? { label: row.provider } : {})} size={42} />
      <span className="flex min-w-0 flex-col gap-1" style={{ flex: '1 1 240px' }}>
        <Link
          to={href}
          className="ae-focus truncate text-[17px] font-medium tracking-[-0.3px] hover:underline"
          onClick={e => e.stopPropagation()}
        >
          {row.name}
        </Link>
        <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          {channelLabel(row.channel, row.rawChannel)} · {row.provider ?? 'Source not reported'} · {row.campaignName}
          {row.sequenceStep !== null && ` · step ${row.sequenceStep}`}
        </span>
        {split && <EventSplitBar human={split.human} machine={split.machine} className="mt-1" />}
      </span>
      <span className="flex flex-wrap gap-4">
        <Figure value={count(row.delivered)} label="Delivered" />
        <Figure value={count(row.humanClicks)} label="Human clicks" color="var(--ae-blue)" />
        <Figure value={count(row.replies)} label="Replies" color="var(--ae-blue)" />
        <Figure value={count(row.bounces)} label="Bounces" color="var(--ae-amber)" />
      </span>
      <Link to={href} className="ae-focus text-[13px] hover:underline" style={{ color: 'var(--ae-blue-ink)' }} onClick={e => e.stopPropagation()}>
        Open →
      </Link>
    </article>
  );
}

function HealthLine() {
  const timeCtx = useTimeContext();
  const { data, error } = useCommsHealth();
  if (error) return <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Pipeline health unavailable</span>;
  if (!data) return null;
  const h = asRecord(data);
  const facts = num(h.communication_facts);
  const last = shortDate(h.last_event_at);
  if (facts === null) return null;
  return (
    <span className="inline-flex items-center gap-2 text-[13px]" style={{ color: 'var(--ae-mute)' }} data-testid="comms-health">
      <span aria-hidden="true" className="inline-block h-[7px] w-[7px] rounded-full" style={{ background: facts > 0 ? 'var(--ae-sage)' : 'var(--ae-faint)' }} />
      {formatCount(facts, timeCtx)} communication event{facts === 1 ? '' : 's'} observed
      {last ? ` · last ${last}` : ''}
    </span>
  );
}

function Legend() {
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]" style={{ color: 'var(--ae-mute)' }}>
      <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="inline-block h-2 w-2 rounded-sm" style={{ background: 'var(--ae-blue)' }} />human-qualified events</span>
      <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="inline-block h-2 w-2 rounded-sm" style={{ background: 'var(--ae-edge)' }} />suspected machine events</span>
      <span>Responses made through an agent are not reported by communications sources yet.</span>
    </span>
  );
}

export function CommunicationsPage() {
  const [query, setQuery] = useState('');
  const [channel, setChannel] = useState<ChannelFilter>('all');
  const { data, error } = useCommsIndex();
  const model = useMemo(() => messageRows(data), [data]);
  const q = query.trim().toLowerCase();
  const rows = model.rows.filter(r => (channel === 'all' || r.channel === channel) && matchesQuery(r, q));
  const channelCount = (key: ChannelKey) => model.rows.filter(r => r.channel === key).length;

  const options: SegmentOption<ChannelFilter>[] = [
    { value: 'all', label: 'All', testId: 'comms-channel-all' },
    ...CHANNELS.map(c => ({ value: c.key, label: c.label, testId: `comms-channel-${c.key}` })),
  ];

  let body: ReactNode;
  if (error) {
    body = (
      <InlineNotice tone="ember">
        Communications are unavailable right now. {error}
      </InlineNotice>
    );
  } else if (!data) {
    body = <LoadingRow label="Reading communications from connected sources" />;
  } else if (model.rows.length === 0 && model.failedCampaigns.length === 0) {
    body = (
      <EmptySlot testId="comms-empty">
        No communications yet. Messages appear here once a communications source (email, SMS, push or in-app) is
        connected and its campaigns are imported.{' '}
        <Link to="/settings/integrations" className="ae-focus font-medium hover:underline" style={{ color: 'var(--ae-blue-ink)' }}>
          Connect a communications source
        </Link>
      </EmptySlot>
    );
  } else if (rows.length === 0) {
    body = (
      <EmptySlot testId="comms-no-match">
        {q
          ? 'No communications match.'
          : `No ${channelLabel(channel === 'all' ? null : channel)} communications observed.${channel === 'agent' ? ' Agent-sent messages are not reported by any connected source yet.' : ''}`}
      </EmptySlot>
    );
  } else {
    body = (
      <div className="flex flex-col gap-3" data-testid="comms-list">
        {rows.map(r => <CommunicationCard key={r.key} row={r} />)}
      </div>
    );
  }

  return (
    <GlassPage>
      <div className="flex flex-col gap-4" data-testid="aether-communications">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <span className="flex flex-col gap-1">
            <h1 className="text-[clamp(26px,4.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Communications</h1>
            <span className="max-w-[560px] text-[14px] leading-[1.45]" style={{ color: 'var(--ae-mute)' }}>
              What was sent, who received it, and what people did next. Imported from the systems that send them.
            </span>
          </span>
          <GlassSearch value={query} onChange={setQuery} placeholder="Search communications" label="Search communications" />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <SegmentedTabs
            label="Channel"
            options={options.map(o => (o.value === 'all' || !data ? o : { ...o, label: <>{o.label}<span className="ae-mono ml-1.5 text-[11px]" style={{ opacity: 0.6 }}>{channelCount(o.value)}</span></> }))}
            value={channel}
            onChange={setChannel}
          />
          <HealthLine />
        </div>

        {model.failedCampaigns.length > 0 && (
          <InlineNotice tone="amber">
            Messages for {model.failedCampaigns.length} campaign{model.failedCampaigns.length === 1 ? '' : 's'} could not be read
            ({model.failedCampaigns.join(', ')}). They are missing from this list, not empty.
          </InlineNotice>
        )}
        {model.skippedCampaigns > 0 && (
          <InlineNotice tone="blue">
            Showing messages from the first {model.scannedCampaigns} communications campaigns. {model.skippedCampaigns} more are not listed here;{' '}
            <Link to="/campaigns?view=all" className="ae-focus font-medium hover:underline">open Campaigns</Link> to see them.
          </InlineNotice>
        )}

        <div className="ae-rise flex flex-col gap-3" key={channel} role="tabpanel">
          {body}
        </div>

        {model.rows.length > 0 && <Legend />}
        {data && model.rows.length > 0 && (
          <Eyebrow style={{ color: 'var(--ae-faint)' }}>
            {model.rows.length} message{model.rows.length === 1 ? '' : 's'} across {model.scannedCampaigns - model.failedCampaigns.length} campaign{model.scannedCampaigns - model.failedCampaigns.length === 1 ? '' : 's'}
          </Eyebrow>
        )}
      </div>
    </GlassPage>
  );
}
