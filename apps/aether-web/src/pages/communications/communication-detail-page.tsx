import { useMemo, useState, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { formatCount, useTimeContext } from '@aether/ui';
import { GlassPage } from '@aether-app/components/app-shell';
import { BrandMark } from '@aether-app/components/brand-mark';
import { ChoiceChip, Eyebrow, InlineNotice, MetricTile, TonePill } from '@aether-app/components/ae-ui';
import {
  EmptySlot, GlassSection, LoadingRow, SegmentedTabs, type SegmentOption,
} from '@aether-app/components/ae-campaigns-geo-ui';
import {
  useCommsCampaign, useCommsConversions, useCommsFunnel, useCommsJourneys, useCommsMessage, useCommsRecipients,
  type RecipientStage,
} from '@aether-app/features/communications/use-communications';
import { campaignSummary, statusTone, usd } from '@aether-app/pages/campaigns/campaign-model';
import {
  channelLabel, conversionSummary, fmtRate, funnelModel, journeyRows, messageDetail, rateStateLabel, recipientRows,
  type FunnelStep, type GovernedRate, type MessageDetail,
} from './communications-model';
import { EventSplitBar } from './communications-page';

type Tab = 'overview' | 'recipients' | 'response' | 'journeys' | 'outcomes';
const TABS: readonly SegmentOption<Tab>[] = [
  { value: 'overview', label: 'Overview' },
  { value: 'recipients', label: 'Recipients' },
  { value: 'response', label: 'Response' },
  { value: 'journeys', label: 'Journeys' },
  { value: 'outcomes', label: 'Outcomes' },
];

function isTab(v: string | null): v is Tab {
  return v !== null && TABS.some(t => t.value === v);
}

function useCount() {
  const timeCtx = useTimeContext();
  return (v: number | null) => (v === null ? '—' : formatCount(v, timeCtx));
}

function Unavailable({ what, error }: { readonly what: string; readonly error: string }) {
  return <InlineNotice tone="ember">{what} {error}</InlineNotice>;
}

function CampaignScope({ name }: { readonly name: string }) {
  return (
    <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
      Reported for the whole campaign <span style={{ color: 'var(--ae-ink)' }}>{name}</span>, not this message alone.
    </span>
  );
}

// ── Overview ─────────────────────────────────────────────────────────────────

/** The message as Aether retained it, framed for its channel. Only the redacted subject is kept. */
function MessageReplay({ m }: { readonly m: MessageDetail }) {
  const subject = m.subject ?? m.name;
  const from = m.provider ? `Sent from ${m.provider}` : 'Source not reported';
  const bodyNote = (
    <span className="text-[12px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>
      The message body stays in {m.provider ?? 'the sending system'}. Aether keeps the redacted subject and identifiers only.
    </span>
  );
  const meta = [
    m.template ? `template ${m.template}` : null,
    m.variant ? `variant ${m.variant}` : null,
    m.category,
  ].filter(Boolean).join(' · ');

  let frame: ReactNode;
  if (m.channel === 'sms') {
    frame = (
      <div className="flex flex-col items-start gap-1.5 rounded-[18px] p-4" style={{ background: 'var(--ae-edge-soft)' }} data-replay="sms">
        <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{from}</span>
        <span className="max-w-[300px] rounded-[16px_16px_16px_4px] px-3.5 py-2.5 text-[13px] leading-relaxed" style={{ background: 'var(--ae-blue-tint)' }}>{subject}</span>
        {bodyNote}
      </div>
    );
  } else if (m.channel === 'push') {
    frame = (
      <div className="flex items-start gap-2.5 rounded-[18px] border px-3.5 py-3" style={{ background: 'var(--ae-card)', borderColor: 'var(--ae-edge-soft)' }} data-replay="push">
        {m.provider && <BrandMark token={m.provider} size={34} />}
        <span className="flex flex-col gap-0.5">
          <span className="text-[13px] font-medium">{subject}</span>
          {bodyNote}
        </span>
      </div>
    );
  } else if (m.channel === 'in_app') {
    frame = (
      <div className="flex flex-col gap-2 rounded-[18px] border p-4" style={{ background: 'var(--ae-blue-tint)', borderColor: 'var(--ae-edge-soft)' }} data-replay="in_app">
        <span className="text-[15px] font-medium">{subject}</span>
        {bodyNote}
      </div>
    );
  } else if (m.channel === 'agent') {
    frame = (
      <div className="flex flex-col gap-1.5 rounded-[18px] border p-3.5" style={{ borderColor: 'var(--ae-violet)' }} data-replay="agent">
        <span className="ae-mono text-[12px] font-medium" style={{ color: 'var(--ae-violet)' }}>{from}</span>
        <span className="text-[13px] leading-relaxed">{subject}</span>
        {bodyNote}
      </div>
    );
  } else {
    frame = (
      <div className="flex flex-col overflow-hidden rounded-[16px] border" style={{ background: 'var(--ae-card)', borderColor: 'var(--ae-edge-soft)' }} data-replay="email">
        <span className="flex items-center gap-2 border-b px-3.5 py-2.5 text-[11px]" style={{ borderColor: 'var(--ae-edge-soft)', color: 'var(--ae-mute)' }}>
          {m.provider && <BrandMark token={m.provider} size={18} />}
          {from}
        </span>
        <span className="px-4 pb-1 pt-3.5 text-[15px] font-medium">{subject}</span>
        <span className="px-4 pb-4">{bodyNote}</span>
      </div>
    );
  }
  return (
    <GlassSection testId="comms-replay">
      <Eyebrow>What was sent</Eyebrow>
      {frame}
      {meta && <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-faint)' }}>{meta}</span>}
    </GlassSection>
  );
}

interface NextStep {
  readonly label: string;
  readonly value: number;
  readonly depth: number;
  readonly color: string;
  readonly note: string;
}

/** Branching view of what was observed after delivery, from the message's own counts. */
function WhatHappenedNext({ m }: { readonly m: MessageDetail }) {
  const count = useCount();
  const [selected, setSelected] = useState(0);
  const s = m.stats;
  const steps: NextStep[] = ([
    s.delivered !== null && { label: 'Delivered', value: s.delivered, depth: 0, color: 'var(--ae-mute)', note: 'Distinct recipients the provider confirmed delivery to.' },
    s.bounces !== null && { label: 'Bounced', value: s.bounces, depth: 1, color: 'var(--ae-amber)', note: 'Bounce events reported by the provider for this message.' },
    s.humanClicks !== null && { label: 'Clicked through (human)', value: s.humanClicks, depth: 1, color: 'var(--ae-blue)', note: 'Clicks left after removing link scanners and other suspected machine activity.' },
    s.replies !== null && { label: 'Replied', value: s.replies, depth: 2, color: 'var(--ae-blue)', note: 'Replies, excluding automated responses such as out-of-office messages.' },
    s.machineEvents !== null && { label: 'Suspected machine activity', value: s.machineEvents, depth: 1, color: 'var(--ae-faint)', note: 'Events from security scanners or image proxies. They are excluded from human-qualified counts.' },
  ] as const).filter((x): x is NextStep => Boolean(x) && (x as NextStep).value > 0);
  const max = Math.max(1, ...steps.map(x => x.value));
  const sel = steps[Math.min(selected, steps.length - 1)];

  return (
    <GlassSection testId="comms-next">
      <Eyebrow>What happened next</Eyebrow>
      {steps.length === 0 ? (
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Nothing observed for this message yet.</span>
      ) : (
        <>
          <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>Counts observed for this message. Select a step.</span>
          <div className="flex flex-col gap-0.5">
            {steps.map((x, i) => (
              <button
                key={x.label}
                type="button"
                aria-pressed={i === selected}
                onClick={() => setSelected(i)}
                className="ae-focus flex items-center gap-2.5 rounded-xl py-1.5 pr-2 text-left transition-colors"
                style={{ paddingLeft: 8 + x.depth * 20, background: i === selected ? 'var(--ae-blue-tint)' : 'transparent' }}
              >
                <span aria-hidden="true" className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: x.color }} />
                <span className="min-w-0 flex-1 text-[13px]">{x.label}</span>
                <span className="block h-[5px] w-[70px] shrink-0 overflow-hidden rounded-full" style={{ background: 'var(--ae-edge-soft)' }}>
                  <span className="block h-full" style={{ width: `${(x.value / max) * 100}%`, background: x.color }} />
                </span>
                <span className="ae-mono w-[60px] text-right text-[12px]" style={{ color: 'var(--ae-mute)' }}>{count(x.value)}</span>
              </button>
            ))}
          </div>
          {sel && <span className="text-[12px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>{sel.note}</span>}
        </>
      )}
    </GlassSection>
  );
}

