import type { JourneyMeta, JourneyStep } from '@aether-app/features/journey';

/**
 * Read model shared by the Journeys and Episodes pages (Claude Design:
 * Aether Journeys, Aether Episodes). Everything here is derived from one
 * profile's compiled unified journey (`GET /v1/profile/{id}/unified-journey`);
 * nothing is invented. Where the backend does not classify something (an
 * actor, an episode boundary) the derivation rule is explicit and named.
 */

type Row = Record<string, unknown>;

function rec(v: unknown): Row {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Row) : {};
}

function text(v: unknown): string | null {
  if (typeof v === 'string') return v.trim() ? v : null;
  if (typeof v === 'number' && Number.isFinite(v)) return String(v);
  return null;
}

export function humanizeToken(v: string): string {
  return v.replace(/[_-]+/g, ' ');
}

// ── Journey payload ─────────────────────────────────────────────────────────

export interface JourneySummary {
  readonly journeyId: string | null;
  /** Compiler state: `open`, `converted` or `empty` today. */
  readonly state: string | null;
  readonly stepCount: number | null;
  readonly startedAt: string | null;
  readonly endedAt: string | null;
  readonly convertedAt: string | null;
  readonly hasAgent: boolean;
  readonly hasWeb3: boolean;
  readonly hasX402: boolean;
}

export interface ProfileJourney {
  /** Steps in chronological order. */
  readonly steps: JourneyStep[];
  readonly meta: JourneyMeta | null;
  readonly summary: JourneySummary | null;
  /** Dimensions the aggregator could not read (e.g. attribution credits). */
  readonly degraded: string[];
  /** True when the step page was truncated by the read limit. */
  readonly hasMore: boolean;
}

export function stepTime(step: JourneyStep): number | null {
  const t = Date.parse(step.occurred_at);
  return Number.isNaN(t) ? null : t;
}

export function parseProfileJourney(raw: unknown): ProfileJourney {
  const r = rec(raw);
  const steps = (Array.isArray(r.steps) ? r.steps : [])
    .filter((s): s is JourneyStep => !!s && typeof s === 'object' && typeof (s as Row).step_id === 'string')
    .map((s, i) => ({ s, i }))
    .sort((a, b) => {
      const ta = stepTime(a.s);
      const tb = stepTime(b.s);
      if (ta !== null && tb !== null && ta !== tb) return ta - tb;
      const pa = typeof a.s.step_position === 'number' ? a.s.step_position : a.i;
      const pb = typeof b.s.step_position === 'number' ? b.s.step_position : b.i;
      return pa - pb;
    })
    .map(x => x.s);
  const metaRaw = rec(r.meta);
  const meta = typeof metaRaw.journey_id === 'string' ? (metaRaw as unknown as JourneyMeta) : null;
  const s = rec(r.summary);
  const summary: JourneySummary | null = Object.keys(s).length === 0 ? null : {
    journeyId: text(s.journey_id),
    state: text(s.journey_state),
    stepCount: typeof s.step_count === 'number' ? s.step_count : null,
    startedAt: text(s.started_at),
    endedAt: text(s.ended_at),
    convertedAt: text(s.converted_at),
    hasAgent: s.has_agent === true,
    hasWeb3: s.has_web3 === true,
    hasX402: s.has_x402 === true,
  };
  const pagination = rec(r.pagination);
  return {
    steps,
    meta,
    summary,
    degraded: Array.isArray(r.degraded_dimensions) ? r.degraded_dimensions.map(String) : [],
    hasMore: pagination.has_more === true || r.has_more === true,
  };
}

// ── Actors (swimlanes) ──────────────────────────────────────────────────────

export type Lane = 'person' | 'agent' | 'system' | 'unclassified';

export const LANES: ReadonlyArray<{ readonly key: Lane; readonly label: string; readonly color: string }> = [
  { key: 'person', label: 'Person', color: 'var(--ae-blue)' },
  { key: 'agent', label: 'Agent', color: 'var(--ae-violet)' },
  { key: 'system', label: 'System', color: 'var(--ae-mute)' },
  { key: 'unclassified', label: 'Unclassified', color: 'var(--ae-faint)' },
];

const PERSON_ACTORS = new Set(['human', 'person', 'user', 'customer']);

