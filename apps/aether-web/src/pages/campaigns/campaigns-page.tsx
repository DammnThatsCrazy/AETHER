import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  DataTable, ErrorState, Icon, LoadingState,
  formatCount, useTimeContext,
} from '@aether/ui';
import { TruthBanner, encodeExplorationContext } from '@aether/ui/exploration';
import { GlassPage } from '@aether-app/components/app-shell';
import { BrandMark } from '@aether-app/components/brand-mark';
import {
  Eyebrow, InlineNotice, LinkButton, MetricTile, PrimaryButton, SecondaryButton, TonePill, toneColor, type Tone,
} from '@aether-app/components/ae-ui';
import {
  EmptySlot, GlassSearch, GlassSection, LoadingRow, SegmentedTabs, ShareRow, type SegmentOption,
} from '@aether-app/components/ae-campaigns-geo-ui';
import { useCampaigns, usePlatformOverview, useAutomationInsights } from '@aether-app/features/campaigns/use-campaigns';
import { useCampaignQuality } from '@aether-app/features/campaigns/use-campaign-quality';
import { useIgnoreReview, useMappingReviews, useResolveReview } from '@aether-app/features/campaigns/use-mapping-review';
import {
  useCampaignExploration,
  type CampaignExplorationRow,
} from '@aether-app/features/campaigns/use-campaign-exploration';
import {
  asList, asRecord, campaignSummary, compact, num, pct, statusTone, text, usd,
  type AnyRecord, type CampaignSummary,
} from './campaign-model';

// ── Views ─────────────────────────────────────────────────────────────────────

type View = 'active' | 'paused' | 'ended' | 'all' | 'review' | 'attribution' | 'exploration';

const STATUS_VIEWS: Partial<Record<View, string>> = { active: 'active', paused: 'paused', ended: 'ended' };
const VIEWS: readonly View[] = ['active', 'paused', 'ended', 'all', 'review', 'attribution', 'exploration'];

function isView(v: string | null): v is View {
  return v !== null && (VIEWS as readonly string[]).includes(v);
}

function errorText(error: unknown): string {
  if (!error) return '';
  return error instanceof Error ? error.message : String(error);
}

// ── Campaign card ─────────────────────────────────────────────────────────────

function CardFigure({ value, label, tone }: { value: string; label: string; tone?: Tone }) {
  return (
    <span className="flex flex-col">
      <span
        className="ae-mono text-[15px] font-medium"
        style={{ color: tone === 'sage' ? 'var(--ae-sage)' : value === '—' ? 'var(--ae-faint)' : undefined }}
      >
        {value}
      </span>
      <span className="text-[10px]" style={{ color: 'var(--ae-faint)' }}>{label}</span>
    </span>
  );
}