function OverviewTab({ m }: { readonly m: MessageDetail }) {
  const count = useCount();
  const s = m.stats;
  const split = s.totalEvents !== null && s.machineEvents !== null && s.totalEvents > 0
    ? { human: Math.max(0, s.totalEvents - s.machineEvents), machine: Math.min(s.machineEvents, s.totalEvents) }
    : null;
  return (
    <div className="flex flex-col gap-3.5">
      <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(150px, 100%), 1fr))' }} data-testid="comms-kpis">
        <MetricTile label="Delivered" value={count(s.delivered)} sub={m.firstSeen ? `first seen ${m.firstSeen}` : 'first seen not reported'} />
        <MetricTile label="Human clicks" value={count(s.humanClicks)} tone="blue" sub="scanners excluded" />
        <MetricTile label="Replies" value={count(s.replies)} tone="blue" sub="automated replies excluded" />
        <MetricTile label="Bounces" value={count(s.bounces)} tone="amber" />
        <MetricTile label="Machine events" value={count(s.machineEvents)} sub={split ? <EventSplitBar human={split.human} machine={split.machine} className="mt-1" /> : 'of all events'} />
      </div>
      <div className="grid items-start gap-3.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(320px, 100%), 1fr))' }}>
        <MessageReplay m={m} />
        <WhatHappenedNext m={m} />
      </div>
      {m.links.length > 0 && (
        <GlassSection testId="comms-links">
          <Eyebrow>Links in this message</Eyebrow>
          {m.links.map(l => (
            <div key={l.id} className="flex flex-wrap items-center justify-between gap-2 border-t pt-2 text-[12px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>
              <code className="ae-mono min-w-0 break-all" style={{ color: 'var(--ae-mute)' }}>{l.id}</code>
              <span className="ae-mono shrink-0">
                {count(l.humanClicks)} human clicks{l.uniqueClickers !== null ? ` · ${count(l.uniqueClickers)} people` : ''}
              </span>
            </div>
          ))}
        </GlassSection>
      )}
    </div>
  );
}

