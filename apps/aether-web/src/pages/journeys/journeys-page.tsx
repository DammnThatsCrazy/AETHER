import { useEffect, useMemo, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { formatUSD } from '@aether/ui';
import { GlassPage } from '@aether-app/components/app-shell';
import {
  Eyebrow, InlineNotice, LinkButton, Panel, SecondaryButton, Spinner, TonePill,
} from '@aether-app/components/ae-ui';
import { EmptySlot, GlassSearch, OutlineChip, SegmentedTabs } from '@aether-app/components/ae-campaigns-geo-ui';
import { LaneDot } from '@aether-app/components/ae-journeys-ui';
import { BrandMark } from '@aether-app/components/brand-mark';
import { useUsers, type UserRow } from '@aether-app/features/users/use-users';
import {
  JOURNEY_FANOUT_CAP, useJourneyFanout, type FanoutEntry,
} from '@aether-app/features/journeys/use-journey-fanout';
import {
  JOURNEY_LIST_STATES, attributedRevenue, journeyListState, lastActivity, participants, span, stepLabel,
  stepLane, systemsTouched, type JourneyListState, type ProfileJourney,
} from '@aether-app/features/journeys/journey-model';
import type { JourneyStep } from '@aether-app/features/journey';

type View = 'journeys' | 'paths';
type Tab = 'recent' | 'active' | 'converting' | 'interrupted';
type StateFilter = 'all' | Exclude<JourneyListState, 'empty'>;

const TABS: ReadonlyArray<{ readonly value: Tab; readonly label: string }> = [
  { value: 'recent', label: 'Recent' },
  { value: 'active', label: 'Active' },
  { value: 'converting', label: 'Converting' },
  { value: 'interrupted', label: 'Interrupted' },
];

const CARD_STEPS = 5;

export function journeyHref(profileId: string): string {
  return `/journeys/${encodeURIComponent(profileId)}`;
}

function parseTab(v: string | null): Tab {
  return v === 'active' || v === 'converting' || v === 'interrupted' ? v : 'recent';
}

function parseState(v: string | null): StateFilter {
  return v === 'active' || v === 'idle' || v === 'converted' ? v : 'all';
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Whole-day span, as the frame reads it ("today", "1 day", "3 days"). */
function spanDays(ms: number | null): string | null {
  if (ms === null) return null;
  const days = Math.round(ms / 86_400_000);
  return days < 1 ? 'same day' : plural(days, 'day');
}

interface CardModel {
  readonly row: UserRow;
  readonly journey: ProfileJourney;
  readonly state: Exclude<JourneyListState, 'empty'>;
  readonly last: number | null;
}

/** Facts line built only from the steps: span · steps · systems · actors. */
function journeyFacts(j: ProfileJourney): string {
  const steps = j.steps;
  const total = j.summary?.stepCount ?? j.meta?.step_count ?? steps.length;
  const systems = systemsTouched(steps, 99).length;
  const agents = participants(steps).agents.length;
  const hasPerson = steps.some(s => stepLane(s) === 'person');
  const hasAgentSteps = steps.some(s => stepLane(s) === 'agent');
  return [
    spanDays(span(steps).ms),
    plural(total, 'step'),
    systems ? plural(systems, 'system') : null,
    hasPerson ? '1 person' : null,
    agents ? plural(agents, 'agent') : hasAgentSteps ? 'agent steps' : null,
  ].filter(Boolean).join(' · ');
}

/** Card value as the frame shows it: "$418", "$24K"; cents only when present. */
export function shortUSD(v: number): string {
  const whole = Math.abs(v) >= 10_000 || Number.isInteger(v);
  return formatUSD(v, { compact: Math.abs(v) >= 10_000, maximumFractionDigits: whole ? 0 : 2, minimumFractionDigits: whole ? 0 : 2 });
}

function stepMark(step: JourneyStep): string | null {
  return step.ai_provider || step.source || step.domain || null;
}

function JourneyCard({ card, focused }: { card: CardModel; focused: boolean }) {
  const { row, journey } = card;
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView?.({ block: 'nearest' });
  }, [focused]);
  const meta = JOURNEY_LIST_STATES.find(s => s.key === card.state)!;
  const total = journey.summary?.stepCount ?? journey.meta?.step_count ?? journey.steps.length;
  const revenue = attributedRevenue(journey.steps);
  const revenueUnknown = journey.degraded.some(d => d.startsWith('attribution'));
  const isId = row.displayName === row.id;

  return (
    <article
      ref={ref}
      className="ae-glass-card flex min-w-0 flex-col gap-3 rounded-[20px] px-5 pb-4 pt-[18px]"
      style={focused ? { borderColor: 'var(--ae-blue)' } : undefined}
      data-journey-card={row.id}
      data-journey-state={card.state}
    >
      <header className="flex min-w-0 items-start justify-between gap-3">
        <h2 className={`min-w-0 break-words text-[16px] font-medium leading-[1.4] tracking-[-0.3px] ${isId ? 'ae-mono text-[14px]' : ''}`}>
          {row.displayName}
        </h2>
        <TonePill tone={meta.tone} className="mt-[3px] flex-none">{meta.label}</TonePill>
      </header>
      <span className="-mt-1 text-[12px]" style={{ color: 'var(--ae-mute)' }} data-testid="journey-facts">{journeyFacts(journey)}</span>
      <ol className="flex min-w-0 flex-col" aria-label={`${row.displayName} journey steps`}>
        {journey.steps.slice(0, CARD_STEPS).map((s, i, arr) => {
          const mark = stepMark(s);
          return (
            <li key={s.step_id} className="relative flex min-w-0 items-center gap-2.5 py-[3px] text-[13px]">
              {i < arr.length - 1 && (
                <span className="absolute left-[3.5px] top-[17px] h-[calc(100%-6px)] w-px" style={{ background: 'var(--ae-edge)' }} aria-hidden="true" />
              )}
              <LaneDot step={s} size={8} />
              {mark ? <BrandMark token={mark} size={18} shape="square" /> : <span className="w-[18px] flex-none" aria-hidden="true" />}
              <span className="min-w-0 truncate">{stepLabel(s)}</span>
            </li>
          );
        })}
        {total > CARD_STEPS && (
          <li className="pl-[46px] pt-0.5 text-[12px]" style={{ color: 'var(--ae-mute)' }}>+{total - CARD_STEPS} more</li>
        )}
      </ol>
      <footer className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-2 border-t pt-3" style={{ borderColor: 'var(--ae-edge)' }}>
        <Link to={journeyHref(row.id)} className="ae-btn-primary ae-focus px-4 py-[7px] text-[13px]" data-testid="open-journey">Open journey</Link>
        <Link to={`/explore?entity=${encodeURIComponent(row.id)}`} className="ae-focus text-[13px] hover:underline" style={{ color: 'var(--ae-blue-ink)' }}>
          Open in Graph →
        </Link>
        <span className="ml-auto text-[13px] font-medium tabular-nums" data-testid="journey-value">
          {revenue !== null && revenue > 0 ? (
            <span style={{ color: 'var(--ae-sage)' }} title={formatUSD(revenue)}>{shortUSD(revenue)}</span>
          ) : revenueUnknown ? (
            <span style={{ color: 'var(--ae-mute)' }} title="Attribution could not be read for this journey">unknown</span>
          ) : (
            <span style={{ color: 'var(--ae-faint)' }} aria-label="No attributed revenue reported" title="No attributed revenue reported">—</span>
          )}
        </span>
      </footer>
    </article>
  );
}

