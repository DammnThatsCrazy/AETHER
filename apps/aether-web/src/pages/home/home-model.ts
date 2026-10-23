import { formatUSD } from '@aether/ui';
import type { TenantIntegrationItem } from '@aether-app/features/integrations';
import type { TenantEconomicOverview } from '@aether-app/lib/api/endpoints';
import type { CampaignSummary } from '@aether-app/pages/campaigns/campaign-model';

/**
 * Pure read-model helpers for Home. Nothing here invents a value: every
 * function returns `null` (rendered as "not reported") when the read does not
 * carry the number.
 */

export function num(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN;
  return Number.isFinite(n) ? n : null;
}

export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return value.toLocaleString('en-US');
}

export function relative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'never';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const mins = Math.round((now - t) / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function shortStamp(iso: string | number | null | undefined): string {
  if (iso === null || iso === undefined) return '—';
  const t = typeof iso === 'number' ? iso : Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  return new Date(t).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function tokenKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, '');
}

/**
 * Human name for a campaign's source platform. Campaigns are imported from
 * connected systems, so the matching integration's display name is the
 * authoritative label; an unmatched token is shown in words rather than as a
 * raw identifier (`google_ads` → "Google Ads").
 */
export function platformLabel(token: string, integrations: readonly TenantIntegrationItem[]): string {
  const key = tokenKey(token);
  if (!key) return '';
  const match = integrations.find(i => tokenKey(i.family) === key || tokenKey(i.display_name) === key);
  if (match) return match.display_name;
  return token
    .replace(/[_-]+/g, ' ')
    .trim()
    .replace(/\b\w/g, ch => ch.toUpperCase());
}

export function needsAttention(item: TenantIntegrationItem): boolean {
  return item.enabled && /fail|error|degraded/i.test(item.sync_status);
}

// ── Economic KPIs ───────────────────────────────────────────────────────────

export interface EconomicKpis {
  /** Attributed revenue in USD, or null when nothing has been attributed. */
  readonly revenue: number | null;
  /** Campaign spend in USD, or null when no spend records exist. */
  readonly spend: number | null;
  /** Attributed revenue ÷ spend, only when both are reported and spend > 0. */
  readonly roas: number | null;
  readonly noAttribution: boolean;
  readonly noSpend: boolean;
  readonly failed: boolean;
}

export function economicKpis(overview: TenantEconomicOverview | null | undefined): EconomicKpis | null {
  if (!overview) return null;
  const codes = new Set((overview.warnings ?? []).map(w => w.code));
  const failed = codes.has('COMPUTATION_ERROR');
  const noAttribution = codes.has('NO_ATTRIBUTION_DATA');
  const noSpend = codes.has('NO_SPEND_DATA');
  const rawRevenue = num(overview.attributed_revenue?.usd_amount);
  const rawSpend = num(overview.campaign_spend?.usd_amount);
  const revenue = failed || noAttribution ? null : rawRevenue;
  const spend = failed || noSpend || rawSpend === null || rawSpend <= 0 ? null : rawSpend;
  const roas = revenue !== null && spend !== null ? revenue / spend : null;
  return { revenue, spend, roas, noAttribution, noSpend, failed };
}

// ── Since you last visited ───────────────────────────────────────────────────

const VISIT_PREFIX = 'aether.home.lastVisit:';

/** Read the previous visit time for this viewer (per-viewer convenience; storage may be blocked). */
export function readLastVisit(scope: string): number | null {
  try {
    const raw = window.localStorage.getItem(VISIT_PREFIX + scope);
    const t = raw ? Number(raw) : NaN;
    return Number.isFinite(t) ? t : null;
  } catch {
    return null;
  }
}

export function writeLastVisit(scope: string, at: number): void {
  try {
    window.localStorage.setItem(VISIT_PREFIX + scope, String(at));
  } catch {
    // Storage blocked (private window, preview): the line simply reads "first visit" next time.
  }
}

export interface SinceVisit {
  readonly campaignsImported: number;
  readonly connectionsSynced: number;
  readonly connectionsFailing: number;
  readonly checksRan: boolean;
}

function after(iso: string | null | undefined, since: number): boolean {
  if (!iso) return false;
  const t = Date.parse(iso);
  return !Number.isNaN(t) && t > since;
}

export function sinceVisit(
  since: number,
  campaigns: readonly Record<string, unknown>[],
  integrations: readonly TenantIntegrationItem[],
  readinessRecordedAt: string | null | undefined,
): SinceVisit {
  return {
    campaignsImported: campaigns.filter(c => after(typeof c['created_at'] === 'string' ? c['created_at'] : null, since)).length,
    connectionsSynced: integrations.filter(i => after(i.last_synced_at, since)).length,
    connectionsFailing: integrations.filter(i => needsAttention(i)).length,
    checksRan: after(readinessRecordedAt, since),
  };
}

// ── Activity timeline ───────────────────────────────────────────────────────

export interface ActivityMoment {
  readonly key: string;
  readonly at: number;
  readonly title: string;
  readonly detail: string;
  readonly tone: 'blue' | 'sage' | 'amber' | 'solar';
}

/** Dated moments the reads actually carry: imports, syncs and readiness runs. */
export function activityMoments(
  campaigns: readonly CampaignSummary[],
  campaignCreated: ReadonlyMap<string, string>,
  integrations: readonly TenantIntegrationItem[],
  readinessRecordedAt: string | null | undefined,
  readinessReady: boolean,
  limit = 5,
): ActivityMoment[] {
  const out: ActivityMoment[] = [];
  for (const c of campaigns) {
    const iso = campaignCreated.get(c.id);
    const t = iso ? Date.parse(iso) : NaN;
    if (!Number.isNaN(t)) out.push({ key: `c:${c.id}`, at: t, title: `${c.name} imported`, detail: c.status, tone: 'blue' });
  }
  for (const i of integrations) {
    const t = i.last_synced_at ? Date.parse(i.last_synced_at) : NaN;
    if (!Number.isNaN(t)) {
      const bad = needsAttention(i);
      out.push({ key: `i:${i.id}`, at: t, title: `${i.display_name} ${bad ? 'sync failed' : 'synced'}`, detail: i.sync_status.replace(/_/g, ' '), tone: bad ? 'amber' : 'sage' });
    }
  }
  const rt = readinessRecordedAt ? Date.parse(readinessRecordedAt) : NaN;
  if (!Number.isNaN(rt)) out.push({ key: 'readiness', at: rt, title: 'Graph checks ran', detail: readinessReady ? 'all checks passed' : 'some checks pending', tone: 'solar' });
  return out.sort((a, b) => b.at - a.at).slice(0, limit).reverse();
}

/** Compact USD ("$284K", "$1.2M") through the canonical value formatter. */
export function usdShort(value: number): string {
  return formatUSD(value, { compact: true, maximumFractionDigits: 1, minimumFractionDigits: 0 });
}
