import { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Icon } from '@aether/ui';
import { GlassPage } from '@aether-app/components/app-shell';
import { ChoiceChip, InlineNotice, SecondaryButton, Spinner, TonePill } from '@aether-app/components/ae-ui';
import { SegmentedTabs } from '@aether-app/components/ae-campaigns-geo-ui';
import { MiniDensity } from '@aether-app/components/ae-journeys-ui';
import { BrandMark } from '@aether-app/components/brand-mark';
import { useUsers } from '@aether-app/features/users/use-users';
import { useProfileJourney } from '@aether-app/features/journeys/use-profile-journey';
import {
  EPISODE_BUCKETS, density, episodeBucket, episodeOpen, episodeTitle, formatDuration, formatWhen,
  segmentEpisodes, stepTime, systemsTouched, type EpisodeBucket,
} from '@aether-app/features/journeys/journey-model';
import { episodeHref } from '@aether-app/pages/journeys/journey-detail-page';

const enc = encodeURIComponent;

/** Episodes of one profile's journey, bucketed by day and grouped under the journey. */
function ProfileEpisodes({ profileId, profileName, bucket, onBucket }: {
  profileId: string;
  profileName: string;
  bucket: EpisodeBucket | null;
  onBucket: (b: EpisodeBucket) => void;
}) {
  const { data, isLoading, error, refetch } = useProfileJourney(profileId);
  const episodes = useMemo(() => segmentEpisodes(data?.steps ?? []), [data]);
  // Pin "now" to the read so buckets stay stable between renders.
  const now = useMemo(() => Date.now(), [data]);
  const counts = useMemo(() => {
    const c: Record<EpisodeBucket, number> = { today: 0, yesterday: 0, week: 0, earlier: 0 };
    for (const ep of episodes) c[episodeBucket(ep, now)] += 1;
    return c;
  }, [episodes, now]);

  if (error) {
    return (
      <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-4" role="alert">
        <span className="text-[15px] font-medium">Episodes are unavailable right now</span>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{error}</span>
        <SecondaryButton onClick={() => void refetch()}>Try again</SecondaryButton>
      </div>
    );
  }
  if (isLoading || !data) {
    return (
      <div className="flex items-center gap-2.5 py-10 text-[13px]" style={{ color: 'var(--ae-mute)' }} data-testid="episodes-loading">
        <Spinner size={20} /> Loading episodes…
      </div>
    );
  }
  if (episodes.length === 0) {
    return (
      <div className="ae-card flex flex-col items-start gap-1.5 rounded-[20px] px-5 py-5" data-testid="episodes-empty">
        <span className="text-[15px] font-medium">No episodes yet</span>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
          {data.meta?.quality_status === 'not_provisioned'
            ? `No journey has been compiled for ${profileName} yet. Episodes appear once its activity is ingested.`
            : `${profileName}'s journey has no steps yet.`}
        </span>
      </div>
    );
  }

  const active = bucket ?? EPISODE_BUCKETS.find(([b]) => counts[b] > 0)![0];
  const shown = episodes.filter(ep => episodeBucket(ep, now) === active).reverse();
  const lastHour = data.steps.filter(s => {
    const t = stepTime(s);
    return t !== null && now - t <= 3_600_000;
  }).length;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SegmentedTabs<EpisodeBucket>
          label="Episode period"
          value={active}
          onChange={onBucket}
          options={EPISODE_BUCKETS.map(([value, label]) => ({ value, label, badge: counts[value] }))}
        />
        <span className="flex items-center gap-1.5 text-[12px]" style={{ color: 'var(--ae-mute)' }} data-testid="episodes-last-hour">
          <span className={`h-1.5 w-1.5 rounded-full ${lastHour > 0 ? 'ae-pulse' : ''}`} style={{ background: lastHour > 0 ? 'var(--ae-sage)' : 'var(--ae-faint)' }} />
          {lastHour} event{lastHour === 1 ? '' : 's'} in the last hour
        </span>
      </div>

      <div className="flex flex-col gap-2.5" data-testid="episodes-group">
        <span className="flex items-baseline gap-2">
          <Link to={`/journeys/${enc(profileId)}`} className="ae-focus text-[15px] font-medium hover:underline">{profileName} →</Link>
          <span className="ae-eyebrow">Journey</span>
        </span>
        {shown.length === 0 ? (
          <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No episodes here.</span>
        ) : shown.map(ep => {
          const open = episodeOpen(ep, now);
          const systems = systemsTouched(ep.steps, 4);
          const sessions = ep.sessions.filter(s => s.id).length;
          return (
            <Link
              key={ep.id}
              to={episodeHref(profileId, ep.id)}
              className="ae-focus ae-glass-card flex flex-wrap items-center justify-between gap-3 rounded-[18px] px-4 py-3 hover:border-[var(--ae-blue)]"
              data-episode={ep.id}
            >
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-[14px] font-medium">Episode {ep.number} · {episodeTitle(ep)}</span>
                  <TonePill tone={open ? 'sage' : 'mute'}>{open ? 'active' : 'closed'}</TonePill>
                </span>
                <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                  {formatWhen(ep.start)} · {formatDuration(ep.start !== null && ep.end !== null ? ep.end - ep.start : null)} · {ep.steps.length} event{ep.steps.length === 1 ? '' : 's'}{sessions ? ` · ${sessions} session${sessions === 1 ? '' : 's'}` : ''}
                </span>
                {systems.length > 0 && (
                  <span className="flex gap-1">{systems.map(s => <BrandMark key={s} token={s} label={s} size={20} shape="round" />)}</span>
                )}
              </span>
              <MiniDensity bins={density(ep.steps, 12).bins} />
              <span className="text-[12px]" style={{ color: 'var(--ae-blue-ink)' }}>Open episode →</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Episodes (design: Aether Episodes). Episodes are concentrated periods of
 * activity inside a journey. The API exposes no compiled episodes or
 * tenant-wide list yet, so this page derives them from one profile's compiled
 * journey (a new episode after 30 minutes without a step) and lets the viewer
 * pick the profile (`?profile=`). `?when=` selects Today / Yesterday /
 * This week / Earlier. Cards open /episodes/:profileId/:episodeId.
 */
export function EpisodesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { users, search, setSearch, isLoading, error, reload } = useUsers();
  const sorted = useMemo(
    () => [...users].sort((a, b) => (Date.parse(b.lastSeenAt ?? '') || 0) - (Date.parse(a.lastSeenAt ?? '') || 0)),
    [users],
  );
  const profileParam = searchParams.get('profile');
  const profileId = profileParam ?? sorted[0]?.id ?? null;
  const profileName = users.find(u => u.id === profileId)?.displayName ?? profileId ?? '';
  const whenParam = searchParams.get('when');
  const bucket = EPISODE_BUCKETS.some(([b]) => b === whenParam) ? (whenParam as EpisodeBucket) : null;

  const setParams = (patch: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) params.delete(k);
      else params.set(k, v);
    }
    setSearchParams(params);
  };

  const chips = sorted.slice(0, 8);
  if (profileId && !chips.some(u => u.id === profileId)) {
    const u = sorted.find(x => x.id === profileId);
    chips.unshift(u ?? { id: profileId, displayName: profileId });
  }

  return (
    <GlassPage>
      <div className="flex min-w-0 flex-col gap-4" data-testid="aether-episodes">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-1">
            <h1 className="text-[clamp(26px,3.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Episodes</h1>
            <span className="text-[14px]" style={{ color: 'var(--ae-mute)' }}>Concentrated periods of activity. Each one belongs to a journey.</span>
          </div>
          <label className="ae-card flex w-full min-w-0 items-center gap-2 rounded-full px-4 py-2 sm:w-auto sm:min-w-[240px]">
            <Icon name="search" decorative size="sm" className="opacity-60" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search episodes by profile"
              aria-label="Search episodes"
              className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-[var(--ae-faint)]"
            />
          </label>
        </div>

        <InlineNotice tone="blue">
          The API does not expose compiled episodes yet. Aether derives them from a profile&apos;s compiled journey:
          a new episode starts after 30 minutes without a step.
        </InlineNotice>

        {error ? (
          <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-4" role="alert">
            <span className="text-[15px] font-medium">Profiles are unavailable right now</span>
            <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{error}</span>
            <SecondaryButton onClick={reload}>Try again</SecondaryButton>
          </div>
        ) : isLoading && !profileParam ? (
          <div className="flex items-center gap-2.5 py-10 text-[13px]" style={{ color: 'var(--ae-mute)' }} data-testid="episodes-profiles-loading">
            <Spinner size={20} /> Loading profiles…
          </div>
        ) : !profileId ? (
          <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-5">
            <span className="text-[15px] font-medium">No episodes here</span>
            <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
              {search ? `No profiles match "${search}".` : 'Episodes appear once your first source sends events and journeys are compiled.'}
            </span>
            {!search && <Link to="/activation" className="ae-btn-primary ae-focus mt-1 px-5 py-[9px]">Connect your first source</Link>}
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Profile">
              <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Journey of</span>
              {chips.map(u => (
                <ChoiceChip key={u.id} size="sm" selected={u.id === profileId} onClick={() => setParams({ profile: u.id, when: null })}>
                  {u.displayName}
                </ChoiceChip>
              ))}
            </div>
            <ProfileEpisodes
              key={profileId}
              profileId={profileId}
              profileName={profileName}
              bucket={bucket}
              onBucket={b => setParams({ when: b })}
            />
          </>
        )}
      </div>
    </GlassPage>
  );
}
