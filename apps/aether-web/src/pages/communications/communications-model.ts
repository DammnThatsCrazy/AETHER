import {
  asList, asRecord, campaignSummary, num, shortDate, text, type AnyRecord,
} from '@aether-app/pages/campaigns/campaign-model';
import type { CommsIndex } from '@aether-app/features/communications/use-communications';

/**
 * Read-side helpers for the Communications page. They only normalise the
 * loosely-typed Communications Intelligence payloads; an absent figure stays
 * absent (null), never zero. Rates are never computed here: governed rate
 * results come from the backend measurement plane (min sample, Wilson band,
 * value state) and are passed through as-is.
 */

export type ChannelKey = 'email' | 'sms' | 'push' | 'in_app' | 'agent';

export const CHANNELS: readonly { readonly key: ChannelKey; readonly label: string }[] = [
  { key: 'email', label: 'Email' },
  { key: 'sms', label: 'SMS' },
  { key: 'push', label: 'Push' },
  { key: 'in_app', label: 'In-app' },
  { key: 'agent', label: 'Agent' },
];

export function channelKey(raw: unknown): ChannelKey | null {
  const c = typeof raw === 'string' ? raw.trim().toLowerCase().replace(/[\s-]/g, '_') : '';
  if (c === 'email') return 'email';
  if (c === 'sms' || c === 'text') return 'sms';
  if (c === 'push') return 'push';
  if (c === 'in_app' || c === 'inapp') return 'in_app';
  if (c === 'agent' || c === 'agent_message') return 'agent';
  return null;
}

export function channelLabel(key: ChannelKey | null, raw?: string | null): string {
  if (key) return CHANNELS.find(c => c.key === key)?.label ?? key;
  return raw ? raw : 'Channel not reported';
}

export interface CommsMessageRow {
  readonly key: string;
  readonly campaignId: string;
  readonly campaignName: string;
  readonly campaignStatus: string;
  readonly provider: string | null;
  readonly channel: ChannelKey | null;
  readonly rawChannel: string | null;
  readonly externalMessageId: string;
  readonly name: string;
  readonly status: string;
  readonly sequenceStep: number | null;
  readonly delivered: number | null;
  readonly humanClicks: number | null;
  readonly replies: number | null;
  readonly bounces: number | null;
  readonly machineEvents: number | null;
  readonly totalEvents: number | null;
}

export interface CommsIndexModel {
  readonly rows: readonly CommsMessageRow[];
  readonly scannedCampaigns: number;
  readonly failedCampaigns: readonly string[];
  readonly skippedCampaigns: number;
}

export function messageRows(index: CommsIndex | null | undefined): CommsIndexModel {
  if (!index) return { rows: [], scannedCampaigns: 0, failedCampaigns: [], skippedCampaigns: 0 };
  const rows: CommsMessageRow[] = [];
  const failed: string[] = [];
  for (const entry of index.campaigns) {
    const c = campaignSummary(entry.raw);
    if (entry.messages === null) {
      failed.push(c.name);
      continue;
    }
    const provider = entry.raw.primary_platform ?? c.platform;
    for (const m of entry.messages) {
      const ext = text(m.external_message_id, '');
      if (!ext) continue;
      rows.push({
        key: `${c.id}:${ext}`,
        campaignId: c.id,
        campaignName: c.name,
        campaignStatus: c.status,
        provider: provider ? String(provider) : null,
        channel: channelKey(m.channel ?? c.channel),
        rawChannel: c.channel,
        externalMessageId: ext,
        name: ext === 'unattributed' ? 'Events without a message id' : text(m.name, ext),
        status: text(m.status, 'unknown'),
        sequenceStep: num(m.sequence_step),
        delivered: num(m.delivered),
        humanClicks: num(m.human_clicks),
        replies: num(m.replies),
        bounces: num(m.bounces),
        machineEvents: num(m.machine_events),
        totalEvents: num(m.total_events),
      });
    }
  }
  return {
    rows,
    scannedCampaigns: index.campaigns.length,
    failedCampaigns: failed,
    skippedCampaigns: index.skipped,
  };
}

/** Human-qualified vs suspected machine split of a message's events (counts, not a rate). */
export function eventSplit(row: Pick<CommsMessageRow, 'machineEvents' | 'totalEvents'>): { human: number; machine: number } | null {
  if (row.totalEvents === null || row.totalEvents <= 0 || row.machineEvents === null) return null;
  const machine = Math.min(row.machineEvents, row.totalEvents);
  return { human: row.totalEvents - machine, machine };
}

export function matchesQuery(row: CommsMessageRow, q: string): boolean {
  if (!q) return true;
  return [row.name, row.campaignName, row.provider ?? '', row.externalMessageId].some(v => v.toLowerCase().includes(q));
}