function CampaignDetails({ c }: { c: CampaignSummary }) {
  const timeCtx = useTimeContext();
  const entered = c.reached ?? 0;
  const share = (v: number | null) => (entered > 0 && v !== null ? (v / entered) * 100 : null);
  return (
    <div className="flex flex-col gap-4 border-t pt-3.5" style={{ borderColor: 'var(--ae-edge)' }} data-testid="campaign-details">
      {entered > 0 && (
        <div className="flex flex-col gap-2">
          <Eyebrow>Funnel</Eyebrow>
          <ShareRow label="Entered" value={formatCount(entered, timeCtx)} share={100} />
          {c.clicked !== null && c.clicked > 0 && <ShareRow label="Clicked" value={formatCount(c.clicked, timeCtx)} share={share(c.clicked)} />}
          <ShareRow label="Converted" value={formatCount(c.converted ?? 0, timeCtx)} share={share(c.converted ?? 0)} color="var(--ae-sage)" />
          {c.dropped !== null && c.dropped > 0 && <ShareRow label="Dropped off" value={formatCount(c.dropped, timeCtx)} share={share(c.dropped)} color="var(--ae-amber)" />}
          {c.abandoned !== null && c.abandoned > 0 && <ShareRow label="Abandoned" value={formatCount(c.abandoned, timeCtx)} share={share(c.abandoned)} color="var(--ae-ember)" />}
          {(c.dropOffRate !== null || c.abandonmentRate !== null) && (
            <span className="flex flex-wrap gap-4 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              {c.dropOffRate !== null && <span>Drop-off rate <span className="ae-mono" style={{ color: 'var(--ae-amber)' }}>{pct(c.dropOffRate)}</span></span>}
              {c.abandonmentRate !== null && <span>Abandonment <span className="ae-mono" style={{ color: 'var(--ae-ember)' }}>{pct(c.abandonmentRate)}</span></span>}
            </span>
          )}
        </div>
      )}

      {c.channels.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <Eyebrow>Top channels</Eyebrow>
          {c.channels.slice(0, 6).map((ch, i) => {
            const label = text(ch.channel ?? ch.name);
            const source = ch.source ? String(ch.source) : null;
            return (
              <div key={`${label}-${source ?? ''}-${i}`} className="flex flex-wrap items-center justify-between gap-2 border-t pt-1.5 text-[12px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>
                <span className="flex items-center gap-2">
                  {source && <BrandMark token={source} label={source} size={20} markSize={12} />}
                  <span>{label}</span>
                  {source && <span style={{ color: 'var(--ae-mute)' }}>{source}</span>}
                </span>
                <span className="ae-mono flex gap-4" style={{ color: 'var(--ae-mute)' }}>
                  {num(ch.conversions) !== null && <span style={{ color: 'var(--ae-ink)' }}>{formatCount(num(ch.conversions) ?? 0, timeCtx)} conv.</span>}
                  {num(ch.revenue_usd) !== null && <span style={{ color: 'var(--ae-sage)' }}>{usd(num(ch.revenue_usd))}</span>}
                  {num(ch.conversion_rate) !== null && <span>{pct(num(ch.conversion_rate))}</span>}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {c.revenue !== null && (
        <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))' }}>
          <MetricTile label="Revenue" value={usd(c.revenue)} />
          {c.cost !== null && <MetricTile label="Cost" value={usd(c.cost)} />}
          {c.roas !== null && <MetricTile label="ROAS" value={`${c.roas.toFixed(2)}x`} />}
        </div>
      )}

      {entered === 0 && c.channels.length === 0 && c.revenue === null && (
        <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          The source has not reported funnel, channel or revenue figures for this campaign yet.
        </span>
      )}
    </div>
  );
}

function CampaignCard({ campaign }: { campaign: CampaignSummary }) {
  const navigate = useNavigate();
  const timeCtx = useTimeContext();
  const [open, setOpen] = useState(false);
  const c = campaign;
  const openCampaign = () => { if (c.id) void navigate(`/campaigns/${encodeURIComponent(c.id)}`); };
  const dates = c.start ? `Started ${c.start}${c.end ? ` · ends ${c.end}` : ''}` : c.end ? `Ends ${c.end}` : 'No dates reported by the source';

  return (
    <article
      className="ae-glass-card flex flex-col gap-3.5 rounded-[24px] px-5 py-4"
      data-testid="campaign-card"
      data-campaign-id={c.id}
    >
      <div className="flex flex-wrap items-center gap-x-[18px] gap-y-3.5">
        <div className="flex min-w-0 flex-col gap-1.5" style={{ flex: '1 1 300px' }}>
          <span className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={openCampaign}
              disabled={!c.id}
              className="ae-focus truncate text-left text-[18px] font-medium tracking-[-0.3px] hover:underline"
            >
              {c.name}
            </button>
            <TonePill tone={statusTone(c.status)}>{c.status}</TonePill>
            {c.type && <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>type: {c.type}</span>}
          </span>
          <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{dates}</span>
          <span className="flex flex-wrap items-center gap-1.5">
            {c.platform && (
              <span className="inline-flex items-center gap-1.5 rounded-full border py-0.5 pl-1 pr-2.5 text-[11px]" style={{ borderColor: 'var(--ae-edge-soft)', background: 'var(--ae-glass-card)' }}>
                <BrandMark token={c.platform} label={c.platform} size={16} markSize={11} shape="round" />
                {c.platform}
              </span>
            )}
            {c.channel && (
              <span className="rounded-full border px-2.5 py-0.5 text-[11px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>{c.channel}</span>
            )}
            {c.mappingQuality && (
              <span className="text-[11px]" style={{ color: c.mappingQuality === 'high' ? 'var(--ae-sage)' : 'var(--ae-mute)' }}>
                mapping {c.mappingQuality}
              </span>
            )}
            <code className="ae-mono text-[11px]" style={{ color: 'var(--ae-faint)' }}>{c.id}</code>
          </span>
        </div>
        <div className="flex flex-wrap gap-[18px]">
          <CardFigure value={c.reached !== null ? formatCount(c.reached, timeCtx) : '—'} label="reached" />
          <CardFigure value={c.converted !== null ? formatCount(c.converted, timeCtx) : '—'} label="conversions" />
          <CardFigure value={c.conversionRate !== null ? pct(c.conversionRate) : '—'} label="conv. rate" />
          <CardFigure value={usd(c.revenue)} label="attributed revenue" {...(c.revenue !== null ? { tone: 'sage' as Tone } : {})} />
          {c.fraudBlocked !== null && c.fraudBlocked > 0 && (
            <span className="flex flex-col">
              <span className="ae-mono text-[15px] font-medium" style={{ color: 'var(--ae-ember)' }}>{formatCount(c.fraudBlocked, timeCtx)}</span>
              <span className="text-[10px]" style={{ color: 'var(--ae-faint)' }}>fraud blocked</span>
            </span>
          )}
        </div>
        <span className="flex items-center gap-3">
          <LinkButton onClick={() => setOpen(o => !o)} tone="mute">{open ? 'Hide details' : 'Details'}</LinkButton>
          {c.id && <LinkButton onClick={openCampaign}>Open →</LinkButton>}
        </span>
      </div>
      {open && <CampaignDetails c={c} />}
    </article>
  );
}

// ── Campaign list ─────────────────────────────────────────────────────────────

function CampaignList({ status, query }: { status?: string; query: string }) {
  const navigate = useNavigate();
  const { data, isLoading, error } = useCampaigns(status ? { status, limit: 50 } : { limit: 50 });
  const campaigns = useMemo(() => {
    const d = asRecord(data);
    return asList(d.campaigns ?? data).map(campaignSummary);
  }, [data]);
  const q = query.trim().toLowerCase();
  const rows = q
    ? campaigns.filter(c => [c.name, c.id, c.platform ?? '', c.channel ?? ''].some(v => v.toLowerCase().includes(q)))
    : campaigns;

  if (error) {
    return (
      <InlineNotice tone="ember">
        <span className="block font-medium">Failed to load campaigns</span>
        <span className="block">{errorText(error)}</span>
      </InlineNotice>
    );
  }
  if (isLoading && !data) return <LoadingRow label="Loading campaigns…" />;

  if (campaigns.length === 0) {
    return (
      <EmptySlot testId="campaigns-empty">
        <span className="block text-[14px] font-medium" style={{ color: 'var(--ae-ink)' }}>
          {status ? `No ${status} campaigns` : 'No campaigns'}
        </span>
        <span className="mt-1 block">
          {status
            ? `No ${status} campaigns found.`
            : 'Campaigns appear here once traffic and orders are attributed — connect a source to start building attribution.'}
        </span>
        {!status && (
          <span className="mt-3 inline-block">
            <PrimaryButton onClick={() => void navigate('/activation')}>Connect your first source</PrimaryButton>
          </span>
        )}
      </EmptySlot>
    );
  }

  if (rows.length === 0) {
    return <EmptySlot>No campaigns match “{query.trim()}”.</EmptySlot>;
  }

  return (
    <div className="flex flex-col gap-3" data-testid="campaign-list">
      {rows.map((c, i) => <CampaignCard key={c.id || i} campaign={c} />)}
    </div>
  );
}

// ── Review queue ──────────────────────────────────────────────────────────────

function evidenceChips(review: AnyRecord): { label: string; value: string }[] {
  const evidence = asRecord(review.evidence);
  return ([
    ['ext id', evidence.external_campaign_id],
    ['utm_id', evidence.utm_id],
    ['utm_campaign', evidence.utm_campaign],
    ['utm_source', evidence.utm_source],
    ['utm_medium', evidence.utm_medium],
  ] as const)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([label, v]) => ({ label, value: String(v) }));
}

function ReviewQueue() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useMappingReviews({ status: 'open', limit: 50 });
  const campaigns = useCampaigns({ limit: 50 });
  const raw = asRecord(data);
  const reviews = (Array.isArray(raw.items) ? raw.items : Array.isArray(data) ? data : []) as AnyRecord[];
  const names = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of asList(asRecord(campaigns.data).campaigns ?? campaigns.data).map(campaignSummary)) {
      if (c.id) map.set(c.id, c.name);
    }
    return map;
  }, [campaigns.data]);
  const openQueue = () => void navigate('/campaign-intelligence/mapping-review');

  return (
    <div className="flex flex-col gap-3" data-testid="campaign-review">
      <span className="max-w-[640px] text-[13px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>
        These source campaigns did not group cleanly. A source label or medium alone never decides a campaign’s identity, so a person confirms them.
      </span>
      {error && (
        <InlineNotice tone="ember">
          <span className="block font-medium">Review queue unavailable</span>
          <span className="block">{errorText(error)}</span>
        </InlineNotice>
      )}
      {!error && isLoading && !data && <LoadingRow label="Loading review items…" />}
      {!error && data !== undefined && data !== null && reviews.length === 0 && (
        <EmptySlot>The queue is clear. Every observed source campaign is grouped.</EmptySlot>
      )}
      {reviews.map((review, i) => (
        <ReviewCard
          key={text(review.review_id ?? review.id, String(i))}
          review={review}
          names={names}
          onOpenQueue={openQueue}
        />
      ))}
    </div>
  );
}

