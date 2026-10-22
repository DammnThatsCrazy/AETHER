import { useMemo, useState, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { formatUSD } from '@aether/ui';
import { GlassPage } from '@aether-app/components/app-shell';
import {
  Bar, Eyebrow, InlineNotice, MetricTile, Panel, Spinner, TonePill,
} from '@aether-app/components/ae-ui';
import {
  Crumb, EvidenceModeToggle, LaneDot, PageTabs, RawFields, SwimlaneReplay, SystemsTouched, useReplay,
  type EvidenceMode,
} from '@aether-app/components/ae-journeys-ui';
import type { JourneyStep } from '@aether-app/features/journey';
import { useProfileJourney, JOURNEY_STEP_LIMIT } from '@aether-app/features/journeys/use-profile-journey';
import {
  attributedRevenue, episodeTitle, formatDuration, formatWhen, gapsAfter, humanizeToken, journeyStateTone,
  laneMix, longestGaps, participants, segmentEpisodes, span, stepLabel, stepLane, stepPlain, stepRaw,
  stepTime, stepWho, systemsTouched, type Episode, type ProfileJourney,
} from '@aether-app/features/journeys/journey-model';
import { useUserProfile } from '@aether-app/features/users/use-user-profile';
import { profileIdentity } from '@aether-app/pages/user-profile/profile-model';

type Tab = 'overview' | 'timeline' | 'participants' | 'episodes' | 'outcome' | 'evidence';

const TABS: ReadonlyArray<readonly [Tab, string]> = [
  ['overview', 'Overview'],
  ['timeline', 'Timeline'],
  ['participants', 'Participants'],
  ['episodes', 'Episodes'],
  ['outcome', 'Outcome'],
  ['evidence', 'Evidence'],
];

const enc = encodeURIComponent;

export function episodeHref(profileId: string, episodeId: string): string {
  return `/episodes/${enc(profileId)}/${enc(episodeId)}`;
}

export function Quiet({ children }: { children: ReactNode }) {
  return <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{children}</span>;
}

export function OutLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="ae-focus ae-card rounded-full px-3.5 py-1.5 text-[12px] hover:underline">
      {children} →
    </Link>
  );
}

/** Links a step to the pages that own its referenced objects. */
function stepLinks(step: JourneyStep, profileId: string, episodes: readonly Episode[]) {
  const links: Array<{ to: string; label: string }> = [];
  if (step.campaign_id) links.push({ to: `/campaigns/${enc(step.campaign_id)}`, label: 'Campaign 360' });
  if (step.agent_id) links.push({ to: `/agents/${enc(step.agent_id)}`, label: 'Agent 360' });
  if (stepLane(step) === 'person') links.push({ to: `/users/${enc(profileId)}`, label: 'Profile 360' });
  const ep = episodes.find(e => e.steps.some(s => s.step_id === step.step_id));
  if (ep) links.push({ to: episodeHref(profileId, ep.id), label: `Episode ${ep.number}` });
  return links;
}

function StepFacts({ step, gap }: { step: JourneyStep; gap: number | null }) {
  const facts: Array<[string, string]> = [['Family', humanizeToken(step.activity_family)]];
  if (step.activity_status) facts.push(['Status', humanizeToken(step.activity_status)]);
  if (step.evidence_confidence !== null && step.evidence_confidence !== undefined) facts.push(['Evidence confidence', `${Math.round(step.evidence_confidence * 100)}%`]);
  if (step.verification_level) facts.push(['Verification', humanizeToken(step.verification_level)]);
  if (gap !== null) facts.push(['Until next step', formatDuration(gap)]);
  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
      {facts.map(([l, v]) => (
        <span key={l} className="flex min-w-0 flex-col rounded-[10px] px-2.5 py-1.5" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
          <span className="truncate text-[13px]">{v}</span>
          <span className="ae-eyebrow text-[10px]">{l}</span>
        </span>
      ))}
    </div>
  );
}

// ── Overview ────────────────────────────────────────────────────────────────

