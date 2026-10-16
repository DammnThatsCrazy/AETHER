import type { Tone } from '@aether-app/components/ae-ui';
import type { InboxNotification } from '@aether-app/features/notifications/use-inbox';

/**
 * Pure helpers for the Signals page. They only arrange inbox rows the backend
 * returned; nothing here invents a count, a score or a sample signal.
 */

/** Display level. The backend severity (P0–P3 / info) is always shown beside it. */
export type SignalLevel = 'critical' | 'watch' | 'info';

export const LEVELS: readonly SignalLevel[] = ['critical', 'watch', 'info'];

export const LEVEL_LABEL: Record<SignalLevel, string> = { critical: 'Critical', watch: 'Watch', info: 'Info' };

export const LEVEL_TONE: Record<SignalLevel, Tone> = { critical: 'ember', watch: 'amber', info: 'blue' };

/**
 * Backend `NotificationSeverity` → display level: P0/P1 page someone (critical),
 * P2/P3 are worth a look (watch), `info` is informational. Unknown values fall
 * back to info, matching the backend's own coercion.
 */
export function signalLevel(severity: string | null | undefined): SignalLevel {
  const s = (severity ?? '').trim().toUpperCase();
  if (s === 'P0' || s === 'P1') return 'critical';
  if (s === 'P2' || s === 'P3') return 'watch';
  return 'info';
}

export function severityCode(severity: string | null | undefined): string {
  const s = (severity ?? '').trim();
  return s ? (s.toLowerCase() === 'info' ? 'info' : s.toUpperCase()) : 'info';
}

export type RangeHours = 24 | 168 | 720;

export const RANGES: readonly { readonly hours: RangeHours; readonly label: string }[] = [
  { hours: 24, label: '24 hours' },
  { hours: 168, label: '7 days' },
  { hours: 720, label: '30 days' },
];

export function ageHours(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, (now - t) / 3_600_000);
}

export function inRange(row: InboxNotification, hours: RangeHours, now: number): boolean {
  const age = ageHours(row.created_at, now);
  return age !== null && age <= hours;
}

export function relativeAge(iso: string | null | undefined, now: number): string {
  const h = ageHours(iso, now);
  if (h === null) return 'time not recorded';
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m ago`;
  if (h < 48) return `${Math.round(h)}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export interface TimelineBucket {
  readonly key: string;
  readonly heading: string;
  readonly note: string;
  readonly items: readonly InboxNotification[];
}

const BUCKETS: readonly { key: string; heading: string; note: string; test: (h: number) => boolean }[] = [
  { key: 'hour', heading: 'Last hour', note: 'just now', test: h => h < 1 },
  { key: 'today', heading: 'Earlier today', note: 'last 24 hours', test: h => h >= 1 && h < 24 },
  { key: 'week', heading: 'Earlier this week', note: 'days 2 to 7', test: h => h >= 24 && h < 168 },
  { key: 'month', heading: 'Earlier this month', note: 'older', test: h => h >= 168 },
];

/** Newest-first rows grouped into the design's timeline buckets (empty buckets dropped). */
export function timeline(rows: readonly InboxNotification[], now: number): TimelineBucket[] {
  const sorted = [...rows].sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0));
  return BUCKETS.map(b => ({
    key: b.key,
    heading: b.heading,
    note: b.note,
    items: sorted.filter(r => {
      const h = ageHours(r.created_at, now);
      return h !== null && b.test(h);
    }),
  })).filter(b => b.items.length > 0);
}

export function categoryLabel(category: string | null | undefined): string {
  const c = (category ?? '').trim();
  if (!c) return 'Uncategorised';
  const words = c.replace(/[_-]+/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * App routes a signal's `link` may open. Producers also store API paths (e.g.
 * export downloads under `/v1/…`); those are not pages, so they get no link.
 */
const APP_ROUTE_PREFIXES = [
  '/home', '/users', '/campaigns', '/campaign-intelligence', '/clusters', '/agents', '/agent-access',
  '/explore', '/settings', '/imports', '/deployments', '/data-quality', '/security', '/audit-exports',
  '/billing', '/usage-plan', '/notifications', '/geo', '/value-review', '/system-status', '/delivery',
  '/rewards', '/suggestions', '/identity', '/stablecoins', '/derivatives', '/payment-rails', '/interoperability',
];

export function appLink(link: string | null | undefined): string | null {
  if (!link) return null;
  const l = link.trim();
  if (!l.startsWith('/') || l.startsWith('//')) return null;
  const path = l.split(/[?#]/)[0] ?? '';
  return APP_ROUTE_PREFIXES.some(p => path === p || path.startsWith(`${p}/`)) ? l : null;
}

export function countByLevel(rows: readonly InboxNotification[]): Record<SignalLevel, number> {
  const out: Record<SignalLevel, number> = { critical: 0, watch: 0, info: 0 };
  for (const r of rows) out[signalLevel(r.severity)] += 1;
  return out;
}

const LEVEL_ORDER: Record<SignalLevel, number> = { critical: 0, watch: 1, info: 2 };

/** Highest level first, then newest. */
export function byUrgency(a: InboxNotification, b: InboxNotification): number {
  return (
    LEVEL_ORDER[signalLevel(a.severity)] - LEVEL_ORDER[signalLevel(b.severity)] ||
    (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0)
  );
}