function AggregatePaths({ onBrowse }: { onBrowse: () => void }) {
  return (
    <Panel className="flex flex-col gap-3 px-5 py-5">
      <Eyebrow>Most common paths · share of converting journeys</Eyebrow>
      <div className="flex flex-col gap-1.5" data-testid="aggregate-paths-unavailable">
        <span className="text-[15px] font-medium">Aggregate paths are not available yet</span>
        <span className="text-[13px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>
          Ranking common step sequences by their share of converting journeys, with drop-off and time between steps,
          needs a tenant-wide path read. The API does not expose one yet, so Aether shows no ranked paths rather than
          estimating them. Each journey&apos;s own path is available when you open it.
        </span>
      </div>
      <div><SecondaryButton onClick={onBrowse}>Browse journeys</SecondaryButton></div>
    </Panel>
  );
}

function InterruptedUnavailable({ onShowIdle }: { onShowIdle: () => void }) {
  return (
    <Panel className="flex flex-col gap-2 px-5 py-5">
      <div className="flex flex-col gap-1.5" data-testid="interrupted-unavailable">
        <span className="text-[15px] font-medium">Interruption is not reported yet</span>
        <span className="text-[13px] leading-relaxed" style={{ color: 'var(--ae-mute)' }}>
          The journey compiler records a journey as open or converted. It does not mark one as interrupted or
          abandoned, so Aether does not guess that from inactivity. Open journeys with no step in the last 24 hours
          are listed as Open · idle.
        </span>
      </div>
      <div><SecondaryButton onClick={onShowIdle}>Show idle journeys</SecondaryButton></div>
    </Panel>
  );
}