/**
 * Lane for a step from the compiler's `actor_type`. An agent-family step with
 * no actor type is still an agent step; anything else unclassified stays
 * unclassified rather than being guessed into a lane.
 */
export function stepLane(step: JourneyStep): Lane {
  const actor = (step.actor_type ?? '').trim().toLowerCase();
  if (actor) {
    if (actor.includes('agent')) return 'agent';
    if (PERSON_ACTORS.has(actor)) return 'person';
    return 'system';
  }
  if (step.activity_family === 'agent') return 'agent';
  return 'unclassified';
}

export function laneMeta(lane: Lane) {
  return LANES.find(l => l.key === lane)!;
}

/** Lanes to draw: the three design lanes plus Unclassified only when used. */
export function visibleLanes(steps: readonly JourneyStep[]) {
  const used = new Set(steps.map(stepLane));
  return LANES.filter(l => l.key !== 'unclassified' || used.has('unclassified'));
}

export function laneMix(steps: readonly JourneyStep[]) {
  const total = steps.length;
  return LANES.map(l => {
    const n = steps.filter(s => stepLane(s) === l.key).length;
    return { ...l, n, pct: total ? Math.round((n / total) * 100) : 0 };
  }).filter(l => l.n > 0);
}

// ── Language ────────────────────────────────────────────────────────────────

export function stepLabel(step: JourneyStep): string {
  return step.displayLabel?.trim() || humanizeToken(step.activity_type || 'step');
}

export function stepWho(step: JourneyStep): string {
  const lane = stepLane(step);
  if (lane === 'agent') return step.agent_id ? `Agent ${step.agent_id}` : 'Agent';
  if (lane === 'person') return 'Person';
  if (lane === 'system') return humanizeToken(step.actor_type ?? 'system');
  return 'Actor not classified';
}

/** One plain sentence built only from fields the step reports. */
export function stepPlain(step: JourneyStep): string {
  const parts = [`${stepWho(step)}: ${stepLabel(step)}`];
  if (step.source) parts.push(`from ${step.source}`);
  if (step.domain) parts.push(`on ${step.domain}`);
  if (step.channel) parts.push(`via ${humanizeToken(step.channel)}`);
  if (step.ai_provider) parts.push(`through ${step.ai_provider}${step.ai_product ? ` ${step.ai_product}` : ''}`);
  let sentence = parts.join(' ');
  if (step.activity_status && step.activity_status !== 'observed') sentence += ` (${humanizeToken(step.activity_status)})`;
  return `${sentence}.`;
}

const RAW_FIELDS: ReadonlyArray<keyof JourneyStep> = [
  'step_id', 'activity_family', 'activity_type', 'activity_status', 'actor_type', 'source_class',
  'transition_type', 'journey_role', 'channel', 'source', 'domain', 'ai_provider', 'ai_product',
  'referral_mediation_type', 'campaign_id', 'agent_id', 'session_id', 'wallet_id', 'chain_id', 'dapp_id',
  'verification_level', 'evidence_confidence', 'identity_method', 'identity_confidence',
  'attributed_net_revenue', 'risk_tier', 'fraud_disposition', 'occurred_at',
];

/** The step's reported fields as `[field, value]`, nulls omitted. */
export function stepRaw(step: JourneyStep): Array<readonly [string, string]> {
  const out: Array<readonly [string, string]> = [];
  for (const f of RAW_FIELDS) {
    const v = step[f];
    if (v === null || v === undefined || v === '') continue;
    out.push([f, String(v)]);
  }
  return out;
}

// ── Time ────────────────────────────────────────────────────────────────────

export function formatDuration(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms) || ms < 0) return '—';
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