function Overview({
  journey, profileId, episodes, onEvidence,
}: {
  journey: ProfileJourney;
  profileId: string;
  episodes: readonly Episode[];
  onEvidence: (i: number) => void;
}) {
  const { steps } = journey;
  const replay = useReplay(steps.length);
  const current = steps[replay.index];
  const sp = span(steps);
  const mix = laneMix(steps);
  const gaps = gapsAfter(steps);
  const longest = longestGaps(steps);
  const revenue = attributedRevenue(steps);
  const revenueSteps = steps.filter(s => typeof s.attributed_net_revenue === 'number' && s.attributed_net_revenue > 0);
  const agentSteps = steps.filter(s => stepLane(s) === 'agent').length;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }} data-testid="journey-kpis">
        <MetricTile label="Steps" value={journey.summary?.stepCount ?? journey.meta?.step_count ?? steps.length} />
        <MetricTile label="Duration" value={formatDuration(sp.ms)} sub={formatWhen(sp.start)} />
        <MetricTile label="Episodes" value={episodes.length} sub="30-minute gap rule" />
        <MetricTile label="Agent steps" value={agentSteps} />
        {revenue !== null && <MetricTile label="Attributed revenue" value={formatUSD(revenue)} />}
      </div>

      <Panel className="flex flex-col gap-3 px-4 py-4 sm:px-5">
        <SwimlaneReplay steps={steps} replay={replay} />
        {current && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[14px] px-3.5 py-2.5" style={{ background: 'var(--ae-edge-soft)' }} data-testid="journey-current-step">
            <span className="flex min-w-0 items-center gap-2.5">
              <LaneDot step={current} size={10} />
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-[14px] font-medium">{stepLabel(current)}</span>
                <span className="truncate text-[12px]" style={{ color: 'var(--ae-mute)' }}>{stepWho(current)} · {formatWhen(stepTime(current))}</span>
              </span>
            </span>
            <button type="button" onClick={() => onEvidence(replay.index)} className="ae-focus ae-btn-secondary px-3.5 py-1.5 text-[12px]">
              View evidence
            </button>
          </div>
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Panel className="flex flex-col gap-2 px-4 py-4 sm:px-5">
          <Eyebrow>The journey, step by step</Eyebrow>
          <ol className="flex flex-col" data-testid="journey-chain">
            {steps.map((s, i) => (
              <li key={s.step_id} className="grid gap-x-3" style={{ gridTemplateColumns: '14px 1fr' }}>
                <span className="flex flex-col items-center">
                  <span className="mt-1.5"><LaneDot step={s} size={10} /></span>
                  {i < steps.length - 1 && <span className="w-px flex-1" style={{ background: 'var(--ae-edge)' }} />}
                </span>
                <button type="button" onClick={() => replay.seek(i)} className="ae-focus min-w-0 pb-3 text-left">
                  <span className="block truncate text-[14px] font-medium hover:underline" style={i === replay.index ? { color: 'var(--ae-blue-ink)' } : undefined}>{stepLabel(s)}</span>
                  <span className="block text-[12px]" style={{ color: 'var(--ae-mute)' }}>{stepPlain(s)}</span>
                  {gaps[i] !== null && gaps[i] !== undefined && (
                    <span className="block text-[11px]" style={{ color: 'var(--ae-faint)' }}>↓ {formatDuration(gaps[i]!)} until the next step</span>
                  )}
                </button>
              </li>
            ))}
          </ol>
          {stepLinks(current ?? steps[0]!, profileId, episodes).length > 0 && (
            <span className="flex flex-wrap gap-1.5 pt-1">
              {stepLinks(current ?? steps[0]!, profileId, episodes).map(l => <OutLink key={l.to} to={l.to}>{l.label}</OutLink>)}
            </span>
          )}
        </Panel>

        <div className="flex flex-col gap-4">
          <Panel className="flex flex-col gap-2.5 px-4 py-4 sm:px-5">
            <Eyebrow>Who did the work</Eyebrow>
            <span className="flex h-2 overflow-hidden rounded-full" aria-hidden="true">
              {mix.map(m => <span key={m.key} style={{ width: `${m.pct}%`, background: m.color }} />)}
            </span>
            {mix.map(m => (
              <span key={m.key} className="flex items-center justify-between text-[13px]">
                <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: m.color }} />{m.label}</span>
                <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-mute)' }}>{m.n} · {m.pct}%</span>
              </span>
            ))}
            <Eyebrow className="pt-2">Where the time went</Eyebrow>
            {longest.length === 0 ? (
              <Quiet>No waits between steps are reported.</Quiet>
            ) : longest.map(g => (
              <div key={`${g.from}-${g.to}-${g.ms}`} className="flex flex-col gap-1">
                <span className="flex justify-between gap-2 text-[12px]">
                  <span className="truncate">{g.from} → {g.to}</span>
                  <span className="ae-mono flex-none" style={{ color: 'var(--ae-mute)' }}>{formatDuration(g.ms)}</span>
                </span>
                <Bar value={g.pct} />
              </div>
            ))}
          </Panel>

          {revenue !== null && revenueSteps.length > 0 && (
            <Panel className="flex flex-col gap-2.5 px-4 py-4 sm:px-5">
              <Eyebrow>What moved the outcome</Eyebrow>
              {revenueSteps.map(s => {
                const pct = revenue > 0 ? Math.round(((s.attributed_net_revenue ?? 0) / revenue) * 100) : 0;
                return (
                  <div key={s.step_id} className="flex flex-col gap-1">
                    <span className="flex justify-between gap-2 text-[12px]">
                      <span className="truncate">{stepLabel(s)}</span>
                      <span className="ae-mono flex-none" style={{ color: 'var(--ae-mute)' }}>{pct}%</span>
                    </span>
                    <Bar value={pct} color="var(--ae-sage)" />
                  </div>
                );
              })}
              <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>Share of attributed net revenue. Influence is observed, not proven causal.</span>
            </Panel>
          )}

          <Panel className="flex flex-col gap-2 px-4 py-4 sm:px-5">
            <Eyebrow>Systems touched</Eyebrow>
            <SystemsTouched systems={systemsTouched(steps)} />
          </Panel>
        </div>
      </div>
    </div>
  );
}