/** Review confidence, when the payload carries one (0–1 or 0–100). */
function reviewConfidence(review: AnyRecord): number | null {
  const value = num(review.confidence ?? asRecord(review.evidence).confidence);
  if (value === null) return null;
  return value <= 1 ? value * 100 : value;
}

/** Matching signals, when the payload carries them: `[{ label, matched }]` or plain labels. */
function matchingSignals(review: AnyRecord): { label: string; matched: boolean | null }[] {
  const list = review.matching_signals ?? review.signals ?? asRecord(review.evidence).matching_signals;
  if (!Array.isArray(list)) return [];
  return list.flatMap(item => {
    if (typeof item === 'string' && item.trim()) return [{ label: item, matched: null }];
    const r = asRecord(item);
    const label = r.label ?? r.name ?? r.signal;
    if (typeof label !== 'string' || !label.trim()) return [];
    return [{ label, matched: typeof r.matched === 'boolean' ? r.matched : typeof r.match === 'boolean' ? r.match : null }];
  });
}

function candidateIds(review: AnyRecord): string[] {
  const list = review.candidate_campaign_ids;
  return Array.isArray(list) ? list.map(String).filter(Boolean) : [];
}

function ReviewCard({ review, names, onOpenQueue }: {
  review: AnyRecord;
  names: ReadonlyMap<string, string>;
  onOpenQueue: () => void;
}) {
  const timeCtx = useTimeContext();
  const resolve = useResolveReview();
  const ignore = useIgnoreReview();
  const reviewId = text(review.review_id ?? review.id, '');
  const evidence = asRecord(review.evidence);
  const platform = evidence.platform ? String(evidence.platform) : null;
  const sourceLabel = evidence.utm_campaign ?? evidence.external_campaign_id;
  const observed = num(review.observed_count);
  const touchpoints = num(review.affected_touchpoints);
  // The platform chip already carries the source label; don't repeat it as an evidence chip.
  const chips = evidenceChips(review).filter(chip => !(platform && sourceLabel && chip.value === String(sourceLabel)));
  const confidence = reviewConfidence(review);
  const signals = matchingSignals(review);
  const candidates = candidateIds(review);
  const [picked, setPicked] = useState(candidates[0] ?? '');
  const busy = resolve.isLoading || ignore.isLoading;
  const proposed = candidates.map(id => names.get(id) ?? id);
  const failure = resolve.error ?? ignore.error;

  return (
    <article className="ae-glass-card flex flex-col gap-3 rounded-[24px] px-5 py-4" data-testid="review-item" data-review-id={reviewId}>
      <span className="flex flex-wrap items-start justify-between gap-2.5">
        <span className="flex min-w-0 flex-col gap-1.5">
          <span className="flex flex-wrap items-center gap-1.5">
            {platform && (
              <span className="inline-flex items-center gap-1.5 rounded-full border py-0.5 pl-1 pr-2.5 text-[12px]" style={{ borderColor: 'var(--ae-edge-soft)', background: 'var(--ae-glass-card)' }}>
                <BrandMark token={platform} label={platform} size={18} markSize={12} shape="round" />
                {sourceLabel ? <span className="ae-mono">{String(sourceLabel)}</span> : platform}
              </span>
            )}
            {chips.map(chip => (
              <span key={chip.label} className="ae-mono rounded-full border px-2.5 py-0.5 text-[11px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>
                <span style={{ color: 'var(--ae-faint)' }}>{chip.label} </span>{chip.value}
              </span>
            ))}
          </span>
          {proposed.length > 0 && (
            <span className="text-[15px] font-medium" data-testid="review-proposed">Proposed: {proposed.join(' or ')}</span>
          )}
          <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
            {observed !== null ? `${formatCount(observed, timeCtx)} observation${observed === 1 ? '' : 's'}` : 'Observations not reported'}
            {touchpoints !== null && touchpoints > 0 ? ` · ${formatCount(touchpoints, timeCtx)} touchpoints waiting` : ''}
          </span>
          {signals.length > 0 && (
            <span className="flex flex-wrap gap-1.5" data-testid="review-signals">
              {signals.map(sig => {
                const tone: Tone = sig.matched === true ? 'sage' : sig.matched === false ? 'ember' : 'mute';
                return (
                  <TonePill key={sig.label} tone={tone} className="gap-1 !text-[11px] !px-2.5 !py-0.5">
                    {sig.matched !== null && <Icon name={sig.matched ? 'circle-check' : 'circle-x'} decorative size="sm" />}
                    {sig.label}
                  </TonePill>
                );
              })}
            </span>
          )}
        </span>
        {confidence !== null ? (
          <span className="ae-mono text-[13px]" style={{ color: toneColor(confidence >= 60 ? 'amber' : 'ember') }} data-testid="review-confidence">
            {Math.round(confidence)}% confidence
          </span>
        ) : (
          <TonePill tone="amber">needs a person</TonePill>
        )}
      </span>
      {failure && (
        <InlineNotice tone="ember">
          {resolve.error ? 'The grouping was not confirmed' : 'The item was not ignored'}: {failure}
        </InlineNotice>
      )}
      <span className="flex flex-wrap items-center gap-2 border-t pt-2.5" style={{ borderColor: 'var(--ae-edge-soft)' }}>
        {candidates.length > 1 && (
          <select
            value={picked}
            onChange={e => setPicked(e.target.value)}
            aria-label="Campaign to group under"
            className="ae-focus rounded-xl border bg-transparent px-3 py-[7px] text-[12px]"
            style={{ borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)' }}
          >
            {candidates.map(id => <option key={id} value={id}>{names.get(id) ?? id}</option>)}
          </select>
        )}
        <PrimaryButton
          onClick={() => void resolve.mutate({ reviewId, campaignId: picked })}
          disabled={busy || !reviewId || !picked}
          className="!px-4 !py-[7px] text-[12px]"
          data-testid="review-confirm"
        >
          {resolve.isLoading ? 'Confirming…' : 'Confirm grouping'}
        </PrimaryButton>
        <SecondaryButton
          onClick={() => void ignore.mutate({ reviewId })}
          disabled={busy || !reviewId}
          className="!px-4 !py-[7px] text-[12px]"
          data-testid="review-ignore"
        >
          {ignore.isLoading ? 'Ignoring…' : 'Ignore'}
        </SecondaryButton>
        {candidates.length === 0 && (
          <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>No campaign was proposed; pick one in the review queue.</span>
        )}
        <span className="flex-1" />
        <LinkButton onClick={onOpenQueue}>Open in the review queue →</LinkButton>
      </span>
    </article>
  );
}

// ── Attribution ───────────────────────────────────────────────────────────────

function AttributionView() {
  const timeCtx = useTimeContext();
  const { data, isLoading, error } = useCampaigns({ limit: 50 });
  const rows = useMemo(() => {
    const d = asRecord(data);
    return asList(d.campaigns ?? data).flatMap(raw => {
      const c = campaignSummary(raw);
      return c.channels.map(ch => ({
        campaign: c.name,
        channel: text(ch.channel ?? ch.name),
        source: ch.source ? String(ch.source) : null,
        conversions: num(ch.conversions),
        revenue: num(ch.revenue_usd),
        rate: num(ch.conversion_rate),
        weight: num(ch.weight),
      }));
    });
  }, [data]);

  if (error) {
    return (
      <InlineNotice tone="ember">
        <span className="block font-medium">Attribution unavailable</span>
        <span className="block">{errorText(error)}</span>
      </InlineNotice>
    );
  }
  if (isLoading && !data) return <LoadingRow label="Loading attribution…" />;
  if (rows.length === 0) {
    return <EmptySlot>No attribution data. Channel credits appear once campaigns have recorded touchpoints.</EmptySlot>;
  }
  const cols = 'minmax(150px,1.6fr) minmax(110px,1fr) 90px 90px 80px 90px';
  return (
    <GlassSection testId="campaign-attribution">
      <Eyebrow>Attribution by channel</Eyebrow>
      <div className="overflow-x-auto">
        <div className="flex min-w-[640px] flex-col" role="table" aria-label="Campaign attribution by channel">
          <div role="row" className="ae-eyebrow grid gap-3 px-1 pb-1.5" style={{ gridTemplateColumns: cols }}>
            <span role="columnheader">Campaign</span>
            <span role="columnheader">Channel</span>
            <span role="columnheader" className="text-right">Conversions</span>
            <span role="columnheader" className="text-right">Revenue</span>
            <span role="columnheader" className="text-right">Conv. rate</span>
            <span role="columnheader" className="text-right">Weight</span>
          </div>
          {rows.map((r, i) => (
            <div role="row" key={`${r.campaign}-${r.channel}-${r.source ?? ''}-${i}`} className="grid items-center gap-3 border-t px-1 py-[7px] text-[13px]" style={{ gridTemplateColumns: cols, borderColor: 'var(--ae-edge)' }}>
              <span role="cell" className="truncate">{r.campaign}</span>
              <span role="cell" className="flex min-w-0 items-center gap-2">
                {r.source && <BrandMark token={r.source} label={r.source} size={20} markSize={12} />}
                <span className="truncate">{r.channel}{r.source ? <span style={{ color: 'var(--ae-mute)' }}> · {r.source}</span> : null}</span>
              </span>
              <span role="cell" className="ae-mono text-right text-[12px]">{r.conversions !== null ? formatCount(r.conversions, timeCtx) : '—'}</span>
              <span role="cell" className="ae-mono text-right text-[12px]" style={{ color: r.revenue !== null ? 'var(--ae-sage)' : 'var(--ae-faint)' }}>{usd(r.revenue)}</span>
              <span role="cell" className="ae-mono text-right text-[12px]">{pct(r.rate)}</span>
              <span role="cell" className="ae-mono text-right text-[12px]">{pct(r.weight)}</span>
            </div>
          ))}
        </div>
      </div>
    </GlassSection>
  );
}

// ── Exploration (graph-backed) ────────────────────────────────────────────────

export function CampaignExplorationTab() {
  const navigate = useNavigate();
  const timeCtx = useTimeContext();
  const [cursor, setCursor] = useState<string | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<readonly string[]>([]);
  const [linkError, setLinkError] = useState<string | null>(null);
  const { data: envelope, isLoading, error, client, context } = useCampaignExploration(cursor);
  const rows = envelope?.data?.campaigns ?? [];
  const adapterAvailable = envelope?.execution.adapters.includes('campaign360') ?? false;

  async function openCampaign(row: CampaignExplorationRow) {
    setLinkError(null);
    try {
      const resolved = await client.resolveLink({
        context,
        to: 'campaign360',
        focus: { kind: 'campaign', id: row.campaign_id },
      });
      if (!resolved.adapter_available) {
        setLinkError('Campaign exploration is unavailable in this release.');
        return;
      }
      navigate(`/campaigns/${encodeURIComponent(row.campaign_id)}?${encodeExplorationContext(resolved.link.context)}`);
    } catch (reason) {
      setLinkError(reason instanceof Error ? reason.message : 'Unable to preserve exploration context.');
    }
  }

  if (error) return <ErrorState title="Campaign exploration unavailable" message={error} />;
  if (isLoading && !envelope) return <LoadingState lines={5} />;
  if (envelope && !adapterAvailable) {
    return <TruthBanner status="not_enabled" surfaceLabel="Campaign exploration" />;
  }

  return (
    <div className="space-y-3">
      {envelope && (
        <TruthBanner
          status="ready"
          truth={envelope.truth}
          completeness={envelope.completeness}
          applicability={envelope.applicability}
        />
      )}
      {linkError && <ErrorState title="Unable to open campaign" message={linkError} />}
      <DataTable<CampaignExplorationRow>
        caption="Campaign exploration results"
        columns={[
          {
            key: 'campaign_id',
            header: 'Campaign',
            render: (row) => <code>{row.campaign_id}</code>,
          },
          {
            key: 'count',
            header: 'Attributed nodes',
            render: (row) => formatCount(row.count, timeCtx),
          },
        ]}
        data={rows}
        keyExtractor={(row) => row.campaign_id}
        onRowClick={(row) => void openCampaign(row)}
        loading={isLoading}
        selection={{ selectedKeys, onSelectionChange: setSelectedKeys }}
        page={{
          returned: rows.length,
          ...(envelope?.pagination?.total_estimate !== undefined
            ? { total: envelope.pagination.total_estimate }
            : {}),
          ...(envelope?.pagination?.cursor !== undefined
            ? { nextCursor: envelope.pagination.cursor }
            : {}),
          onNext: setCursor,
        }}
        emptyMessage="No attributed campaign nodes match this exploration."
      />
      {(envelope?.data?.unattributed_count ?? 0) > 0 && (
        <p className="text-xs text-text-muted">
          {envelope!.data!.unattributed_count} returned nodes have no asserted campaign attribution.
        </p>
      )}
    </div>
  );
}

// ── Platform overview (KPI band + mix + insights) ─────────────────────────────

const WINDOWS: readonly SegmentOption<'6' | '24' | '72'>[] = [
  { value: '6', label: '6h' },
  { value: '24', label: '24h' },
  { value: '72', label: '72h' },
];

function OverviewBand({ hours, onHours }: { hours: number; onHours: (h: number) => void }) {
  const timeCtx = useTimeContext();
  const { data, isLoading, error } = usePlatformOverview(hours);
  const ov = asRecord(data);
  const value = (v: unknown, kind: 'count' | 'pct') => {
    const n = num(v);
    if (n === null) return isLoading && !data ? '…' : '—';
    return kind === 'pct' ? pct(n) : formatCount(n, timeCtx);
  };
  const fraud = num(ov.fraud_blocked);

  return (
    <div className="flex flex-col gap-2.5" data-testid="campaigns-overview">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Eyebrow>Platform · last {hours}h</Eyebrow>
        <SegmentedTabs
          label="Overview window"
          options={WINDOWS}
          value={String(hours) as '6' | '24' | '72'}
          onChange={v => onHours(Number(v))}
        />
      </div>
      <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
        <MetricTile label="Total sessions" value={value(ov.total_sessions, 'count')} sub={`last ${hours}h`} />
        <MetricTile label="Conversion rate" value={value(ov.conversion_rate, 'pct')} sub="sessions that converted" />
        <MetricTile label="Fraud blocked" value={value(ov.fraud_blocked, 'count')} sub="sessions" {...(fraud !== null && fraud > 0 ? { tone: 'ember' as Tone } : {})} />
        <MetricTile label="Active campaigns" value={value(ov.active_campaigns, 'count')} sub="observed" />
      </div>
      {error && (
        <InlineNotice tone="amber">
          <span className="block font-medium">Failed to load overview</span>
          <span className="block">Platform totals are unavailable right now; campaign records below are read separately. {errorText(error)}</span>
        </InlineNotice>
      )}
    </div>
  );
}

function PlatformMix({ hours }: { hours: number }) {
  const timeCtx = useTimeContext();
  const { data } = usePlatformOverview(hours);
  const { data: insightsData } = useAutomationInsights();
  const ov = asRecord(data);
  const web2 = asRecord(ov.web2);
  const web3 = asRecord(ov.web3);
  const insights = asList(insightsData ?? ov.insights);
  const hasMix = web2.sessions !== undefined || web3.sessions !== undefined;
  if (!hasMix && insights.length === 0) return null;
  const count = (v: unknown) => (num(v) !== null ? formatCount(num(v) ?? 0, timeCtx) : '—');

  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(300px, 100%), 1fr))' }}>
      {hasMix && (
        <GlassSection testId="campaigns-mix">
          <Eyebrow>Web2 and Web3 · last {hours}h</Eyebrow>
          <div className="grid grid-cols-2 gap-2.5">
            <MetricTile label="Web2 sessions" value={count(web2.sessions)} sub={`${pct(num(web2.conversion_rate))} conv.`} />
            <MetricTile label="Web2 revenue" value={usd(num(web2.revenue_usd))} sub={`avg LTV ${usd(num(web2.avg_ltv_usd))}`} />
            <MetricTile label="Wallet sessions" value={count(web3.sessions)} sub={`${pct(num(web3.conversion_rate))} conv.`} />
            <MetricTile label="On-chain volume" value={usd(num(web3.volume_usd))} sub={`${count(web3.active_wallets)} wallets active`} />
          </div>
        </GlassSection>
      )}
      {insights.length > 0 && (
        <GlassSection testId="campaigns-insights">
          <Eyebrow>What this tells you</Eyebrow>
          {insights.slice(0, 6).map((insight, i) => {
            const ins = asRecord(insight);
            const sev = String(ins.severity ?? '');
            const tone: Tone = sev === 'high' ? 'ember' : sev === 'medium' ? 'amber' : 'blue';
            return (
              <div key={i} className="flex items-start gap-2.5 rounded-[14px] border px-3 py-2.5" style={{ borderColor: 'var(--ae-edge-soft)', background: 'var(--ae-glass-card)' }}>
                {sev && <TonePill tone={tone}>{sev}</TonePill>}
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="text-[13px] leading-snug">{text(ins.message ?? ins.description ?? (typeof insight === 'string' ? insight : ''))}</span>
                  {!!ins.recommendation && <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>{text(ins.recommendation)}</span>}
                </span>
                {!!ins.metric && <span className="ae-mono shrink-0 text-[11px]" style={{ color: 'var(--ae-mute)' }}>{text(ins.metric)}: {text(ins.value)}</span>}
              </div>
            );
          })}
        </GlassSection>
      )}
    </div>
  );
}