/** Profiles whose journey is not shown as a card: not compiled yet, or the read failed. */
function FanoutDisclosure({
  listed, read, empty, failed, onRetry,
}: {
  listed: number;
  read: number;
  empty: UserRow[];
  failed: UserRow[];
  onRetry: () => void;
}) {
  const capped = listed > read;
  if (!capped && empty.length === 0 && failed.length === 0) return null;
  const names = (rows: UserRow[]) => rows.slice(0, 4).map(r => r.displayName).join(', ') + (rows.length > 4 ? ` and ${rows.length - 4} more` : '');
  return (
    <div className="flex flex-col gap-1 text-[12px] leading-relaxed" style={{ color: 'var(--ae-mute)' }} data-testid="journeys-disclosure">
      {capped && (
        <span data-testid="journeys-capped">
          Showing journeys for the first {read} of {listed} listed profiles. There is no tenant-wide journey list yet, so
          each profile&apos;s journey is read separately; search to reach other profiles.
        </span>
      )}
      {empty.length > 0 && (
        <span data-testid="journeys-not-compiled">No journey compiled yet for {plural(empty.length, 'profile')}: {names(empty)}.</span>
      )}
      {failed.length > 0 && (
        <span className="flex flex-wrap items-center gap-x-2" style={{ color: 'var(--ae-amber)' }} data-testid="journeys-failed">
          {plural(failed.length, 'journey')} could not be read: {names(failed)}.
          <LinkButton onClick={onRetry}>Retry</LinkButton>
        </span>
      )}
    </div>
  );
}

/**
 * Journeys (design: Aether Journeys). Aether compiles one journey per profile
 * and the API has no tenant-wide journey list, so the index reads the listed
 * profiles' compiled journeys in a bounded fan-out and shows one card each.
 * `?tab=` picks Recent / Active / Converting / Interrupted, `?state=` filters
 * by derived state, `?profile=` highlights a profile's card, and `?view=paths`
 * shows Aggregate Paths (honestly unavailable until a path read exists).
 */