// ── Timeline ────────────────────────────────────────────────────────────────

function Timeline({ steps, profileId, episodes }: { steps: readonly JourneyStep[]; profileId: string; episodes: readonly Episode[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const [mode, setMode] = useState<EvidenceMode>('plain');
  const gaps = gapsAfter(steps);
  return (
    <Panel className="flex flex-col gap-3 px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Quiet>Select a step to see exactly what happened.</Quiet>
        <EvidenceModeToggle mode={mode} onChange={setMode} />
      </div>
      <ol className="flex flex-col" data-testid="journey-timeline">
        {steps.map((s, i) => {
          const expanded = open === s.step_id;
          const links = stepLinks(s, profileId, episodes);
          return (
            <li key={s.step_id} className="border-b last:border-b-0" style={{ borderColor: 'var(--ae-edge-soft)' }}>
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : s.step_id)}
                className="ae-focus grid w-full items-center gap-x-3 py-2.5 text-left"
                style={{ gridTemplateColumns: 'minmax(70px, 110px) 10px minmax(0,1fr) auto' }}
              >
                <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>{formatWhen(stepTime(s))}</span>
                <LaneDot step={s} />
                <span className="truncate text-[14px]">{stepLabel(s)}</span>
                <span className="hidden truncate text-[12px] sm:inline" style={{ color: 'var(--ae-mute)' }}>{stepWho(s)}</span>
              </button>
              {expanded && (
                <div className="flex flex-col gap-2.5 pb-3 pl-0 sm:pl-[122px]" data-testid="timeline-step-detail">
                  {mode === 'plain' ? <span className="text-[13px]">{stepPlain(s)}</span> : <RawFields rows={stepRaw(s)} />}
                  <StepFacts step={s} gap={gaps[i] ?? null} />
                  {links.length > 0 && (
                    <span className="flex flex-wrap gap-1.5">{links.map(l => <OutLink key={l.to} to={l.to}>{l.label}</OutLink>)}</span>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

// ── Participants ────────────────────────────────────────────────────────────

function ParticipantGroup({ title, items, empty }: { title: string; items: Array<{ key: string; label: string; sub: string; to?: string }>; empty: string }) {
  return (
    <Panel className="flex flex-col gap-2 px-4 py-4">
      <Eyebrow>{title}</Eyebrow>
      {items.length === 0 ? <Quiet>{empty}</Quiet> : items.map(i => (
        i.to ? (
          <Link key={i.key} to={i.to} className="ae-focus flex min-w-0 flex-col rounded-[12px] px-3 py-2 hover:underline" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
            <span className="ae-mono truncate text-[13px]">{i.label}</span>
            <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{i.sub}</span>
          </Link>
        ) : (
          <span key={i.key} className="flex min-w-0 flex-col rounded-[12px] px-3 py-2" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
            <span className="ae-mono truncate text-[13px]">{i.label}</span>
            <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{i.sub}</span>
          </span>
        )
      ))}
    </Panel>
  );
}

export function ParticipantsGrid({ steps, profileId, profileName }: { steps: readonly JourneyStep[]; profileId: string; profileName: string }) {
  const p = participants(steps);
  const count = (pred: (s: JourneyStep) => boolean) => steps.filter(pred).length;
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }} data-testid="participants">
      <ParticipantGroup
        title="Person"
        empty="No person is attached."
        items={[{ key: profileId, label: profileName, sub: `${count(s => stepLane(s) === 'person')} person steps`, to: `/users/${enc(profileId)}` }]}
      />
      <ParticipantGroup
        title="Agents"
        empty="No agent took part."
        items={p.agents.map(a => ({ key: a, label: a, sub: `${count(s => s.agent_id === a)} steps`, to: `/agents/${enc(a)}` }))}
      />
      <ParticipantGroup
        title="Campaigns"
        empty="No campaign is referenced."
        items={p.campaigns.map(c => ({ key: c, label: c, sub: `${count(s => s.campaign_id === c)} steps`, to: `/campaigns/${enc(c)}` }))}
      />
      <ParticipantGroup
        title="Wallets"
        empty="No wallet is referenced."
        items={p.wallets.map(w => ({ key: w, label: w, sub: `${count(s => s.wallet_id === w)} steps` }))}
      />
    </div>
  );
}

// ── Episodes ────────────────────────────────────────────────────────────────

function Episodes({ episodes, profileId }: { episodes: readonly Episode[]; profileId: string }) {
  return (
    <div className="flex flex-col gap-3" data-testid="journey-episodes">
      <Quiet>
        A journey contains episodes: concentrated periods of activity. Until the API exposes compiled episodes, a new
        episode starts after 30 minutes without a step.
      </Quiet>
      {episodes.map(ep => (
        <Link
          key={ep.id}
          to={episodeHref(profileId, ep.id)}
          className="ae-focus ae-glass-card flex flex-wrap items-center justify-between gap-3 rounded-[18px] px-4 py-3 hover:border-[var(--ae-blue)]"
        >
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate text-[14px] font-medium">Episode {ep.number} · {episodeTitle(ep)}</span>
            <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              {formatWhen(ep.start)} · {formatDuration(ep.start !== null && ep.end !== null ? ep.end - ep.start : null)} · {ep.steps.length} event{ep.steps.length === 1 ? '' : 's'} · {ep.sessions.filter(x => x.id).length} session{ep.sessions.filter(x => x.id).length === 1 ? '' : 's'}
            </span>
          </span>
          <span className="text-[12px]" style={{ color: 'var(--ae-blue-ink)' }}>Open episode →</span>
        </Link>
      ))}
    </div>
  );
}

// ── Outcome ─────────────────────────────────────────────────────────────────

function Outcome({ journey, profileId }: { journey: ProfileJourney; profileId: string }) {
  const { steps, summary } = journey;
  const outcomes = steps.filter(s => s.activity_family === 'outcome' || s.activity_family === 'commerce');
  const revenue = attributedRevenue(steps);
  const attributionDown = journey.degraded.includes('attribution_credits');
  const converted = summary?.convertedAt ? Date.parse(summary.convertedAt) : NaN;
  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="journey-outcome">
      <Panel className="flex flex-col gap-2 px-4 py-4 sm:px-5">
        <Eyebrow>Primary</Eyebrow>
        <span className="text-[20px] font-medium tracking-[-0.3px]">
          {summary?.state ? humanizeToken(summary.state) : 'State not reported'}
        </span>
        <Quiet>{Number.isNaN(converted) ? 'No conversion is recorded for this journey.' : `Converted ${formatWhen(converted)}`}</Quiet>
        <Eyebrow className="pt-2">Outcome steps</Eyebrow>
        {outcomes.length === 0 ? <Quiet>No outcome or commerce step is recorded.</Quiet> : (
          <ul className="flex flex-col gap-1">
            {outcomes.map(s => (
              <li key={s.step_id} className="flex items-center gap-2 text-[13px]"><LaneDot step={s} />{stepLabel(s)}<span style={{ color: 'var(--ae-mute)' }}>· {formatWhen(stepTime(s))}</span></li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel className="flex flex-col gap-2 px-4 py-4 sm:px-5">
        <Eyebrow>Attributed value</Eyebrow>
        {attributionDown ? (
          <InlineNotice tone="amber">Attribution credits are unavailable right now, so attributed revenue is unknown (not zero).</InlineNotice>
        ) : revenue === null ? (
          <Quiet>No attributed revenue is recorded on these steps.</Quiet>
        ) : (
          <span className="ae-mono text-[22px]">{formatUSD(revenue)}</span>
        )}
        <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          Lifetime value and comparisons with similar journeys are not reported by the journey read.
        </span>
        <span className="flex flex-wrap gap-1.5 pt-1">
          <OutLink to={`/users/${enc(profileId)}`}>Profile 360</OutLink>
          <OutLink to={`/users/${enc(profileId)}/journey`}>Risk and operation evidence</OutLink>
        </span>
      </Panel>
    </div>
  );
}

// ── Evidence ────────────────────────────────────────────────────────────────

function Evidence({ steps, focus }: { steps: readonly JourneyStep[]; focus: number | null }) {
  const [mode, setMode] = useState<EvidenceMode>('plain');
  const verified = steps.filter(s => s.verification_level).length;
  const conf = steps.map(s => s.evidence_confidence).filter((v): v is number => typeof v === 'number');
  const meanConf = conf.length ? Math.round((conf.reduce((a, b) => a + b, 0) / conf.length) * 100) : null;
  const methods = new Set(steps.map(s => s.identity_method).filter(Boolean)).size;
  const ordered = focus !== null && steps[focus] ? [steps[focus]!, ...steps.filter((_, i) => i !== focus)] : [...steps];
  return (
    <div className="flex flex-col gap-3" data-testid="journey-evidence">
      <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
        <MetricTile label="Steps with evidence" value={steps.length} />
        <MetricTile label="Verified steps" value={verified} />
        <MetricTile label="Mean evidence confidence" value={meanConf === null ? '—' : `${meanConf}%`} sub={meanConf === null ? 'not reported' : undefined} />
        <MetricTile label="Identity methods" value={methods} />
      </div>
      <div className="flex justify-end"><EvidenceModeToggle mode={mode} onChange={setMode} /></div>
      <ul className="flex flex-col gap-2">
        {ordered.map((s, i) => (
          <li
            key={s.step_id}
            className="flex flex-col gap-1.5 rounded-[14px] px-3.5 py-2.5"
            style={{ background: 'var(--ae-glass-card)', border: `1px solid ${focus !== null && i === 0 ? 'var(--ae-blue)' : 'var(--ae-edge-soft)'}` }}
            data-evidence-step={s.step_id}
          >
            {mode === 'plain' ? (
              <span className="text-[13px]">{formatWhen(stepTime(s))} — {stepPlain(s)}</span>
            ) : (
              <RawFields rows={stepRaw(s)} />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Open journey (design: Aether Journeys, open view). Reads the profile's
 * compiled unified journey; tabs per the design: Overview (swimlane replay,
 * step chain, actor mix, waits), Timeline, Participants, Episodes, Outcome,
 * Evidence. Route: /journeys/:profileId (`?tab=` selects a tab).
 */
export function JourneyDetailPage() {
  const { profileId = '' } = useParams<{ profileId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab') as Tab | null;
  const tab: Tab = TABS.some(([t]) => t === tabParam) ? tabParam! : 'overview';
  const [focus, setFocus] = useState<number | null>(null);
  const { data, isLoading, error, refetch } = useProfileJourney(profileId);
  const profile = useUserProfile(profileId);
  const identity = profileIdentity(profile.data, profileId);
  const steps = useMemo(() => data?.steps ?? [], [data]);
  const episodes = useMemo(() => segmentEpisodes(steps), [steps]);
  const sp = span(steps);

  const setTab = (t: Tab) => {
    const params = new URLSearchParams(searchParams);
    if (t === 'overview') params.delete('tab');
    else params.set('tab', t);
    setSearchParams(params);
  };

  const state = data?.summary?.state ?? null;
  const total = data?.summary?.stepCount ?? data?.meta?.step_count ?? steps.length;

  return (
    <GlassPage>
      <div className="flex min-w-0 flex-col gap-4" data-testid="aether-journey-detail">
        <Crumb to="/journeys" section="Journeys" name={identity.name} />
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <span className="flex flex-wrap items-center gap-2.5">
              <h1 className={`truncate text-[clamp(22px,3vw,28px)] font-medium tracking-[-0.5px] ${identity.nameIsId ? 'ae-mono' : ''}`}>{identity.name}</h1>
              {state && <TonePill tone={journeyStateTone(state)}>{humanizeToken(state)}</TonePill>}
            </span>
            {steps.length > 0 && (
              <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
                {total} steps · {formatWhen(sp.start)} → {formatWhen(sp.end)} · {formatDuration(sp.ms)}
              </span>
            )}
          </div>
          <span className="flex flex-wrap gap-1.5">
            <OutLink to={`/users/${enc(profileId)}`}>Profile 360</OutLink>
            <OutLink to={`/explore?entity=${enc(profileId)}`}>Open in Graph</OutLink>
            <OutLink to={`/users/${enc(profileId)}/journey`}>Journey explorer</OutLink>
          </span>
        </div>

        {error ? (
          <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-4" role="alert">
            <span className="text-[15px] font-medium">This journey is unavailable right now</span>
            <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{error}</span>
            <button type="button" onClick={() => void refetch()} className="ae-btn-secondary ae-focus px-5 py-[9px]">Try again</button>
          </div>
        ) : isLoading || !data ? (
          <div className="flex items-center gap-2.5 py-10 text-[13px]" style={{ color: 'var(--ae-mute)' }} data-testid="journey-loading">
            <Spinner size={20} /> Loading journey…
          </div>
        ) : steps.length === 0 ? (
          <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-5" data-testid="journey-empty">
            <span className="text-[15px] font-medium">
              {data.meta?.quality_status === 'not_provisioned' ? 'No journey compiled yet' : 'This journey has no steps yet'}
            </span>
            <Quiet>Journey compilation starts automatically when activity for this profile is ingested.</Quiet>
          </div>
        ) : (
          <>
            {data.meta?.quality_status === 'partial' && (
              <InlineNotice tone="amber">This journey was compiled by an older compiler version, so cross-rail coverage may be incomplete.</InlineNotice>
            )}
            {data.hasMore && (
              <InlineNotice tone="blue">Showing the first {JOURNEY_STEP_LIMIT} steps. The journey explorer pages through the rest.</InlineNotice>
            )}
            <PageTabs tabs={TABS} value={tab} onChange={setTab} label="Journey sections" />
            {tab === 'overview' && (
              <Overview journey={data} profileId={profileId} episodes={episodes} onEvidence={i => { setFocus(i); setTab('evidence'); }} />
            )}
            {tab === 'timeline' && <Timeline steps={steps} profileId={profileId} episodes={episodes} />}
            {tab === 'participants' && <ParticipantsGrid steps={steps} profileId={profileId} profileName={identity.name} />}
            {tab === 'episodes' && <Episodes episodes={episodes} profileId={profileId} />}
            {tab === 'outcome' && <Outcome journey={data} profileId={profileId} />}
            {tab === 'evidence' && <Evidence steps={steps} focus={focus} />}
          </>
        )}
      </div>
    </GlassPage>
  );
}