export function communicationHref(row: Pick<CommsMessageRow, 'campaignId' | 'externalMessageId'>): string {
  return `/communications/${encodeURIComponent(row.campaignId)}/${encodeURIComponent(row.externalMessageId)}`;
}

// ── Governed rates ────────────────────────────────────────────────────────────

export interface GovernedRate {
  readonly value: number | null;
  readonly state: string;
  readonly sampleSize: number | null;
  readonly minRequired: number | null;
  readonly lower: number | null;
  readonly upper: number | null;
  readonly method: string | null;
}

/** Pass a backend `*_rate_result` through; returns null when none was reported. */
export function governedRate(result: unknown): GovernedRate | null {
  const r = asRecord(result);
  if (!Object.keys(r).length) return null;
  const suff = asRecord(r.sufficiency);
  const unc = asRecord(r.uncertainty);
  const state = text(r.value_state, 'missing_inputs');
  const value = state === 'observed' || state === 'estimated' ? num(r.value) : null;
  return {
    value,
    state,
    sampleSize: num(suff.sample_size),
    minRequired: num(suff.min_required),
    lower: num(unc.lower),
    upper: num(unc.upper),
    method: unc.method ? String(unc.method) : null,
  };
}

const STATE_LABELS: Record<string, string> = {
  observed: 'Observed',
  estimated: 'Estimated',
  insufficient_data: 'Withheld: below the minimum sample',
  missing_inputs: 'Withheld: nothing delivered yet',
  not_applicable: 'Not applicable',
  degraded: 'Withheld: degraded inputs',
};

export function rateStateLabel(state: string): string {
  return STATE_LABELS[state] ?? `Withheld: ${state.replace(/_/g, ' ')}`;
}

