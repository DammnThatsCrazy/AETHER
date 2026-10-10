/**
 * Status data for /status. Live state comes from the existing health endpoint
 * (VITE_STATUS_API_URL; parsing carried over from apps/status). History
 * comes from VITE_STATUS_HISTORY_URL?days=90 when that feed exists. Missing or
 * failing sources are reported as such; nothing defaults to operational.
 */

export type HealthState = 'operational' | 'degraded' | 'outage' | 'unknown';
export type DayStatus = 'operational' | 'degraded' | 'outage' | 'no_data';

export interface HealthComponent {
  key: string;
  label: string;
  state: HealthState;
  detail: string;
}

export interface HealthSnapshot {
  state: HealthState;
  /** 'unconfigured' when no endpoint is set; 'unreachable' when the request failed. */
  source: 'live' | 'unconfigured' | 'unreachable' | 'unverified';
  detail: string;
  checkedAt: string | null;
  components: HealthComponent[];
}

export interface HistoryDay {
  date: string;
  status: DayStatus;
  uptimePct: number | null;
}

export interface Incident {
  id: string;
  title: string;
  status: string;
  startedAt: string;
  resolvedAt: string | null;
  components: string[];
}

export interface StatusHistory {
  components: Record<string, HistoryDay[]>;
  incidents: Incident[];
}

export const COMPONENT_LABELS: Record<string, string> = {
  api: 'Aether API',
  admin: 'Tenant administration',
  analytics: 'Analytics and views',
  identity: 'People and connections',
  ingestion: 'Data intake',
  provider_credentials: 'Connected tools',
  notification: 'Messages and workflows',
  consent: 'Consent and data separation',
  ml_serving: 'Model serving',
  agent: 'AI agents',
  campaign: 'Campaigns',
  commerce: 'Commerce',
  rewards: 'Rewards',
};

export type ComponentGroup = 'product' | 'connections' | 'supporting';

const GROUP_OF: Record<string, ComponentGroup> = {
  api: 'product',
  admin: 'product',
  analytics: 'product',
  identity: 'product',
  ingestion: 'connections',
  provider_credentials: 'connections',
  notification: 'connections',
};

export const groupOf = (key: string): ComponentGroup => GROUP_OF[key] ?? 'supporting';

export function stateFromBackend(value: unknown): HealthState {
  if (value === 'ok' || value === 'healthy') return 'operational';
  if (value === 'degraded') return 'degraded';
  if (value === 'down') return 'outage';
  return 'unknown';
}

function componentDetail(value: unknown): string {
  const fallback = 'The monitored service did not provide component detail.';
  if (!value || typeof value !== 'object') return fallback;
  const signals = (value as { signals?: unknown }).signals;
  if (!signals || typeof signals !== 'object') return fallback;
  for (const signal of Object.values(signals)) {
    const detail = signal && typeof signal === 'object' ? (signal as { detail?: unknown }).detail : undefined;
    if (typeof detail === 'string' && detail.trim()) return detail;
  }
  return 'The monitored service reported a component state without additional detail.';
}