// ── Response ─────────────────────────────────────────────────────────────────

function RateValue({ rate }: { readonly rate: GovernedRate | null }) {
  if (!rate) return null;
  if (rate.value === null) {
    return <span className="text-[11px]" style={{ color: 'var(--ae-amber)' }} data-value-state={rate.state}>{rateStateLabel(rate.state)}</span>;
  }
  return <span className="ae-mono text-[13px]" data-value-state={rate.state}>{fmtRate(rate.value)}</span>;
}

function RateDetail({ step }: { readonly step: FunnelStep }) {
  const count = useCount();
  const r = step.rate;
  return (
    <GlassSection testId="comms-step-detail">
      <Eyebrow>{step.label}{r?.value != null ? ` · ${fmtRate(r.value)}` : ''}</Eyebrow>
      <span className="text-[13px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>{step.note}</span>
      {r && (
        <span className="flex flex-col gap-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          <span>State: <span style={{ color: 'var(--ae-ink)' }}>{rateStateLabel(r.state)}</span></span>
          {r.sampleSize !== null && (
            <span>
              Sample: <span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{count(r.sampleSize)}</span> delivered
              {r.minRequired !== null ? ` (minimum ${count(r.minRequired)})` : ''}
            </span>
          )}
          {r.value !== null && r.lower !== null && r.upper !== null && (
            <span>
              95% interval{r.method ? ` (${r.method})` : ''}: <span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{fmtRate(r.lower)} to {fmtRate(r.upper)}</span>
            </span>
          )}
        </span>
      )}
    </GlassSection>
  );
}

