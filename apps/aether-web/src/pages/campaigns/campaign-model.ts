import type { Tone } from '@aether-app/components/ae-ui';

/**
 * Read-side helpers for campaign payloads. The campaign list and Campaign 360
 * endpoints return loosely-typed records; these helpers only normalise field
 * aliases and never substitute a value for an absent one.
 */

export type AnyRecord = Record<string, unknown>;

export function asRecord(v: unknown): AnyRecord {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as AnyRecord) : {};
}

export function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

/** Finite number or null (absent / non-numeric is unknown, not zero). */
export function num(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN;
  return Number.isFinite(n) ? n : null;
}

export function text(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 10_000) return `${(value / 1_000).toFixed(1)}k`;
  return Math.round(value).toLocaleString('en-US');
}

export function usd(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '—';
  if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (Math.abs(value) >= 10_000) return `$${Math.round(value / 1_000)}K`;
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

/** a / b as a fraction, or null when either side is unknown or b is 0. */
export function ratio(a: number | null, b: number | null): number | null {
  if (a === null || b === null || b === 0) return null;
  return a / b;
}

export function shortDate(iso: unknown): string | null {
  if (typeof iso !== 'string' || !iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export function statusTone(status: string): Tone {
  const s = status.toLowerCase();
  if (s === 'active' || s === 'live' || s === 'running' || s === 'enabled') return 'sage';
  if (s === 'paused') return 'amber';
  if (s === 'scheduled' || s === 'draft') return 'blue';
  if (s === 'cancelled' || s === 'canceled' || s === 'failed') return 'ember';
  return 'mute';
}

export interface CampaignSummary {
  readonly id: string;
  readonly name: string;
  readonly status: string;
  readonly type: string | null;
  readonly platform: string | null;
  readonly channel: string | null;
  readonly start: string | null;
  readonly end: string | null;
  readonly reached: number | null;
  readonly clicked: number | null;
  readonly converted: number | null;
  readonly dropped: number | null;
  readonly abandoned: number | null;
  readonly dropOffRate: number | null;
  readonly abandonmentRate: number | null;
  readonly conversionRate: number | null;
  readonly fraudBlocked: number | null;
  readonly revenue: number | null;
  readonly cost: number | null;
  readonly roas: number | null;
  readonly mappingQuality: string | null;
  readonly channels: readonly AnyRecord[];
}

/** Normalise one campaign list row (field aliases match the previous page). */
export function campaignSummary(raw: unknown): CampaignSummary {
  const c = asRecord(raw);
  const metrics = asRecord(c.metrics);
  const funnel = asRecord(c.funnel ?? metrics.funnel);
  const platform = c.platform ?? c.origin ?? c.source;
  return {
    id: text(c.id ?? c.campaign_id, ''),
    name: text(c.name ?? c.campaign_id ?? c.id),
    status: text(c.status, 'unknown'),
    type: c.type ? String(c.type) : null,
    platform: platform ? String(platform) : null,
    channel: c.channel ? String(c.channel) : null,
    start: shortDate(c.start_date ?? c.created_at),
    end: shortDate(c.end_date),
    reached: num(funnel.entered ?? c.impressions),
    clicked: num(funnel.clicked ?? c.clicks),
    converted: num(funnel.converted ?? c.conversions),
    dropped: num(funnel.dropped),
    abandoned: num(funnel.abandoned),
    dropOffRate: num(funnel.drop_off_rate ?? c.drop_off_rate),
    abandonmentRate: num(funnel.abandonment_rate ?? c.abandonment_rate),
    conversionRate: num(metrics.conversion_rate ?? c.conversion_rate),
    fraudBlocked: num(metrics.fraud_blocked ?? c.fraud_blocked),
    revenue: num(c.revenue_usd ?? metrics.revenue_usd),
    cost: num(c.cost_usd ?? metrics.cost_usd),
    roas: num(c.roas ?? metrics.roas),
    mappingQuality: c.mapping_quality ? String(c.mapping_quality) : null,
    channels: asList(c.top_channels ?? metrics.top_channels).map(ch =>
      ch && typeof ch === 'object' ? (ch as AnyRecord) : { channel: String(ch) },
    ),
  };
}
