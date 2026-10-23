/**
 * Pure shaping helpers for the Value page. Every function here turns a real
 * backend payload into chart-ready rows; none of them invents a value. A field
 * the backend did not send stays `null` and the UI renders it as "not reported".
 */

export type Row = Record<string, unknown>;

export function asRecord(value: unknown): Row {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {};
}

export function asList(value: unknown): Row[] {
  return Array.isArray(value)
    ? value.filter((item): item is Row => !!item && typeof item === 'object' && !Array.isArray(item))
    : [];
}

export function num(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function str(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text === '' ? null : text;
}

/**
 * Compact currency for chart labels: $1.2M, $12.4k, $830. A non-USD currency
 * code is shown as a prefix (EUR 12.4k) rather than a dollar sign.
 */
export function compactMoney(value: number | null, currency: string | null = null): string {
  if (value === null) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  const unit = currency && currency !== 'USD' ? `${currency} ` : '$';
  if (abs >= 1_000_000) return `${sign}${unit}${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000) return `${sign}${unit}${Math.round(abs / 1_000)}k`;
  if (abs >= 1_000) return `${sign}${unit}${(abs / 1_000).toFixed(1)}k`;
  return `${sign}${unit}${Math.round(abs).toLocaleString('en-US')}`;
}

export function pct(value: number | null, digits = 0): string {
  return value === null ? '—' : `${(value * 100).toFixed(digits)}%`;
}

/** snake_case backend vocabulary → sentence case label. */
export function humanize(token: string): string {
  const spaced = token.replace(/[_-]+/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : token;
}

// ── Value-created events (GET /v1/billing/value-created) ─────────────────────

export interface ValueEvent {
  readonly id: string;
  readonly sourceType: string;
  readonly sourceId: string | null;
  readonly valueType: string;
  readonly amount: number | null;
  readonly currency: string | null;
  readonly confidence: number | null;
  readonly notes: string | null;
  readonly occurredAt: Date | null;
}

export function parseValueEvents(payload: unknown): ValueEvent[] {
  return asList(asRecord(payload)['items']).map((row, index) => {
    const at = str(row['occurred_at']);
    const parsed = at ? new Date(at) : null;
    return {
      id: str(row['value_event_id']) ?? `value-${index}`,
      sourceType: str(row['source_type']) ?? 'unknown',
      sourceId: str(row['source_id']),
      valueType: str(row['value_type']) ?? 'unknown',
      amount: num(row['value_amount']),
      currency: str(row['currency']),
      confidence: num(row['confidence']),
      notes: str(row['attribution_notes']),
      occurredAt: parsed && !Number.isNaN(parsed.getTime()) ? parsed : null,
    };
  });
}

export interface Group {
  readonly key: string;
  readonly total: number;
  readonly events: number;
  /** Events in this group that carried no amount (counted, never summed as 0). */
  readonly unpriced: number;
  readonly confidence: number | null;
  readonly last: Date | null;
}

export function groupEvents(events: readonly ValueEvent[], by: (event: ValueEvent) => string): Group[] {
  const groups = new Map<string, { total: number; events: number; unpriced: number; conf: number[]; last: Date | null }>();
  for (const event of events) {
    const key = by(event);
    const group = groups.get(key) ?? { total: 0, events: 0, unpriced: 0, conf: [], last: null };
    group.events += 1;
    if (event.amount === null) group.unpriced += 1;
    else group.total += event.amount;
    if (event.confidence !== null) group.conf.push(event.confidence);
    if (event.occurredAt && (!group.last || event.occurredAt > group.last)) group.last = event.occurredAt;
    groups.set(key, group);
  }
  return [...groups.entries()]
    .map(([key, g]) => ({
      key,
      total: g.total,
      events: g.events,
      unpriced: g.unpriced,
      confidence: g.conf.length ? g.conf.reduce((a, b) => a + b, 0) / g.conf.length : null,
      last: g.last,
    }))
    .sort((a, b) => b.total - a.total || b.events - a.events);
}

export function dayKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export interface DayPoint {
  readonly day: string;
  readonly total: number;
  readonly events: number;
}

export const SERIES_MAX_DAYS = 400;

/** Daily totals across the span the events actually cover (gaps filled with real zero-event days), capped to the most recent SERIES_MAX_DAYS. */
export function dailySeries(events: readonly ValueEvent[]): DayPoint[] {
  const dated = events.filter((e): e is ValueEvent & { occurredAt: Date } => e.occurredAt !== null);
  if (dated.length === 0) return [];
  const byDay = new Map<string, { total: number; events: number }>();
  let min = dated[0]!.occurredAt;
  let max = dated[0]!.occurredAt;
  for (const event of dated) {
    const key = dayKey(event.occurredAt);
    const bucket = byDay.get(key) ?? { total: 0, events: 0 };
    bucket.events += 1;
    bucket.total += event.amount ?? 0;
    byDay.set(key, bucket);
    if (event.occurredAt < min) min = event.occurredAt;
    if (event.occurredAt > max) max = event.occurredAt;
  }
  const out: DayPoint[] = [];
  const end = new Date(max.getFullYear(), max.getMonth(), max.getDate());
  // Bound the walk to the most recent SERIES_MAX_DAYS so a stray decade-old
  // timestamp can neither build a huge array nor push current days out.
  const earliest = new Date(end.getFullYear(), end.getMonth(), end.getDate() - (SERIES_MAX_DAYS - 1));
  const first = new Date(min.getFullYear(), min.getMonth(), min.getDate());
  const cursor = first < earliest ? earliest : first;
  for (let i = 0; cursor <= end && i < SERIES_MAX_DAYS; i += 1) {
    const key = dayKey(cursor);
    const bucket = byDay.get(key);
    out.push({ day: key, total: bucket?.total ?? 0, events: bucket?.events ?? 0 });
    cursor.setDate(cursor.getDate() + 1);
  }
  return out;
}

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;
export const HOUR_BANDS = ['00', '03', '06', '09', '12', '15', '18', '21'] as const;

export interface HeatCell {
  readonly day: number;
  readonly band: number;
  readonly total: number;
  readonly events: number;
}

/** Weekday × 3-hour band, in the viewer's local time. */
export function weekdayHeat(events: readonly ValueEvent[]): HeatCell[] {
  const cells: HeatCell[] = [];
  const grid = Array.from({ length: 7 }, () => Array.from({ length: 8 }, () => ({ total: 0, events: 0 })));
  for (const event of events) {
    if (!event.occurredAt) continue;
    const day = (event.occurredAt.getDay() + 6) % 7;
    const band = Math.floor(event.occurredAt.getHours() / 3);
    const cell = grid[day]![band]!;
    cell.events += 1;
    cell.total += event.amount ?? 0;
  }
  grid.forEach((row, day) => row.forEach((cell, band) => cells.push({ day, band, ...cell })));
  return cells;
}

// ── Outcome ledger (GET /v1/intelligence/outcome-ledger) ─────────────────────

export interface FunnelStep {
  readonly key: string;
  readonly label: string;
  readonly count: number | null;
}

export function ledgerFunnel(summary: Row): FunnelStep[] {
  return [
    { key: 'recommendations_generated', label: 'Recommendations generated' },
    { key: 'recommendations_viewed', label: 'Viewed' },
    { key: 'decisions_recorded', label: 'Decisions recorded' },
    { key: 'actions_logged', label: 'Actions logged' },
    { key: 'outcomes_observed', label: 'Outcomes observed' },
  ].map(step => ({ ...step, count: num(summary[step.key]) }));
}

export interface EntityValue {
  readonly key: string;
  readonly observed: number;
  readonly expected: number | null;
  readonly outcomes: number | null;
  readonly recommendations: number | null;
}

export function entityValues(ledger: Row): EntityValue[] {
  return asList(ledger['by_entity'])
    .map(row => ({
      key: str(row['key']) ?? 'unknown',
      observed: num(row['observed_value']) ?? 0,
      expected: num(row['expected_value']),
      outcomes: num(row['outcomes']),
      recommendations: num(row['recommendations']),
    }))
    .sort((a, b) => b.observed - a.observed);
}

/** Cumulative share of value held by the top x share of entities (a Lorenz-style curve, descending). */
export function concentration(values: readonly number[]): Array<{ x: number; y: number }> {
  const positive = values.filter(v => v > 0).sort((a, b) => b - a);
  const total = positive.reduce((a, b) => a + b, 0);
  if (positive.length === 0 || total <= 0) return [];
  const points = [{ x: 0, y: 0 }];
  let running = 0;
  positive.forEach((v, i) => {
    running += v;
    points.push({ x: (i + 1) / positive.length, y: running / total });
  });
  return points;
}

export interface TreeCell {
  readonly key: string;
  readonly value: number;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

/**
 * Squarified-enough treemap: recursively splits the remaining area along its
 * longer side, alternating, so cell area is proportional to value. Coordinates
 * are percentages of the container.
 */
export function treemap(items: ReadonlyArray<{ key: string; value: number }>): TreeCell[] {
  const positive = items.filter(i => i.value > 0).sort((a, b) => b.value - a.value);
  const out: TreeCell[] = [];
  function split(list: typeof positive, x: number, y: number, w: number, h: number): void {
    if (list.length === 0) return;
    if (list.length === 1) {
      out.push({ key: list[0]!.key, value: list[0]!.value, x, y, w, h });
      return;
    }
    const total = list.reduce((a, b) => a + b.value, 0);
    let acc = 0;
    let cut = 0;
    while (cut < list.length - 1 && acc + list[cut]!.value <= total / 2) {
      acc += list[cut]!.value;
      cut += 1;
    }
    if (cut === 0) {
      acc = list[0]!.value;
      cut = 1;
    }
    const share = acc / total;
    if (w >= h) {
      split(list.slice(0, cut), x, y, w * share, h);
      split(list.slice(cut), x + w * share, y, w * (1 - share), h);
    } else {
      split(list.slice(0, cut), x, y, w, h * share);
      split(list.slice(cut), x, y + h * share, w, h * (1 - share));
    }
  }
  split(positive, 0, 0, 100, 100);
  return out;
}

// ── Campaign overviews (GET /v1/campaigns/{id}/overview) ─────────────────────

export const WINDOWS = [7, 30, 90] as const;
export type WindowDays = (typeof WINDOWS)[number];

const DAY_MS = 86_400_000;

/** A half-open period [start, end) of `days` days. */
export interface ValueWindow {
  readonly days: number;
  readonly start: Date;
  readonly end: Date;
}

/**
 * The selected window ending at `anchor`, and the immediately preceding window
 * of equal length (its end is the current window's start, so no event is in both).
 */
export function valueWindows(days: number, anchor: Date): { current: ValueWindow; previous: ValueWindow } {
  const end = new Date(anchor.getTime());
  const start = new Date(end.getTime() - days * DAY_MS);
  return { current: { days, start, end }, previous: { days, start: new Date(start.getTime() - days * DAY_MS), end: start } };
}

/** "Sep 23 – Oct 23" (years added only when the window crosses one or is not this year). */
export function rangeLabel(window: ValueWindow, now: Date = new Date()): string {
  const sameYear = window.start.getFullYear() === window.end.getFullYear() && window.end.getFullYear() === now.getFullYear();
  const opts: Intl.DateTimeFormatOptions = sameYear ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' };
  return `${window.start.toLocaleDateString('en-US', opts)} – ${window.end.toLocaleDateString('en-US', opts)}`;
}

/**
 * One bucket per day of the window, counted from its start, so two windows of
 * equal length line up index by index. Events outside the window are ignored.
 */
export function windowSeries(events: readonly ValueEvent[], window: ValueWindow): DayPoint[] {
  const out = Array.from({ length: window.days }, (_, i) => {
    const day = new Date(window.start.getTime() + i * DAY_MS);
    return { day: dayKey(day), total: 0, events: 0 };
  });
  const from = window.start.getTime();
  for (const event of events) {
    if (!event.occurredAt) continue;
    const index = Math.floor((event.occurredAt.getTime() - from) / DAY_MS);
    const bucket = out[index];
    if (index < 0 || !bucket) continue;
    bucket.events += 1;
    bucket.total += event.amount ?? 0;
  }
  return out;
}

/** Value types that are revenue kept or grown, as opposed to costs and losses avoided. */
export const REVENUE_VALUE_TYPES: ReadonlySet<string> = new Set(['retained_revenue', 'expansion_revenue']);

export interface Headline {
  /** Sum of priced events (one currency); null when no event carried an amount. */
  readonly value: number | null;
  /** Sum of priced retained/expansion revenue events; null when none carried an amount. */
  readonly revenue: number | null;
  readonly events: number;
  readonly priced: number;
  /** Value per priced event; null when no event carried an amount. */
  readonly average: number | null;
}

/** Headline figures from one window's single-currency read. */
export function headline(read: OneCurrencyRead): Headline {
  let value = 0;
  let revenue = 0;
  let priced = 0;
  let pricedRevenue = 0;
  for (const e of read.events) {
    if (e.amount === null) continue;
    priced += 1;
    value += e.amount;
    if (REVENUE_VALUE_TYPES.has(e.valueType)) {
      pricedRevenue += 1;
      revenue += e.amount;
    }
  }
  return {
    value: priced ? value : null,
    revenue: pricedRevenue ? revenue : null,
    events: read.events.length,
    priced,
    average: priced ? value / priced : null,
  };
}

export type Delta =
  | { readonly kind: 'change'; readonly ratio: number }
  | { readonly kind: 'new' }
  | { readonly kind: 'unavailable'; readonly reason: string };

/** Relative change from the previous figure; never divides by zero or compares a missing figure. */
export function compareFigures(current: number | null, previous: number | null): Delta {
  if (current === null && previous === null) return { kind: 'unavailable', reason: 'no amounts in either period' };
  if (current === null) return { kind: 'unavailable', reason: 'no amounts this period' };
  if (previous === null) return { kind: 'unavailable', reason: 'no amounts in the previous period' };
  if (previous === 0) return current === 0 ? { kind: 'change', ratio: 0 } : { kind: 'new' };
  return { kind: 'change', ratio: (current - previous) / Math.abs(previous) };
}

export interface CampaignValue {
  readonly id: string;
  readonly name: string;
  readonly platform: string | null;
  readonly status: string | null;
  /** null = the overview read failed for this campaign. */
  readonly overview: {
    readonly spend: number | null;
    readonly gross: number | null;
    readonly net: number | null;
    readonly roas: number | null;
    readonly attributed: number | null;
    readonly converted: number | null;
    readonly observed: number | null;
  } | null;
}

export function parseCampaignOverview(payload: unknown): NonNullable<CampaignValue['overview']> {
  const d = asRecord(payload);
  return {
    spend: num(d['spend_usd']),
    gross: num(d['gross_attributed_revenue'] ?? d['attributed_gross_revenue']),
    net: num(d['net_attributed_revenue'] ?? d['attributed_net_revenue']),
    roas: num(d['roas']),
    attributed: num(d['attributed_count']),
    converted: num(d['converted_count']),
    observed: num(d['observed_count']),
  };
}

export interface OneCurrencyRead {
  /** Events with amounts kept only in `currency`; amounts in other currencies become null. */
  readonly events: ValueEvent[];
  /** The currency the amounts are in (null when events carry no currency code). */
  readonly currency: string | null;
  /** Priced events whose amount was set aside because it is in another currency. */
  readonly setAside: number;
  readonly otherCurrencies: string[];
}

/**
 * Value events carry an optional, unrestricted currency and there is no
 * exchange-rate source here, so amounts are only ever summed within one
 * currency: the one most priced events use. Events in other currencies are
 * still counted, never added to that total.
 */
export function inOneCurrency(events: readonly ValueEvent[]): OneCurrencyRead {
  const code = (e: ValueEvent) => (e.currency ? e.currency.toUpperCase() : null);
  const counts = new Map<string | null, number>();
  for (const e of events) if (e.amount !== null) counts.set(code(e), (counts.get(code(e)) ?? 0) + 1);
  if (counts.size <= 1) return { events: [...events], currency: counts.size ? [...counts.keys()][0]! : null, setAside: 0, otherCurrencies: [] };
  const [currency] = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]!;
  let setAside = 0;
  const kept = events.map(e => {
    if (e.amount === null || code(e) === currency) return e;
    setAside += 1;
    return { ...e, amount: null };
  });
  const otherCurrencies = [...counts.keys()].filter(k => k !== currency).map(k => k ?? 'unspecified');
  return { events: kept, currency, setAside, otherCurrencies };
}