function ResponseTab({ campaignId, campaignName }: { readonly campaignId: string; readonly campaignName: string }) {
  const count = useCount();
  const { data, error } = useCommsFunnel(campaignId);
  const [selected, setSelected] = useState(1);
  const model = useMemo(() => funnelModel(data), [data]);
  if (error) return <Unavailable what="The response ladder is unavailable right now." error={error} />;
  if (!data) return <LoadingRow label="Reading the response ladder" />;
  const base = Math.max(1, ...model.steps.map(s => Math.max(s.human ?? 0, s.reported ?? 0)));
  const nothing = model.steps.every(s => !s.human && !s.reported);
  if (nothing) return <EmptySlot testId="comms-response-empty">No sends or deliveries have been reported for this campaign yet.</EmptySlot>;
  const sel = model.steps[Math.min(selected, model.steps.length - 1)];
  const withheld = model.steps.filter(s => s.rate && s.rate.value === null);

  return (
    <div className="flex flex-col gap-3">
      <CampaignScope name={campaignName} />
      {withheld.length > 0 && (
        <InlineNotice tone="amber">
          Rates are withheld until the governed minimum sample is met. Counts are still shown.
        </InlineNotice>
      )}
      <GlassSection testId="comms-ladder">
        <Eyebrow>Response ladder · select a step</Eyebrow>
        {model.steps.map((s, i) => {
          const human = s.human ?? 0;
          const machine = s.reported !== null && s.human !== null ? Math.max(0, s.reported - s.human) : 0;
          const width = (Math.max(human, s.reported ?? 0) / base) * 100;
          return (
            <button
              key={s.key}
              type="button"
              aria-pressed={i === selected}
              onClick={() => setSelected(i)}
              className="ae-focus -mx-2.5 flex flex-col gap-1 rounded-xl px-2.5 py-1.5 text-left transition-colors"
              style={{ background: i === selected ? 'var(--ae-blue-tint)' : 'transparent' }}
              data-step={s.key}
            >
              <span className="flex w-full items-center justify-between gap-2 text-[13px]">
                <span>{s.label}</span>
                <span className="flex items-center gap-2">
                  <RateValue rate={s.rate} />
                  <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-faint)' }}>{count(s.human)}</span>
                </span>
              </span>
              <span className="flex h-[9px] gap-0.5" style={{ width: `${Math.max(1, width)}%`, minWidth: 4 }}>
                {human > 0 && <span className="rounded-l" style={{ flex: human, background: 'var(--ae-blue)' }} />}
                {machine > 0 && <span className="rounded-r" style={{ flex: machine, background: 'var(--ae-edge)' }} />}
              </span>
            </button>
          );
        })}
        <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>
          Blue: human-qualified. Grey: the extra events the provider reports, mostly scanners and proxies.
          Return visits, agent sessions and purchases are on the Journeys and Outcomes tabs.
        </span>
      </GlassSection>
      {sel && <RateDetail step={sel} />}
    </div>
  );
}

// ── Recipients ───────────────────────────────────────────────────────────────

const STAGES: readonly { readonly value: RecipientStage; readonly label: string }[] = [
  { value: 'all', label: 'Everyone' },
  { value: 'delivered', label: 'Delivered only' },
  { value: 'engaged', label: 'Engaged' },
  { value: 'replied', label: 'Replied' },
];

function initials(name: string): string {
  return name.split(/[\s._@-]+/).filter(Boolean).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('') || '?';
}