// ── Campaign intelligence strip ───────────────────────────────────────────────

function IntelligenceStrip({ openReviews }: { openReviews: number }) {
  const navigate = useNavigate();
  const { data: quality } = useCampaignQuality();
  const spendRate = num(asRecord(quality).spend_mapping_rate);
  const below = spendRate !== null && spendRate < 0.9;

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-[18px] border px-4 py-2.5" style={{ borderColor: 'var(--ae-edge)', background: 'var(--ae-glass-card)' }} data-testid="campaign-intelligence">
      <span className="flex flex-wrap items-center gap-x-3.5 gap-y-1 text-[12px]">
        <Eyebrow>Campaign intelligence</Eyebrow>
        {spendRate !== null ? (
          <span className="flex items-center gap-1.5">
            <span style={{ color: 'var(--ae-mute)' }}>Spend mapping rate</span>
            <span className="ae-mono font-medium" style={{ color: below ? 'var(--ae-amber)' : 'var(--ae-sage)' }}>{(spendRate * 100).toFixed(1)}%</span>
            {below && <TonePill tone="amber">Below target</TonePill>}
          </span>
        ) : openReviews === 0 ? (
          <span style={{ color: 'var(--ae-mute)' }}>Connect a campaign source to start populating the registry.</span>
        ) : null}
      </span>
      <span className="flex flex-wrap items-center gap-3">
        <LinkButton onClick={() => void navigate('/campaign-intelligence/sources')}>Sources</LinkButton>
        <LinkButton onClick={() => void navigate('/campaign-intelligence/registry')}>Registry</LinkButton>
        <LinkButton onClick={() => void navigate('/campaign-intelligence/mapping-review')}>Review queue</LinkButton>
        <LinkButton onClick={() => void navigate('/campaign-intelligence/quality')}>Quality</LinkButton>
      </span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

/**
 * Campaigns (Claude Design handoff: Aether Campaigns). Campaigns are imported
 * from the systems that run them and normalised here; Aether observes them and
 * never edits, pauses or launches anything at the source. Every figure is a
 * read from the existing campaign, automation, quality and mapping-review
 * endpoints.
 */
export function CampaignsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const viewParam = params.get('view');
  const view: View = isView(viewParam) ? viewParam : 'active';
  const [hours, setHours] = useState(24);
  const [query, setQuery] = useState('');

  const all = useCampaigns({ limit: 50 });
  const reviews = useMappingReviews({ status: 'open', limit: 50 });
  const reviewRecord = asRecord(reviews.data);
  const openReviews = num(reviewRecord.total)
    ?? (Array.isArray(reviewRecord.items) ? reviewRecord.items.length : Array.isArray(reviews.data) ? reviews.data.length : 0);
  const total = num(asRecord(all.data).total);

  function setView(next: View) {
    setParams(prev => {
      const p = new URLSearchParams(prev);
      if (next === 'active') p.delete('view');
      else p.set('view', next);
      return p;
    }, { replace: true });
  }

  const options: SegmentOption<View>[] = [
    { value: 'active', label: 'Active' },
    { value: 'paused', label: 'Paused' },
    { value: 'ended', label: 'Ended' },
    { value: 'all', label: 'All campaigns' },
    { value: 'review', label: 'Review', badge: openReviews },
    { value: 'attribution', label: 'Attribution' },
    { value: 'exploration', label: 'Exploration' },
  ];
  const listView = view === 'active' || view === 'paused' || view === 'ended' || view === 'all';
  const status = STATUS_VIEWS[view];

  return (
    <GlassPage>
      <div className="flex flex-col gap-4" data-testid="aether-campaigns">
        {/* Header */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <span className="flex flex-col gap-1">
            <h1 className="text-[clamp(26px,4.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Campaigns</h1>
            <span className="max-w-[560px] text-[14px] leading-[1.45]" style={{ color: 'var(--ae-mute)' }}>
              Imported from the systems that run them, then normalized here. Aether observes them. It never edits, pauses or launches anything at the source.
            </span>
          </span>
          <span className="flex w-full flex-wrap gap-2 sm:w-auto">
            {listView && <GlassSearch value={query} onChange={setQuery} placeholder="Search campaigns" label="Search campaigns" />}
            <PrimaryButton onClick={() => void navigate('/campaign-intelligence/sources')} data-testid="campaigns-import">
              Import from a source
            </PrimaryButton>
            <SecondaryButton onClick={() => void navigate('/campaign-intelligence/campaigns/new')}>Custom campaign</SecondaryButton>
          </span>
        </div>

        <IntelligenceStrip openReviews={openReviews} />

        <OverviewBand hours={hours} onHours={setHours} />

        {/* View chips */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SegmentedTabs label="Campaign views" options={options} value={view} onChange={setView} />
          {total !== null && (
            <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
              {compact(total)} canonical campaign{total === 1 ? '' : 's'} imported
            </span>
          )}
        </div>

        <div className="ae-rise flex flex-col gap-3" key={view} role="tabpanel">
          {listView && <CampaignList {...(status ? { status } : {})} query={query} />}
          {view === 'review' && <ReviewQueue />}
          {view === 'attribution' && <AttributionView />}
          {view === 'exploration' && (
            <div className="ae-legacy">
              <CampaignExplorationTab />
            </div>
          )}
        </div>

        <PlatformMix hours={hours} />

      </div>
    </GlassPage>
  );
}