export function formatWhen(t: number | null): string {
  if (t === null) return 'time not reported';
  return new Date(t).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function formatClock(t: number | null): string {
  if (t === null) return '—';
  return new Date(t).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function span(steps: readonly JourneyStep[]): { start: number | null; end: number | null; ms: number | null } {
  const times = steps.map(stepTime).filter((t): t is number => t !== null);
  if (times.length === 0) return { start: null, end: null, ms: null };
  const start = Math.min(...times);
  const end = Math.max(...times);
  return { start, end, ms: end - start };
}

/** Gap from each step to the next one (null for the last step or a missing time). */
export function gapsAfter(steps: readonly JourneyStep[]): Array<number | null> {
  return steps.map((s, i) => {
    const next = steps[i + 1];
    if (!next) return null;
    const a = stepTime(s);
    const b = stepTime(next);
    return a === null || b === null ? null : Math.max(0, b - a);
  });
}

/** The longest waits between consecutive steps ("Where the time went"). */
export function longestGaps(steps: readonly JourneyStep[], limit = 4) {
  const gaps = gapsAfter(steps);
  const total = gaps.reduce<number>((acc, g) => acc + (g ?? 0), 0);
  return gaps
    .map((g, i) => ({ g, i }))
    .filter((x): x is { g: number; i: number } => x.g !== null && x.g > 0)
    .sort((a, b) => b.g - a.g)
    .slice(0, limit)
    .map(({ g, i }) => ({
      from: stepLabel(steps[i]!),
      to: stepLabel(steps[i + 1]!),
      ms: g,
      pct: total ? Math.round((g / total) * 100) : 0,
    }));
}

// ── Density ─────────────────────────────────────────────────────────────────

export interface Density {
  readonly bins: number[];
  /** Width of one bin in ms (60_000 means "events per minute"). */
  readonly binMs: number;
  readonly start: number | null;
}

export function density(steps: readonly JourneyStep[], maxBins = 30): Density {
  const { start, ms } = span(steps);
  if (start === null || ms === null) return { bins: [], binMs: 0, start: null };
  const minuteBins = Math.max(1, Math.ceil((ms + 1) / 60_000));
  const binMs = minuteBins <= maxBins ? 60_000 : Math.ceil((ms + 1) / maxBins);
  const count = Math.max(1, Math.ceil((ms + 1) / binMs));
  const bins = new Array<number>(count).fill(0);
  for (const s of steps) {
    const t = stepTime(s);
    if (t === null) continue;
    const i = Math.min(count - 1, Math.floor((t - start) / binMs));
    bins[i] = (bins[i] ?? 0) + 1;
  }
  return { bins, binMs, start };
}

export function densityLabel(d: Density): string {
  return d.binMs === 60_000 ? 'Events per minute' : `Events per ${formatDuration(d.binMs)}`;
}

// ── Systems and participants ────────────────────────────────────────────────

/** Distinct systems the steps report: AI providers, sources and domains. */
export function systemsTouched(steps: readonly JourneyStep[], limit = 8): string[] {
  const seen = new Map<string, string>();
  for (const s of steps) {
    for (const v of [s.ai_provider, s.source, s.domain]) {
      if (!v) continue;
      const k = v.toLowerCase();
      if (!seen.has(k)) seen.set(k, v);
    }
  }
  return [...seen.values()].slice(0, limit);
}

export interface Participants {
  readonly agents: string[];
  readonly campaigns: string[];
  readonly wallets: string[];
  readonly sessions: string[];
}

function distinct(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((v): v is string => !!v))];
}

export function participants(steps: readonly JourneyStep[]): Participants {
  return {
    agents: distinct(steps.map(s => s.agent_id)),
    campaigns: distinct(steps.map(s => s.campaign_id)),
    wallets: distinct(steps.map(s => s.wallet_id)),
    sessions: distinct(steps.map(s => s.session_id)),
  };
}

/** Sum of attributed net revenue; null when no step reports any. */
export function attributedRevenue(steps: readonly JourneyStep[]): number | null {
  const vals = steps.map(s => s.attributed_net_revenue).filter((v): v is number => typeof v === 'number');
  return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
}

// ── Episodes ────────────────────────────────────────────────────────────────

/**
 * Episode boundary used until the backend exposes Episode 360: consecutive
 * steps less than this far apart belong to the same episode.
 */
export const EPISODE_GAP_MS = 30 * 60_000;

export interface EpisodeSession {
  readonly id: string | null;
  readonly steps: JourneyStep[];
}

export interface Episode {
  /** Stable id: the episode's first step id. */
  readonly id: string;
  /** 1-based position in the journey. */
  readonly number: number;
  readonly steps: JourneyStep[];
  readonly start: number | null;
  readonly end: number | null;
  readonly sessions: EpisodeSession[];
}