function RecipientsTab({ campaignId, campaignName }: { readonly campaignId: string; readonly campaignName: string }) {
  const count = useCount();
  const [stage, setStage] = useState<RecipientStage>('all');
  const everyone = useCommsRecipients(campaignId, 'all');
  const current = useCommsRecipients(campaignId, stage, stage !== 'all');
  const read = stage === 'all' ? everyone : current;
  const counts = recipientRows(everyone.data).stageCounts;
  const { rows } = recipientRows(read.data);

  let body: ReactNode;
  if (read.error) body = <Unavailable what="Recipients are unavailable right now." error={read.error} />;
  else if (!read.data) body = <LoadingRow label="Reading recipients" />;
  else if (rows.length === 0) body = <EmptySlot testId="comms-recipients-empty">{stage === 'all' ? 'No recipients observed for this campaign yet.' : 'No recipients at this stage.'}</EmptySlot>;
  else {
    body = (
      <GlassSection className="!gap-0 !py-2" testId="comms-recipients">
        {rows.map((r, i) => {
          const content = (
            <>
              <span className="flex h-[30px] w-[30px] items-center justify-center rounded-full border text-[11px] font-medium" style={{ borderColor: 'var(--ae-edge)', background: 'var(--ae-edge-soft)' }} aria-hidden="true">
                {initials(r.display)}
              </span>
              <span className="flex min-w-0 flex-col leading-tight">
                <span className="truncate text-[14px]">{r.display}</span>
                <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{r.entityId ? 'resolved profile' : 'unresolved: no profile yet'}</span>
              </span>
              <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                {count(r.humanClicks)} clicks · {count(r.replies)} replies
              </span>
              <span className="flex flex-wrap justify-end gap-1">
                <TonePill tone={r.stage === 'replied' || r.stage === 'engaged' ? 'blue' : 'mute'}>{r.stage}</TonePill>
                {r.flags.map(f => <TonePill key={f} tone={f === 'bounced' || f === 'complained' ? 'ember' : 'amber'}>{f}</TonePill>)}
              </span>
            </>
          );
          const cls = 'grid items-center gap-3 py-2.5';
          const style = { gridTemplateColumns: '30px minmax(0,1.3fr) minmax(0,1fr) auto', borderTop: i ? '1px solid var(--ae-edge-soft)' : 'none' };
          return r.entityId ? (
            <Link key={r.key} to={`/users/${encodeURIComponent(r.entityId)}`} className={`ae-focus ${cls} hover:opacity-80`} style={style} data-testid="comms-recipient">
              {content}
            </Link>
          ) : (
            <div key={r.key} className={cls} style={style} data-testid="comms-recipient">{content}</div>
          );
        })}
      </GlassSection>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <CampaignScope name={campaignName} />
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Recipient stage">
        {STAGES.map(s => (
          <ChoiceChip key={s.value} size="sm" selected={stage === s.value} onClick={() => setStage(s.value)}>
            {s.label}{s.value !== 'all' && counts[s.value] !== undefined ? ` · ${counts[s.value]}` : ''}
          </ChoiceChip>
        ))}
      </div>
      {body}
    </div>
  );
}

// ── Journeys ─────────────────────────────────────────────────────────────────

function JourneysTab({ campaignId, campaignName }: { readonly campaignId: string; readonly campaignName: string }) {
  const { data, error } = useCommsJourneys(campaignId);
  if (error) return <Unavailable what="Journeys are unavailable right now." error={error} />;
  if (!data) return <LoadingRow label="Reading journeys" />;
  const { rows, hasMore } = journeyRows(data);
  if (rows.length === 0) return <EmptySlot testId="comms-journeys-empty">No journeys include this campaign yet.</EmptySlot>;
  return (
    <div className="flex flex-col gap-2.5" data-testid="comms-journeys">
      <CampaignScope name={campaignName} />
      {rows.map(j => {
        const inner = (
          <>
            <span className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex flex-wrap items-center gap-1.5 text-[13px]">
                <TonePill tone="blue">{campaignName}</TonePill>
                <span style={{ color: 'var(--ae-faint)' }}>→</span>
                <span>{j.stages !== null ? `${j.stages} touchpoint${j.stages === 1 ? '' : 's'}` : 'touchpoints not reported'}</span>
                <span style={{ color: 'var(--ae-faint)' }}>→</span>
                <TonePill tone={j.converted ? 'sage' : 'mute'}>{j.converted ? 'Converted' : 'Not converted'}</TonePill>
              </span>
            </span>
            <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              {j.started ? `Started ${j.started}` : 'Start not reported'}
              {j.completed ? ` · ended ${j.completed}` : ''}
              {j.profileId ? ' · Open journey →' : ' · no profile linked'}
            </span>
          </>
        );
        return j.profileId ? (
          <Link
            key={j.id}
            to={`/users/${encodeURIComponent(j.profileId)}/journey`}
            className="ae-glass-card ae-focus flex flex-col gap-2 rounded-[22px] px-[18px] py-3.5 hover:opacity-90"
            data-testid="comms-journey"
          >
            {inner}
          </Link>
        ) : (
          <div key={j.id} className="ae-glass-card flex flex-col gap-2 rounded-[22px] px-[18px] py-3.5" data-testid="comms-journey">{inner}</div>
        );
      })}
      {hasMore && <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Showing the first {rows.length} journeys.</span>}
    </div>
  );
}

// ── Outcomes ─────────────────────────────────────────────────────────────────

function OutcomeRow({ label, value, color }: { readonly label: ReactNode; readonly value: string; readonly color?: string }) {
  return (
    <div className="flex items-center justify-between gap-2.5 border-t py-3 text-[14px] first:border-t-0" style={{ borderColor: 'var(--ae-edge-soft)' }}>
      <span>{label}</span>
      <span className="ae-mono text-[13px] font-medium" style={{ color: value === '—' ? 'var(--ae-faint)' : color }}>{value}</span>
    </div>
  );
}

function OutcomesTab({ campaignId, campaignName }: { readonly campaignId: string; readonly campaignName: string }) {
  const count = useCount();
  const conversions = useCommsConversions(campaignId);
  const funnel = useCommsFunnel(campaignId);
  const conv = useMemo(() => conversionSummary(conversions.data), [conversions.data]);
  const delivery = useMemo(() => funnelModel(funnel.data).delivery, [funnel.data]);

  return (
    <div className="flex flex-col gap-3">
      <CampaignScope name={campaignName} />
      <GlassSection testId="comms-outcomes">
        <Eyebrow>Conversions</Eyebrow>
        {conversions.error ? (
          <Unavailable what="Conversions are unavailable right now." error={conversions.error} />
        ) : !conversions.data ? (
          <LoadingRow label="Reading conversions" />
        ) : conv.count === 0 ? (
          <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No conversions attributed to this campaign yet.</span>
        ) : (
          <>
            <OutcomeRow label="Attributed conversions" value={`${count(conv.count)}${conv.hasMore ? '+' : ''}`} color="var(--ae-sage)" />
            <OutcomeRow label="Gross value" value={usd(conv.gross)} color="var(--ae-sage)" />
            {conv.byType.map(t => <OutcomeRow key={t.type} label={<span style={{ color: 'var(--ae-mute)' }}>{t.type}</span>} value={count(t.count)} />)}
          </>
        )}
      </GlassSection>
      <GlassSection testId="comms-delivery-outcomes">
        <Eyebrow>Delivery outcomes</Eyebrow>
        {funnel.error ? (
          <Unavailable what="Delivery outcomes are unavailable right now." error={funnel.error} />
        ) : !funnel.data ? (
          <LoadingRow label="Reading delivery outcomes" />
        ) : (
          <>
            <OutcomeRow label="Unsubscribed" value={count(delivery.unsubscribes ?? null)} color="var(--ae-amber)" />
            <OutcomeRow label="Complaints" value={count(delivery.complaints ?? null)} color="var(--ae-ember)" />
            <OutcomeRow label="Hard bounces" value={count(delivery.hard_bounces ?? null)} color="var(--ae-amber)" />
            <OutcomeRow label="Soft bounces" value={count(delivery.soft_bounces ?? null)} />
            <OutcomeRow label="Suppressed" value={count(delivery.suppressions ?? null)} />
          </>
        )}
      </GlassSection>
      <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>
        Agent adoption after a communication is not reported by communications sources yet.
      </span>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function CommunicationDetailPage() {
  const params = useParams<{ campaignId: string; messageId: string }>();
  const campaignId = params.campaignId ?? '';
  const messageId = params.messageId ?? '';
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get('tab');
  const tab: Tab = isTab(rawTab) ? rawTab : 'overview';
  const campaign = useCommsCampaign(campaignId);
  const message = useCommsMessage(campaignId, messageId);
  const c = campaign.data ? campaignSummary(campaign.data) : null;
  const campaignName = c?.name ?? campaignId;
  const m = useMemo(() => (message.data ? messageDetail(message.data, messageId, campaign.data) : null), [message.data, messageId, campaign.data]);

  function setTab(next: Tab) {
    setSearchParams(prev => {
      const p = new URLSearchParams(prev);
      if (next === 'overview') p.delete('tab');
      else p.set('tab', next);
      return p;
    }, { replace: true });
  }

  const title = m?.name ?? messageId;
  const pill = 'ae-focus rounded-full border px-3.5 py-[7px] text-[12px] hover:opacity-80';
  const pillStyle = { background: 'var(--ae-glass-card)', borderColor: 'var(--ae-edge)' };

  return (
    <GlassPage>
      <div className="flex flex-col gap-3.5" data-testid="aether-communication-detail">
        <nav className="text-[13px]" style={{ color: 'var(--ae-mute)' }} aria-label="Breadcrumb">
          <Link to="/communications" className="ae-focus hover:underline">Communications</Link>
          {' / '}
          <span style={{ color: 'var(--ae-ink)' }}>{title}</span>
        </nav>

        {message.error ? (
          <Unavailable what="This communication is unavailable right now." error={message.error} />
        ) : !m ? (
          <LoadingRow label="Reading this communication" />
        ) : (
          <>
            <section className="ae-glass-card flex min-w-0 flex-wrap items-center justify-between gap-3.5 rounded-[26px] p-[clamp(14px,2.6vw,22px)]" data-testid="comms-header">
              <span className="flex min-w-0 items-center gap-3.5">
                <BrandMark token={m.provider ?? m.rawChannel ?? 'aether'} {...(m.provider ? { label: m.provider } : {})} size={50} />
                <span className="flex min-w-0 flex-col gap-1">
                  <h1 className="text-[clamp(20px,4.4vw,28px)] font-medium leading-[1.1] tracking-[-0.56px]">{m.name}</h1>
                  <span className="flex flex-wrap items-center gap-1.5 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                    {channelLabel(m.channel, m.rawChannel)} · {m.provider ? `sent from ${m.provider}` : 'source not reported'}
                    {m.firstSeen ? ` · first seen ${m.firstSeen}` : ''}
                    {m.sequenceStep !== null ? ` · step ${m.sequenceStep}` : ''}
                    <TonePill tone={statusTone(m.status)}>{m.status}</TonePill>
                  </span>
                </span>
              </span>
              <span className="flex flex-wrap gap-2">
                {campaignId && (
                  <Link to={`/campaigns/${encodeURIComponent(campaignId)}?tab=messages`} className={pill} style={pillStyle}>
                    Campaign: {campaignName} →
                  </Link>
                )}
                <Link to="/explore" className={pill} style={pillStyle}>Open in Explore →</Link>
              </span>
            </section>

            {campaign.error && (
              <InlineNotice tone="amber">The campaign record is unavailable, so campaign details are limited. {campaign.error}</InlineNotice>
            )}

            <SegmentedTabs label="Communication views" options={TABS} value={tab} onChange={setTab} className="self-start" />

            <div className="ae-rise flex flex-col gap-3.5" key={tab} role="tabpanel">
              {tab === 'overview' && <OverviewTab m={m} />}
              {tab === 'recipients' && <RecipientsTab campaignId={campaignId} campaignName={campaignName} />}
              {tab === 'response' && <ResponseTab campaignId={campaignId} campaignName={campaignName} />}
              {tab === 'journeys' && <JourneysTab campaignId={campaignId} campaignName={campaignName} />}
              {tab === 'outcomes' && <OutcomesTab campaignId={campaignId} campaignName={campaignName} />}
            </div>
          </>
        )}
      </div>
    </GlassPage>
  );
}