export function JourneysPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { users, search, setSearch, isLoading, error, reload } = useUsers();
  const view: View = searchParams.get('view') === 'paths' ? 'paths' : 'journeys';
  const tab = parseTab(searchParams.get('tab'));
  const stateFilter = parseState(searchParams.get('state'));
  const focusId = searchParams.get('profile');

  const setParams = (next: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) params.delete(k);
      else params.set(k, v);
    }
    setSearchParams(params);
  };

  const readRows = useMemo(() => {
    const head = users.slice(0, JOURNEY_FANOUT_CAP);
    // A deep-linked profile beyond the cap is still read.
    const focused = focusId && !head.some(u => u.id === focusId) ? users.find(u => u.id === focusId) : undefined;
    return focused ? [...head, focused] : head;
  }, [users, focusId]);
  const ids = useMemo(() => readRows.map(r => r.id), [readRows]);
  const fanout = useJourneyFanout(view === 'journeys' && !isLoading && !error ? ids : []);

  const { cards, empty, failed } = useMemo(() => {
    const now = Date.now();
    const byId = new Map<string, FanoutEntry>((fanout.data ?? []).map(e => [e.id, e]));
    const out: CardModel[] = [];
    const emptyRows: UserRow[] = [];
    const failedRows: UserRow[] = [];
    for (const row of readRows) {
      const e = byId.get(row.id);
      if (!e) continue;
      if (e.status === 'error') { failedRows.push(row); continue; }
      const state = journeyListState(e.journey, now);
      if (state === 'empty') { emptyRows.push(row); continue; }
      out.push({ row, journey: e.journey, state, last: lastActivity(e.journey) });
    }
    out.sort((a, b) => (b.last ?? -Infinity) - (a.last ?? -Infinity));
    return { cards: out, empty: emptyRows, failed: failedRows };
  }, [fanout.data, readRows]);

  const inTab = cards.filter(c => (tab === 'active' ? c.state === 'active' : tab === 'converting' ? c.state === 'converted' : true));
  const counts = Object.fromEntries(JOURNEY_LIST_STATES.map(s => [s.key, inTab.filter(c => c.state === s.key).length])) as Record<StateFilter, number>;
  const shown = stateFilter === 'all' ? inTab : inTab.filter(c => c.state === stateFilter);
  const activeNow = cards.filter(c => c.state === 'active').length;
  const fanoutLoading = fanout.isLoading || (ids.length > 0 && !fanout.data && !fanout.error);
  const allFailed = !!fanout.data && fanout.data.length > 0 && failed.length === fanout.data.length;

  let body;
  if (error) {
    body = (
      <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-4" role="alert">
        <span className="text-[15px] font-medium">Journeys are unavailable right now</span>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{error}</span>
        <SecondaryButton onClick={reload}>Try again</SecondaryButton>
      </div>
    );
  } else if (isLoading) {
    body = (
      <div className="flex items-center gap-2.5 py-10 text-[13px]" style={{ color: 'var(--ae-mute)' }} data-testid="journeys-loading">
        <Spinner size={20} /> Loading journeys…
      </div>
    );
  } else if (users.length === 0) {
    body = (
      <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-5">
        <span className="text-[15px] font-medium">{search ? 'No journeys match' : 'No journeys yet'}</span>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
          {search
            ? `No profiles match "${search}".`
            : 'Journeys appear once your first source sends events and Aether compiles them per profile.'}
        </span>
        {!search && <Link to="/activation" className="ae-btn-primary ae-focus mt-1 px-5 py-[9px]">Connect your first source</Link>}
      </div>
    );
  } else if (fanoutLoading) {
    body = (
      <div className="flex items-center gap-2.5 py-10 text-[13px]" style={{ color: 'var(--ae-mute)' }} data-testid="journeys-reading">
        <Spinner size={20} /> Reading {plural(ids.length, 'profile journey')}…
      </div>
    );
  } else if (fanout.error || allFailed) {
    body = (
      <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-4" role="alert">
        <span className="text-[15px] font-medium">Journeys are unavailable right now</span>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No profile journey could be read{fanout.error ? `: ${fanout.error}` : '.'}</span>
        <SecondaryButton onClick={fanout.refetch}>Try again</SecondaryButton>
      </div>
    );
  } else {
    body = (
      <>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5" data-testid="journey-state-chips">
          <span className="mr-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>State</span>
          <OutlineChip selected={stateFilter === 'all'} onClick={() => setParams({ state: null })}>All · {inTab.length}</OutlineChip>
          {JOURNEY_LIST_STATES.map(s => (
            <OutlineChip key={s.key} selected={stateFilter === s.key} onClick={() => setParams({ state: stateFilter === s.key ? null : s.key })}>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-[7px] w-[7px] rounded-full" style={{ background: s.color }} aria-hidden="true" />
                {s.label} · {counts[s.key]}
              </span>
            </OutlineChip>
          ))}
        </div>
        {shown.length === 0 ? (
          <EmptySlot testId="journeys-tab-empty">
            {cards.length === 0
              ? 'None of these profiles has a compiled journey yet. Journeys compile as each profile’s activity is ingested.'
              : tab === 'active'
                ? 'No open journey had a step in the last 24 hours.'
                : tab === 'converting'
                  ? 'No journey here has a recorded conversion.'
                  : 'No journey is in this state.'}
          </EmptySlot>
        ) : (
          <div className="grid min-w-0 grid-cols-1 items-start gap-3.5 sm:grid-cols-[repeat(auto-fill,minmax(290px,1fr))]" data-testid="journeys-list">
            {shown.map(c => <JourneyCard key={c.row.id} card={c} focused={focusId === c.row.id} />)}
          </div>
        )}
        <FanoutDisclosure listed={users.length} read={Math.min(users.length, JOURNEY_FANOUT_CAP)} empty={empty} failed={failed} onRetry={fanout.refetch} />
      </>
    );
  }

  return (
    <GlassPage>
      <div className="flex min-w-0 flex-col gap-4" data-testid="aether-journeys">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-1">
            <h1 className="text-[clamp(26px,3.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Journeys</h1>
            <span className="text-[14px]" style={{ color: 'var(--ae-mute)' }}>Follow how people and agents move from one event to the next.</span>
          </div>
          <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
            {view === 'journeys' && (
              <div className="flex w-full min-w-0 sm:w-auto">
                <GlassSearch value={search} onChange={setSearch} placeholder="Search journeys" label="Search journeys" />
              </div>
            )}
            <SegmentedTabs<View>
              label="Journeys view"
              value={view}
              onChange={v => setParams({ view: v === 'journeys' ? null : v })}
              options={[{ value: 'journeys', label: 'Individual' }, { value: 'paths', label: 'Aggregate Paths' }]}
            />
          </div>
        </div>

        {view === 'paths' ? (
          <AggregatePaths onBrowse={() => setParams({ view: null })} />
        ) : (
          <>
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <SegmentedTabs<Tab>
                label="Journey list"
                value={tab}
                onChange={t => setParams({ tab: t === 'recent' ? null : t })}
                options={TABS}
              />
              {fanout.data && cards.length > 0 && (
                <span className="flex items-center gap-1.5 text-[13px]" style={{ color: 'var(--ae-mute)' }} data-testid="journeys-active-now">
                  <span className="h-[7px] w-[7px] rounded-full" style={{ background: 'var(--ae-sage)' }} aria-hidden="true" />
                  <span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{activeNow}</span> active in the last 24 h · of {plural(cards.length, 'journey')} read
                </span>
              )}
            </div>
            {tab === 'interrupted' && !error && !isLoading ? (
              <InterruptedUnavailable onShowIdle={() => setParams({ tab: null, state: 'idle' })} />
            ) : body}
          </>
        )}
      </div>
    </GlassPage>
  );
}
