import { useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { GlassPage } from '@aether-app/components/app-shell';
import { Eyebrow, MetricTile, Panel, Spinner, TonePill } from '@aether-app/components/ae-ui';
import {
  Crumb, DensityStrip, EvidenceModeToggle, LaneDot, PageTabs, RawFields, SwimlaneReplay, SystemsTouched,
  useReplay, type EvidenceMode,
} from '@aether-app/components/ae-journeys-ui';
import type { JourneyStep } from '@aether-app/features/journey';
import { useProfileJourney } from '@aether-app/features/journeys/use-profile-journey';
import {
  density, episodeOpen, episodeTitle, formatClock, formatDuration, formatWhen, segmentEpisodes, stepLabel,
  stepLane, stepPlain, stepRaw, stepTime, stepWho, systemsTouched, visibleLanes, type Episode,
} from '@aether-app/features/journeys/journey-model';
import { useUserProfile } from '@aether-app/features/users/use-user-profile';
import { profileIdentity } from '@aether-app/pages/user-profile/profile-model';
import { OutLink, ParticipantsGrid, Quiet } from '@aether-app/pages/journeys/journey-detail-page';

type Tab = 'overview' | 'timeline' | 'sessions' | 'participants' | 'evidence';

const TABS: ReadonlyArray<readonly [Tab, string]> = [
  ['overview', 'Overview'],
  ['timeline', 'Timeline'],
  ['sessions', 'Sessions'],
  ['participants', 'Participants'],
  ['evidence', 'Evidence'],
];

const enc = encodeURIComponent;

/** Index of each agent's first step: the point it entered the episode. */
function spawnPoints(steps: readonly JourneyStep[]): number[] {
  const seen = new Set<string>();
  const out: number[] = [];
  steps.forEach((s, i) => {
    if (s.agent_id && !seen.has(s.agent_id)) {
      seen.add(s.agent_id);
      out.push(i);
    }
  });
  return out;
}

function Sessions({ episode }: { episode: Episode }) {
  const [open, setOpen] = useState<string | null>(episode.sessions[0] ? (episode.sessions[0].id ?? '∅') : null);
  return (
    <div className="flex flex-col gap-2.5" data-testid="episode-sessions">
      <Quiet>Sessions live inside an episode. They are not a destination of their own.</Quiet>
      {episode.sessions.map(s => {
        const key = s.id ?? '∅';
        const expanded = open === key;
        const first = stepTime(s.steps[0]!);
        const last = stepTime(s.steps[s.steps.length - 1]!);
        return (
          <div key={key} className="ae-glass-card flex flex-col rounded-[16px] px-4 py-2.5">
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() => setOpen(expanded ? null : key)}
              className="ae-focus flex w-full items-center justify-between gap-3 text-left"
            >
              <span className="flex min-w-0 flex-col">
                <span className={`truncate text-[14px] font-medium ${s.id ? 'ae-mono' : ''}`}>{s.id ?? 'Steps without a session id'}</span>
                <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                  {formatClock(first)} – {formatClock(last)} · {formatDuration(first !== null && last !== null ? last - first : null)}
                </span>
              </span>
              <span className="ae-mono flex-none text-[12px]" style={{ color: 'var(--ae-mute)' }}>{s.steps.length} events</span>
            </button>
            {expanded && (
              <ul className="mt-2 flex flex-col gap-1 border-t pt-2" style={{ borderColor: 'var(--ae-edge-soft)' }}>
                {s.steps.map(st => (
                  <li key={st.step_id} className="flex items-center gap-2 text-[13px]">
                    <span className="ae-mono w-[72px] flex-none text-[11px]" style={{ color: 'var(--ae-mute)' }}>{formatClock(stepTime(st))}</span>
                    <LaneDot step={st} />
                    <span className="truncate">{stepLabel(st)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Open episode (design: Aether Episodes, open view). The episode is derived
 * from the profile's compiled journey (30-minute gap rule) and addressed by
 * its first step id. Route: /episodes/:profileId/:episodeId (`?tab=`).
 */
export function EpisodeDetailPage() {
  const { profileId = '', episodeId = '' } = useParams<{ profileId: string; episodeId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab') as Tab | null;
  const tab: Tab = TABS.some(([t]) => t === tabParam) ? tabParam! : 'overview';
  const [mode, setMode] = useState<EvidenceMode>('plain');
  const { data, isLoading, error, refetch } = useProfileJourney(profileId);
  const profile = useUserProfile(profileId);
  const identity = profileIdentity(profile.data, profileId);
  const episode = useMemo(
    () => segmentEpisodes(data?.steps ?? []).find(e => e.id === episodeId) ?? null,
    [data, episodeId],
  );
  const steps = episode?.steps ?? [];
  const replay = useReplay(steps.length);
  const current = steps[replay.index];
  const dens = useMemo(() => density(steps), [steps]);

  const setTab = (t: Tab) => {
    const params = new URLSearchParams(searchParams);
    if (t === 'overview') params.delete('tab');
    else params.set('tab', t);
    setSearchParams(params);
  };

  const listHref = `/episodes?profile=${enc(profileId)}`;
  const title = episode ? `Episode ${episode.number} · ${episodeTitle(episode)}` : 'Episode';

  let body;
  if (error) {
    body = (
      <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-4" role="alert">
        <span className="text-[15px] font-medium">This episode is unavailable right now</span>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{error}</span>
        <button type="button" onClick={() => void refetch()} className="ae-btn-secondary ae-focus px-5 py-[9px]">Try again</button>
      </div>
    );
  } else if (isLoading || !data) {
    body = (
      <div className="flex items-center gap-2.5 py-10 text-[13px]" style={{ color: 'var(--ae-mute)' }} data-testid="episode-loading">
        <Spinner size={20} /> Loading episode…
      </div>
    );
  } else if (!episode) {
    body = (
      <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-5" data-testid="episode-missing">
        <span className="text-[15px] font-medium">Episode not found</span>
        <Quiet>This journey no longer has an episode starting at that step. It may have been recompiled.</Quiet>
        <Link to={listHref} className="ae-btn-secondary ae-focus mt-1 px-5 py-[9px]">All episodes</Link>
      </div>
    );
  } else {
    const dur = episode.start !== null && episode.end !== null ? episode.end - episode.start : null;
    const outcomes = steps.filter(s => s.activity_family === 'outcome' || s.activity_family === 'commerce');
    const actors = new Set(steps.map(stepLane)).size;
    body = (
      <>
        <PageTabs tabs={TABS} value={tab} onChange={setTab} label="Episode sections" />
        {tab === 'overview' && (
          <div className="flex flex-col gap-4">
            <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))' }} data-testid="episode-kpis">
              <MetricTile label="Events" value={steps.length} />
              <MetricTile label="Duration" value={formatDuration(dur)} />
              <MetricTile label="Sessions" value={episode.sessions.filter(s => s.id).length} />
              <MetricTile label="Actor classes" value={actors} sub={visibleLanes(steps).filter(l => steps.some(s => stepLane(s) === l.key)).map(l => l.label).join(', ')} />
              <MetricTile label="Peak" value={Math.max(0, ...dens.bins)} sub={dens.binMs === 60_000 ? 'events in a minute' : `events per ${formatDuration(dens.binMs)}`} />
            </div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]" data-testid="episode-overview-grid">
              <Panel className="flex flex-col gap-3 px-4 py-4 sm:px-5">
                <SwimlaneReplay
                  steps={steps}
                  replay={replay}
                  spawns={spawnPoints(steps)}
                  footer={<DensityStrip density={dens} cursor={current ? stepTime(current) : null} />}
                />
              </Panel>
              <div className="flex flex-col gap-4">
                <Panel className="flex flex-col gap-2 px-4 py-4">
                  <Eyebrow>Now</Eyebrow>
                  {current && (
                    <>
                      <span className="flex items-center gap-2">
                        <LaneDot step={current} size={10} />
                        <span className="flex min-w-0 flex-col">
                          <span className="truncate text-[14px] font-medium">{stepLabel(current)}</span>
                          <span className="truncate text-[12px]" style={{ color: 'var(--ae-mute)' }}>{stepWho(current)} · {formatClock(stepTime(current))}</span>
                        </span>
                      </span>
                      <span className="text-[13px]" data-testid="episode-now">{stepPlain(current)}</span>
                    </>
                  )}
                </Panel>
                <Panel className="flex flex-col gap-2 px-4 py-4">
                  <Eyebrow>Systems touched</Eyebrow>
                  <SystemsTouched systems={systemsTouched(steps)} />
                  <Eyebrow className="pt-2">Outcome</Eyebrow>
                  {outcomes.length === 0
                    ? <Quiet>No outcome or commerce step is recorded in this episode.</Quiet>
                    : outcomes.map(s => <span key={s.step_id} className="text-[13px]">{stepLabel(s)} · {formatClock(stepTime(s))}</span>)}
                </Panel>
              </div>
            </div>
          </div>
        )}
        {tab === 'timeline' && (
          <Panel className="flex flex-col gap-3 px-4 py-4 sm:px-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Quiet>Select an event to move the replay to it.</Quiet>
              <EvidenceModeToggle mode={mode} onChange={setMode} />
            </div>
            <ol className="flex flex-col" data-testid="episode-timeline">
              {steps.map((s, i) => (
                <li key={s.step_id} className="border-b last:border-b-0" style={{ borderColor: 'var(--ae-edge-soft)' }}>
                  <button
                    type="button"
                    onClick={() => { replay.seek(i); setTab('overview'); }}
                    className="ae-focus grid w-full items-start gap-x-3 py-2.5 text-left"
                    style={{ gridTemplateColumns: '72px 10px minmax(0,1fr)' }}
                  >
                    <span className="ae-mono pt-0.5 text-[11px]" style={{ color: 'var(--ae-mute)' }}>{formatClock(stepTime(s))}</span>
                    <span className="pt-1.5"><LaneDot step={s} /></span>
                    <span className="flex min-w-0 flex-col gap-1">
                      <span className="truncate text-[14px]">{stepLabel(s)}</span>
                      {mode === 'plain'
                        ? <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>{stepPlain(s)}</span>
                        : <RawFields rows={stepRaw(s)} />}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </Panel>
        )}
        {tab === 'sessions' && <Sessions episode={episode} />}
        {tab === 'participants' && <ParticipantsGrid steps={steps} profileId={profileId} profileName={identity.name} />}
        {tab === 'evidence' && (
          <div className="flex flex-col gap-3" data-testid="episode-evidence">
            <div className="flex justify-end"><EvidenceModeToggle mode={mode} onChange={setMode} /></div>
            <ul className="flex flex-col gap-2">
              {steps.map(s => (
                <li key={s.step_id} className="flex flex-col gap-1.5 rounded-[14px] px-3.5 py-2.5" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
                  {mode === 'plain'
                    ? <span className="text-[13px]">{formatClock(stepTime(s))} — {stepLabel(s)}. {stepPlain(s)}</span>
                    : <RawFields rows={stepRaw(s)} />}
                </li>
              ))}
            </ul>
          </div>
        )}
      </>
    );
  }

  return (
    <GlassPage>
      <div className="flex min-w-0 flex-col gap-4" data-testid="aether-episode-detail">
        <Crumb to={listHref} section="Episodes" name={title} />
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <span className="flex flex-wrap items-center gap-2.5">
              <h1 className="truncate text-[clamp(22px,3vw,28px)] font-medium tracking-[-0.5px]">{title}</h1>
              {episode && <TonePill tone={episodeOpen(episode) ? 'sage' : 'mute'}>{episodeOpen(episode) ? 'active' : 'closed'}</TonePill>}
            </span>
            {episode && (
              <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
                {formatWhen(episode.start)} · {formatDuration(episode.start !== null && episode.end !== null ? episode.end - episode.start : null)}
              </span>
            )}
            <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
              Part of <Link to={`/journeys/${enc(profileId)}`} className="ae-focus hover:underline" style={{ color: 'var(--ae-blue-ink)' }}>{identity.name}&apos;s journey</Link>
            </span>
          </div>
          <span className="flex flex-wrap gap-1.5">
            <OutLink to={`/users/${enc(profileId)}`}>Profile 360</OutLink>
            <OutLink to={`/explore?entity=${enc(profileId)}`}>Open in Graph</OutLink>
          </span>
        </div>
        {body}
      </div>
    </GlassPage>
  );
}
