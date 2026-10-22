import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Icon } from '@aether/ui';
import { GlassPage } from '@aether-app/components/app-shell';
import {
  Eyebrow, InlineNotice, LinkButton, Panel, PrimaryButton, SecondaryButton, Spinner, TonePill,
} from '@aether-app/components/ae-ui';
import { SegmentedTabs } from '@aether-app/components/ae-campaigns-geo-ui';
import { LaneDot } from '@aether-app/components/ae-journeys-ui';
import { useUsers, type UserRow } from '@aether-app/features/users/use-users';
import { useProfileJourney } from '@aether-app/features/journeys/use-profile-journey';
import {
  formatDuration, formatWhen, humanizeToken, journeyStateTone, span, stepLabel,
} from '@aether-app/features/journeys/journey-model';
import { ago } from '@aether-app/pages/user-profile/profile-model';

type View = 'journeys' | 'paths';

const PREVIEW_STEPS = 6;

export function journeyHref(profileId: string): string {
  return `/journeys/${encodeURIComponent(profileId)}`;
}

/** Expanded journey preview for one profile: state, span and the step chain. */
function JourneyPreview({ profileId }: { profileId: string }) {
  const navigate = useNavigate();
  const { data, isLoading, error } = useProfileJourney(profileId);

  let body;
  if (error) {
    body = <InlineNotice tone="amber">This journey is unavailable right now.</InlineNotice>;
  } else if (isLoading || !data) {
    body = <span className="flex items-center gap-2 text-[12px]" style={{ color: 'var(--ae-mute)' }}><Spinner size={14} /> Loading journey…</span>;
  } else if (data.steps.length === 0) {
    body = (
      <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
        {data.meta?.quality_status === 'not_provisioned'
          ? 'No journey has been compiled for this profile yet. Compilation starts when its activity is ingested.'
          : 'This journey has no steps yet.'}
      </span>
    );
  } else {
    const sp = span(data.steps);
    const total = data.summary?.stepCount ?? data.meta?.step_count ?? data.steps.length;
    body = (
      <>
        <span className="flex flex-wrap items-center gap-2 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          {data.summary?.state && <TonePill tone={journeyStateTone(data.summary.state)}>{humanizeToken(data.summary.state)}</TonePill>}
          <span><span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{total}</span> steps</span>
          <span>· started {formatWhen(sp.start)}</span>
          <span>· {formatDuration(sp.ms)}</span>
        </span>
        <ol className="flex flex-wrap items-center gap-1.5" aria-label="Journey steps">
          {data.steps.slice(0, PREVIEW_STEPS).map((s, i) => (
            <li key={s.step_id} className="flex items-center gap-1.5">
              {i > 0 && <span className="h-px w-3" style={{ background: 'var(--ae-edge)' }} aria-hidden="true" />}
              <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12px]" style={{ background: 'var(--ae-edge-soft)' }}>
                <LaneDot step={s} size={7} />
                {stepLabel(s)}
              </span>
            </li>
          ))}
          {total > PREVIEW_STEPS && <li className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>+{total - PREVIEW_STEPS} more</li>}
        </ol>
      </>
    );
  }

  return (
    <div className="flex flex-col gap-2.5 border-t pt-3" style={{ borderColor: 'var(--ae-edge)' }} data-testid="journey-preview">
      {body}
      <div className="flex flex-wrap gap-2">
        <PrimaryButton onClick={() => void navigate(journeyHref(profileId))} data-testid="open-journey">Open journey →</PrimaryButton>
        <SecondaryButton onClick={() => void navigate(`/explore?entity=${encodeURIComponent(profileId)}`)}>Open in Graph →</SecondaryButton>
      </div>
    </div>
  );
}