export function componentsFromPayload(payload: { components?: unknown }): HealthComponent[] {
  if (!payload.components || typeof payload.components !== 'object') return [];
  return Object.entries(payload.components as Record<string, unknown>)
    .map(([key, value]) => ({
      key,
      label: COMPONENT_LABELS[key] ?? key.replace(/_/g, ' '),
      state: stateFromBackend(value && typeof value === 'object' ? (value as { status?: unknown }).status : undefined),
      detail: componentDetail(value),
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

const DETAIL: Record<HealthState, string> = {
  operational: 'The monitored API and its reported component surfaces are operational.',
  degraded: 'The API is reachable, but one or more reported components are degraded.',
  outage: 'The API reports that one or more components are down.',
  unknown: 'The monitored API returned a health state this page cannot verify.',
};

export async function checkHealth(url: string, fetchImpl: typeof fetch = fetch, signal?: AbortSignal): Promise<HealthSnapshot> {
  if (!url) {
    return { state: 'unknown', source: 'unconfigured', detail: 'The live monitoring source has not been connected to this status page.', checkedAt: null, components: [] };
  }
  const checkedAt = new Date().toISOString();
  let response: Response;
  try {
    response = await fetchImpl(url, { signal, headers: { Accept: 'application/json' } });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    return {
      state: 'outage',
      source: 'unreachable',
      detail: 'The health endpoint could not be reached. This may be an outage or a network problem between this page and the API.',
      checkedAt,
      components: [],
    };
  }
  if (!response.ok) {
    return { state: 'degraded', source: 'live', detail: 'The monitored API health endpoint returned a non-success response.', checkedAt, components: [] };
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!body || typeof body !== 'object') {
    return { state: 'unknown', source: 'unverified', detail: 'The endpoint responded, but its health payload could not be verified.', checkedAt, components: [] };
  }
  const payload = body as { status?: unknown; components?: unknown };
  const state = stateFromBackend(payload.status);
  return { state, source: 'live', detail: DETAIL[state], checkedAt, components: componentsFromPayload(payload) };
}

const DAY_STATUSES: DayStatus[] = ['operational', 'degraded', 'outage', 'no_data'];

/** Parse the history feed; anything malformed becomes no_data rather than green. */
export function parseHistory(body: unknown): StatusHistory {
  const out: StatusHistory = { components: {}, incidents: [] };
  if (!body || typeof body !== 'object') return out;
  const { components, incidents } = body as { components?: unknown; incidents?: unknown };
  if (Array.isArray(components)) {
    for (const c of components) {
      if (!c || typeof c !== 'object' || typeof (c as { name?: unknown }).name !== 'string') continue;
      const days = Array.isArray((c as { days?: unknown }).days) ? ((c as { days: unknown[] }).days) : [];
      out.components[(c as { name: string }).name] = days.map((d) => {
        const rec = (d && typeof d === 'object' ? d : {}) as { date?: unknown; status?: unknown; uptime_pct?: unknown };
        const status = DAY_STATUSES.includes(rec.status as DayStatus) ? (rec.status as DayStatus) : 'no_data';
        return {
          date: typeof rec.date === 'string' ? rec.date : '',
          status,
          uptimePct: typeof rec.uptime_pct === 'number' && status !== 'no_data' ? rec.uptime_pct : null,
        };
      });
    }
  }
  if (Array.isArray(incidents)) {
    for (const i of incidents) {
      const rec = (i && typeof i === 'object' ? i : {}) as Record<string, unknown>;
      if (typeof rec.id !== 'string' || typeof rec.title !== 'string' || typeof rec.started_at !== 'string') continue;
      out.incidents.push({
        id: rec.id,
        title: rec.title,
        status: typeof rec.status === 'string' ? rec.status : 'unknown',
        startedAt: rec.started_at,
        resolvedAt: typeof rec.resolved_at === 'string' ? rec.resolved_at : null,
        components: Array.isArray(rec.components) ? rec.components.filter((x): x is string => typeof x === 'string') : [],
      });
    }
  }
  return out;
}

export async function fetchHistory(url: string, days: number, fetchImpl: typeof fetch = fetch, signal?: AbortSignal): Promise<StatusHistory | null> {
  if (!url) return null;
  try {
    const sep = url.includes('?') ? '&' : '?';
    const res = await fetchImpl(`${url}${sep}days=${days}`, { signal, headers: { Accept: 'application/json' } });
    if (!res.ok) return null;
    return parseHistory(await res.json());
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    return null;
  }
}

/** Exactly `days` entries ending today; days the feed omits are no_data. */
export function fillDays(days: HistoryDay[] | undefined, count: number, today: Date): HistoryDay[] {
  const byDate = new Map((days ?? []).map((d) => [d.date, d]));
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - (count - 1 - i)));
    const date = d.toISOString().slice(0, 10);
    return byDate.get(date) ?? { date, status: 'no_data', uptimePct: null };
  });
}

/** Mean uptime over days with data; null when there are none. */
export function uptime(days: HistoryDay[]): number | null {
  const known = days.filter((d) => d.uptimePct !== null);
  if (!known.length) return null;
  return known.reduce((sum, d) => sum + (d.uptimePct ?? 0), 0) / known.length;
}