export function fmtRate(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

// ── Detail payloads ───────────────────────────────────────────────────────────

export interface MessageDetail {
  readonly name: string;
  readonly provider: string | null;
  readonly channel: ChannelKey | null;
  readonly rawChannel: string | null;
  readonly subject: string | null;
  readonly template: string | null;
  readonly variant: string | null;
  readonly category: string | null;
  readonly status: string;
  readonly sequenceStep: number | null;
  readonly firstSeen: string | null;
  readonly lastSeen: string | null;
  readonly stats: {
    readonly delivered: number | null;
    readonly humanClicks: number | null;
    readonly replies: number | null;
    readonly bounces: number | null;
    readonly machineEvents: number | null;
    readonly totalEvents: number | null;
  };
  readonly links: readonly { readonly id: string; readonly humanClicks: number | null; readonly uniqueClickers: number | null }[];
}

export function messageDetail(raw: unknown, externalMessageId: string, campaign?: unknown): MessageDetail {
  const d = asRecord(raw);
  const m = asRecord(d.message);
  const s = asRecord(d.stats);
  const c = asRecord(campaign);
  const provider = m.provider ?? c.primary_platform ?? c.platform;
  const rawChannel = m.channel ?? c.channel;
  return {
    name: externalMessageId === 'unattributed' ? 'Events without a message id' : text(m.name, externalMessageId),
    provider: provider ? String(provider) : null,
    channel: channelKey(rawChannel),
    rawChannel: rawChannel ? String(rawChannel) : null,
    subject: m.subject_redacted ? String(m.subject_redacted) : null,
    template: m.external_template_id ? String(m.external_template_id) : null,
    variant: m.variant_id ? String(m.variant_id) : null,
    category: m.message_category ? String(m.message_category) : null,
    status: text(m.status, 'unknown'),
    sequenceStep: num(m.sequence_step),
    firstSeen: shortDate(m.first_seen_at),
    lastSeen: shortDate(m.last_seen_at),
    stats: {
      delivered: num(s.delivered),
      humanClicks: num(s.human_clicks),
      replies: num(s.replies),
      bounces: num(s.bounces),
      machineEvents: num(s.machine_events),
      totalEvents: num(s.total_events),
    },
    links: asList(d.links).map(asRecord).map(l => ({
      id: text(l.link_id, ''),
      humanClicks: num(l.human_clicks),
      uniqueClickers: num(l.unique_clickers),
    })).filter(l => l.id),
  };
}

export interface FunnelStep {
  readonly key: string;
  readonly label: string;
  readonly human: number | null;
  readonly reported: number | null;
  readonly rate: GovernedRate | null;
  readonly note: string;
}

export interface FunnelModel {
  readonly steps: readonly FunnelStep[];
  readonly delivery: Readonly<Record<string, number | null>>;
  readonly machineRate: GovernedRate | null;
}

export function funnelModel(raw: unknown): FunnelModel {
  const f = asRecord(raw);
  const modes = asRecord(f.modes);
  const hq = asRecord(modes.human_qualified);
  const pr = asRecord(modes.provider_reported);
  const delivery = asRecord(f.delivery);
  const quality = asRecord(f.quality);
  return {
    steps: [
      { key: 'sent', label: 'Sent', human: num(hq.sent), reported: num(pr.sent), rate: null, note: 'Messages the provider reports as sent.' },
      { key: 'delivered', label: 'Delivered', human: num(hq.delivered), reported: num(pr.delivered), rate: null, note: 'Recipients the provider confirmed delivery to. Every rate below uses this as its denominator.' },
      { key: 'opened', label: 'Opened', human: num(hq.opens), reported: num(pr.opens), rate: governedRate(hq.open_rate_result), note: 'Human-qualified opens exclude security scanners and image proxies. Provider-reported opens count every open event.' },
      { key: 'clicked', label: 'Clicked', human: num(hq.clicks), reported: num(pr.clicks), rate: governedRate(hq.click_rate_result), note: 'Human-qualified clicks exclude link scanners and other suspected machine activity.' },
      { key: 'replied', label: 'Replied', human: num(hq.replies), reported: null, rate: governedRate(hq.reply_rate_result), note: 'Replies exclude automated responses such as out-of-office messages.' },
    ],
    delivery: {
      hard_bounces: num(delivery.hard_bounces),
      soft_bounces: num(delivery.soft_bounces),
      complaints: num(delivery.complaints),
      unsubscribes: num(delivery.unsubscribes),
      suppressions: num(delivery.suppressions),
      dropped: num(delivery.dropped),
      deferred: num(delivery.deferred),
    },
    machineRate: governedRate(quality.machine_event_rate_result),
  };
}

export interface RecipientRow {
  readonly key: string;
  readonly display: string;
  readonly entityId: string | null;
  readonly stage: string;
  readonly delivered: number | null;
  readonly humanClicks: number | null;
  readonly replies: number | null;
  readonly flags: readonly string[];
}

export function recipientRows(raw: unknown): { rows: RecipientRow[]; stageCounts: Record<string, number> } {
  const d = asRecord(raw);
  const counts: Record<string, number> = {};
  for (const [k, v] of Object.entries(asRecord(d.stage_counts))) {
    const n = num(v);
    if (n !== null) counts[k] = n;
  }
  const rows = asList(d.items).map(asRecord).map((r, i) => ({
    key: text(r.recipient_key, `r${i}`),
    display: text(r.recipient_display ?? r.recipient_key, 'Unnamed recipient'),
    entityId: r.entity_id ? String(r.entity_id) : null,
    stage: text(r.stage, 'observed'),
    delivered: num(r.delivered),
    humanClicks: num(r.human_clicks),
    replies: num(r.replies),
    flags: (['bounced', 'complained', 'unsubscribed', 'suppressed'] as const).filter(f => Boolean(r[f])),
  }));
  return { rows, stageCounts: counts };
}

export interface JourneyRow {
  readonly id: string;
  readonly profileId: string | null;
  readonly stages: number | null;
  readonly converted: boolean;
  readonly started: string | null;
  readonly completed: string | null;
}

export function journeyRows(raw: unknown): { rows: JourneyRow[]; hasMore: boolean } {
  const d = asRecord(raw);
  const rows = asList(d.items).map(asRecord).map((j, i) => ({
    id: text(j.journey_id, `j${i}`),
    profileId: j.profile_id ? String(j.profile_id) : null,
    stages: num(j.stage_count),
    converted: j.converted === true,
    started: shortDate(j.started_at),
    completed: shortDate(j.completed_at),
  }));
  return { rows, hasMore: asRecord(d.pagination).has_more === true };
}

export interface ConversionSummary {
  readonly count: number;
  readonly hasMore: boolean;
  readonly gross: number | null;
  readonly byType: readonly { readonly type: string; readonly count: number }[];
  readonly items: readonly { readonly id: string; readonly type: string; readonly gross: number | null; readonly date: string | null; readonly profileId: string | null }[];
}

export function conversionSummary(raw: unknown): ConversionSummary {
  const d = asRecord(raw);
  const items = asList(d.items).map(asRecord).map((c, i) => ({
    id: text(c.conversion_id, `c${i}`),
    type: text(c.conversion_type, 'conversion'),
    gross: num(c.gross_value),
    date: shortDate(c.occurred_at),
    profileId: c.profile_id ? String(c.profile_id) : c.entity_id ? String(c.entity_id) : null,
  }));
  const priced = items.filter(c => c.gross !== null);
  const types = new Map<string, number>();
  for (const c of items) types.set(c.type, (types.get(c.type) ?? 0) + 1);
  return {
    count: items.length,
    hasMore: asRecord(d.pagination).has_more === true,
    gross: priced.length ? priced.reduce((sum, c) => sum + (c.gross ?? 0), 0) : null,
    byType: [...types.entries()].map(([type, count]) => ({ type, count })).sort((a, b) => b.count - a.count),
    items,
  };
}

export type { AnyRecord };