function JourneyRow({ row, expanded, onToggle }: { row: UserRow; expanded: boolean; onToggle: () => void }) {
  const lastSeen = ago(row.lastSeenAt);
  return (
    <div className="ae-glass-card flex flex-col gap-2 rounded-[20px] px-5 py-4" style={expanded ? { borderColor: 'var(--ae-blue)' } : undefined} data-journey-row={row.id}>
      <button type="button" onClick={onToggle} aria-expanded={expanded} className="ae-focus flex w-full min-w-0 items-start justify-between gap-3 text-left">
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className={`truncate text-[16px] font-medium tracking-[-0.3px] ${row.displayName === row.id ? 'ae-mono text-[14px]' : ''}`}>{row.displayName}</span>
          <span className="truncate text-[12px]" style={{ color: 'var(--ae-mute)' }}>
            {[
              'Journey',
              lastSeen ? `last active ${lastSeen}` : null,
              row.sessionCount30d !== undefined ? `${row.sessionCount30d} sessions in 30 days` : null,
            ].filter(Boolean).join(' · ')}
          </span>
        </span>
        <Icon name={expanded ? 'circle-minus' : 'circle-plus'} decorative size="sm" className="mt-1 flex-none opacity-50" />
      </button>
      {expanded && <JourneyPreview profileId={row.id} />}
    </div>
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

/**
 * Journeys (design: Aether Journeys). Aether compiles one journey per
 * profile and the app has no tenant-wide journey list read, so journeys are
 * listed by profile; a row expands to that profile's compiled journey and
 * "Open journey" goes to /journeys/:profileId. `?view=paths` shows Aggregate
 * Paths, which is honestly unavailable until a path read exists.
 */
export function JourneysPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { users, search, setSearch, isLoading, error, reload } = useUsers();
  const view: View = searchParams.get('view') === 'paths' ? 'paths' : 'journeys';
  const expanded = searchParams.get('profile');

  const setParam = (key: string, value: string | null) => {
    const params = new URLSearchParams(searchParams);
    if (value === null) params.delete(key);
    else params.set(key, value);
    setSearchParams(params);
  };

  return (
    <GlassPage>
      <div className="flex min-w-0 flex-col gap-4" data-testid="aether-journeys">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-1">
            <h1 className="text-[clamp(26px,3.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Journeys</h1>
            <span className="text-[14px]" style={{ color: 'var(--ae-mute)' }}>Follow how people and agents move from one event to the next.</span>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
            {view === 'journeys' && (
              <label className="ae-card flex min-w-0 flex-1 items-center gap-2 rounded-full px-4 py-2 sm:min-w-[240px]">
                <Icon name="search" decorative size="sm" className="opacity-60" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Search journeys by profile"
                  aria-label="Search journeys"
                  className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-[var(--ae-faint)]"
                />
              </label>
            )}
            <SegmentedTabs<View>
              label="Journeys view"
              value={view}
              onChange={v => setParam('view', v === 'journeys' ? null : v)}
              options={[{ value: 'journeys', label: 'Journeys' }, { value: 'paths', label: 'Aggregate paths' }]}
            />
          </div>
        </div>

        {view === 'paths' ? (
          <AggregatePaths onBrowse={() => setParam('view', null)} />
        ) : (
          <>
            <InlineNotice tone="blue">
              Aether compiles one journey per profile. A tenant-wide journey list and journey-state counts are not
              available from the API yet, so journeys are listed by profile.
            </InlineNotice>
            {error ? (
              <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-4" role="alert">
                <span className="text-[15px] font-medium">Journeys are unavailable right now</span>
                <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{error}</span>
                <SecondaryButton onClick={reload}>Try again</SecondaryButton>
              </div>
            ) : isLoading ? (
              <div className="flex items-center gap-2.5 py-10 text-[13px]" style={{ color: 'var(--ae-mute)' }} data-testid="journeys-loading">
                <Spinner size={20} /> Loading journeys…
              </div>
            ) : users.length === 0 ? (
              <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-5">
                <span className="text-[15px] font-medium">No journeys match</span>
                <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
                  {search
                    ? `No profiles match "${search}".`
                    : 'Journeys appear once your first source sends events and Aether compiles them per profile.'}
                </span>
                {!search && <Link to="/activation" className="ae-btn-primary ae-focus mt-1 px-5 py-[9px]">Connect your first source</Link>}
              </div>
            ) : (
              <>
                <div className="flex flex-wrap justify-between gap-2 text-[13px]" style={{ color: 'var(--ae-mute)' }}>
                  <span><span className="font-medium" style={{ color: 'var(--ae-ink)' }}>{users.length}</span> profile journey{users.length === 1 ? '' : 's'}{search ? ` matching "${search}"` : ''}</span>
                  {expanded && <LinkButton tone="mute" onClick={() => setParam('profile', null)}>Collapse</LinkButton>}
                </div>
                <div className="flex flex-col gap-3" data-testid="journeys-list">
                  {users.map(u => (
                    <JourneyRow
                      key={u.id}
                      row={u}
                      expanded={expanded === u.id}
                      onToggle={() => setParam('profile', expanded === u.id ? null : u.id)}
                    />
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </GlassPage>
  );
}