export function segmentEpisodes(steps: readonly JourneyStep[]): Episode[] {
  const groups: JourneyStep[][] = [];
  let last: number | null = null;
  for (const s of steps) {
    const t = stepTime(s);
    const current = groups[groups.length - 1];
    if (!current || (t !== null && last !== null && t - last >= EPISODE_GAP_MS)) groups.push([s]);
    else current.push(s);
    if (t !== null) last = t;
  }
  return groups.map((g, i) => {
    const sp = span(g);
    const sessions: EpisodeSession[] = [];
    for (const s of g) {
      const id = s.session_id ?? null;
      const existing = sessions.find(x => x.id === id);
      if (existing) existing.steps.push(s);
      else sessions.push({ id, steps: [s] });
    }
    return { id: g[0]!.step_id, number: i + 1, steps: g, start: sp.start, end: sp.end, sessions };
  });
}

export function episodeTitle(ep: Episode): string {
  const first = stepLabel(ep.steps[0]!);
  const last = stepLabel(ep.steps[ep.steps.length - 1]!);
  return ep.steps.length === 1 || first === last ? first : `${first} → ${last}`;
}

/** Open while its last event is within the episode gap of now. */
export function episodeOpen(ep: Episode, now = Date.now()): boolean {
  return ep.end !== null && now - ep.end < EPISODE_GAP_MS;
}

export type EpisodeBucket = 'today' | 'yesterday' | 'week' | 'earlier';

export const EPISODE_BUCKETS: ReadonlyArray<readonly [EpisodeBucket, string]> = [
  ['today', 'Today'],
  ['yesterday', 'Yesterday'],
  ['week', 'This week'],
  ['earlier', 'Earlier'],
];

export function episodeBucket(ep: Episode, now = Date.now()): EpisodeBucket {
  if (ep.start === null) return 'earlier';
  const midnight = new Date(now);
  midnight.setHours(0, 0, 0, 0);
  const today = midnight.getTime();
  if (ep.start >= today) return 'today';
  if (ep.start >= today - 86_400_000) return 'yesterday';
  if (ep.start >= today - 6 * 86_400_000) return 'week';
  return 'earlier';
}

// ── Journey state ───────────────────────────────────────────────────────────

export function journeyStateTone(state: string | null): 'sage' | 'blue' | 'mute' | 'amber' {
  if (state === 'converted' || state === 'completed') return 'sage';
  if (state === 'open' || state === 'active' || state === 'forming') return 'blue';
  if (state === 'interrupted' || state === 'abandoned') return 'amber';
  return 'mute';
}

// ── Journey list state (Journeys index cards) ───────────────────────────────

/**
 * How recently a still-open journey must have had a step to count as active.
 * The compiler only reports `open` / `converted` / `empty`; "active" is this
 * recency rule applied to an open journey, and the UI names the rule.
 */
export const ACTIVE_WINDOW_MS = 24 * 60 * 60_000;

/**
 * Card state for the Journeys index, derived only from the compiled journey:
 * `converted` when the compiler recorded a conversion, `active` / `idle` for
 * an open journey by last-step recency, `empty` when nothing is compiled.
 * There is no interruption or abandonment signal, so none is derived.
 */
export type JourneyListState = 'active' | 'idle' | 'converted' | 'empty';

export const JOURNEY_LIST_STATES: ReadonlyArray<{
  readonly key: Exclude<JourneyListState, 'empty'>;
  readonly label: string;
  readonly tone: 'blue' | 'mute' | 'sage';
  readonly color: string;
}> = [
  { key: 'active', label: 'Active', tone: 'blue', color: 'var(--ae-blue)' },
  { key: 'idle', label: 'Open · idle', tone: 'mute', color: 'var(--ae-mute)' },
  { key: 'converted', label: 'Converted', tone: 'sage', color: 'var(--ae-sage)' },
];

/** Time of the journey's last step (summary end, else the latest step). */
export function lastActivity(j: ProfileJourney): number | null {
  const ended = j.summary?.endedAt ? Date.parse(j.summary.endedAt) : NaN;
  if (!Number.isNaN(ended)) return ended;
  return span(j.steps).end;
}

export function journeyListState(j: ProfileJourney, now = Date.now()): JourneyListState {
  if (j.steps.length === 0 || j.summary?.state === 'empty') return 'empty';
  if (j.summary?.state === 'converted' || j.summary?.convertedAt) return 'converted';
  const last = lastActivity(j);
  return last !== null && now - last <= ACTIVE_WINDOW_MS ? 'active' : 'idle';
}
