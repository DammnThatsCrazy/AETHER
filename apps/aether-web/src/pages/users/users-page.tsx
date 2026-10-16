import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Icon } from '@aether/ui';
import { GlassPage } from '@aether-app/components/app-shell';
import {
  ChoiceChip, Eyebrow, InlineNotice, LinkButton, PrimaryButton, SecondaryButton, Spinner, TonePill, type Tone,
} from '@aether-app/components/ae-ui';
import { useUsers, type UserRow } from '@aether-app/features/users/use-users';
import { useUserGraph, useUserProfile } from '@aether-app/features/users/use-user-profile';
import {
  NETWORK_GROUPS, ago, humanize, initials, profileIdentity, profileNetwork,
} from '@aether-app/pages/user-profile/profile-model';
import { ProfileNetworkMap, neighbourHref } from '@aether-app/pages/user-profile/profile-network-map';

type Mode = 'list' | 'map' | 'activity';
type SortKey = 'recent' | 'trust' | 'risk' | 'name';

const MODES: ReadonlyArray<readonly [Mode, string]> = [
  ['list', 'List'],
  ['map', 'Relationship Map'],
  ['activity', 'Activity'],
];

const SORTS: ReadonlyArray<readonly [SortKey, string]> = [
  ['recent', 'Last seen'],
  ['trust', 'Trust'],
  ['risk', 'Risk'],
  ['name', 'Name'],
];

/** The list endpoint returns at most this many profiles without a search. */
const LIST_LIMIT = 100;

function churnTone(risk: string): Tone {
  return risk === 'low' ? 'sage' : risk === 'churned' ? 'ember' : 'amber';
}

function scorePct(v: number | undefined): string | null {
  return v === undefined ? null : `${Math.round(v * 100)}`;
}

function sortUsers(users: readonly UserRow[], key: SortKey): UserRow[] {
  const copy = [...users];
  const time = (u: UserRow) => (u.lastSeenAt ? Date.parse(u.lastSeenAt) || 0 : 0);
  switch (key) {
    case 'trust': return copy.sort((a, b) => (b.trustScore ?? -1) - (a.trustScore ?? -1));
    case 'risk': return copy.sort((a, b) => (b.riskScore ?? -1) - (a.riskScore ?? -1));
    case 'name': return copy.sort((a, b) => a.displayName.localeCompare(b.displayName));
    default: return copy.sort((a, b) => time(b) - time(a));
  }
}

function Avatar({ name, size = 34 }: { name: string; size?: number }) {
  return (
    <span
      className="ae-mono flex flex-none items-center justify-center rounded-full text-[11px]"
      style={{ width: size, height: size, background: 'var(--ae-shell)', border: '1px solid var(--ae-edge)' }}
      aria-hidden="true"
    >
      {initials(name)}
    </span>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex min-w-0 flex-col rounded-[12px] px-3 py-2" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
      <span className="truncate text-[13px]">{value}</span>
      <span className="ae-eyebrow text-[10px]">{label}</span>
    </span>
  );
}

/**
 * Expanded detail for one profile (design: Aether Profiles, expanded card).
 * Reads the profile summary and its graph only while expanded; every fact
 * shown is from those reads or the list row — unknown fields are omitted.
 */
function ExpandedProfile({ row, profileId }: { row: UserRow | null; profileId: string }) {
  const navigate = useNavigate();
  const summary = useUserProfile(profileId);
  const graph = useUserGraph(profileId);
  const identity = profileIdentity(summary.data, profileId);
  const network = useMemo(() => profileNetwork(graph.data, profileId), [graph.data, profileId]);

  const facts: Array<[string, string]> = [];
  const lastSeen = ago(row?.lastSeenAt ?? identity.lastSeenAt);
  if (lastSeen) facts.push(['Last active', lastSeen]);
  const firstSeen = ago(row?.firstSeenAt ?? identity.firstSeenAt);
  if (firstSeen) facts.push(['First seen', firstSeen]);
  if (identity.kind) facts.push(['Kind', identity.kind]);
  if (row?.trustScore !== undefined) facts.push(['Trust', scorePct(row.trustScore)!]);
  if (row?.riskScore !== undefined) facts.push(['Risk', scorePct(row.riskScore)!]);
  if (row?.sessionCount30d !== undefined) facts.push(['Sessions (30d)', String(row.sessionCount30d)]);
  if (identity.counts.agents !== null) facts.push(['Agents', String(identity.counts.agents)]);
  if (identity.counts.wallets !== null) facts.push(['Wallets', String(identity.counts.wallets)]);
  if (identity.counts.journeys !== null) facts.push(['Journeys', String(identity.counts.journeys)]);
  if (!graph.isLoading && !graph.error) facts.push(['Relationships', String(network.links.length)]);

  return (
    <div className="flex flex-col gap-3 border-t pt-3.5" style={{ borderColor: 'var(--ae-edge)' }} data-testid="profile-expanded">
      {summary.isLoading && facts.length === 0 ? (
        <span className="flex items-center gap-2 text-[12px]" style={{ color: 'var(--ae-mute)' }}><Spinner size={14} /> Loading profile…</span>
      ) : facts.length > 0 ? (
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))' }}>
          {facts.map(([l, v]) => <Fact key={l} label={l} value={v} />)}
        </div>
      ) : (
        <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>No profile facts are reported yet.</span>
      )}
      {summary.error && <InlineNotice tone="amber">The profile summary is unavailable right now.</InlineNotice>}

      <div className="flex flex-col gap-1.5">
        <Eyebrow>Relationships</Eyebrow>
        {graph.isLoading ? (
          <span className="flex items-center gap-2 text-[12px]" style={{ color: 'var(--ae-mute)' }}><Spinner size={14} /> Loading relationships…</span>
        ) : graph.error ? (
          <span className="text-[12px]" style={{ color: 'var(--ae-amber)' }}>Relationships are unavailable right now.</span>
        ) : network.nodes.length === 0 ? (
          <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>No relationships recorded in the graph yet.</span>
        ) : (
          network.nodes.slice(0, 5).map(n => {
            const link = network.links.find(l => l.other === n.id);
            const color = NETWORK_GROUPS.find(g => g.key === n.group)?.color ?? 'var(--ae-mute)';
            return (
              <button
                key={n.id}
                type="button"
                onClick={e => { e.stopPropagation(); void navigate(neighbourHref(n).to); }}
                className="ae-focus flex min-w-0 items-center gap-2 text-left text-[13px] hover:underline"
              >
                <span className="h-[7px] w-[7px] flex-none rounded-full" style={{ background: color }} />
                <span className="truncate">{n.label}</span>
                <span className="flex-none" style={{ color: 'var(--ae-mute)' }}>
                  · {link?.relation ? humanize(link.relation) : n.kind ? humanize(n.kind) : 'related'}{link?.inferred ? ' (inferred)' : ''}
                </span>
              </button>
            );
          })
        )}
        {network.nodes.length > 5 && (
          <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>+{network.nodes.length - 5} more in Profile 360</span>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <PrimaryButton onClick={() => void navigate(`/users/${encodeURIComponent(profileId)}`)} data-testid="open-profile-360">
          Open Profile 360 →
        </PrimaryButton>
        <SecondaryButton onClick={() => void navigate(`/users/${encodeURIComponent(profileId)}/journey`)}>
          View journey
        </SecondaryButton>
      </div>
    </div>
  );
}

function ProfileCard({ row, expanded, onToggle }: { row: UserRow; expanded: boolean; onToggle: () => void }) {
  const lastSeen = ago(row.lastSeenAt);
  const line1 = [row.email, lastSeen ? `Active ${lastSeen}` : null].filter(Boolean).join(' · ');
  return (
    <div
      className="ae-glass-card flex flex-col gap-1.5 rounded-[20px] px-5 py-4"
      style={expanded ? { borderColor: 'var(--ae-blue)' } : undefined}
      data-profile-row={row.id}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="ae-focus flex w-full min-w-0 items-start gap-3 text-left"
      >
        <Avatar name={row.displayName} />
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-wrap items-baseline justify-between gap-x-2.5">
            <span className={`truncate text-[17px] font-medium tracking-[-0.3px] ${row.displayName === row.id ? 'ae-mono text-[15px]' : ''}`}>{row.displayName}</span>
            <span className="flex items-center gap-1.5">
              {row.churnRisk && <TonePill tone={churnTone(row.churnRisk)}>{row.churnRisk} churn</TonePill>}
              {row.loyaltyTier && row.loyaltyTier !== 'none' && <TonePill tone="solar">{row.loyaltyTier}</TonePill>}
              <Icon name={expanded ? 'circle-minus' : 'circle-plus'} decorative size="sm" className="text-current opacity-50" />
            </span>
          </span>
          {line1 && <span className="truncate text-[13px]" style={{ color: 'var(--ae-mute)' }}>{line1}</span>}
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
            {row.trustScore !== undefined && <span>Trust <span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{scorePct(row.trustScore)}</span></span>}
            {row.riskScore !== undefined && <span>Risk <span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{scorePct(row.riskScore)}</span></span>}
            {row.sessionCount30d !== undefined && <span><span className="ae-mono" style={{ color: 'var(--ae-ink)' }}>{row.sessionCount30d}</span> sessions (30d)</span>}
            {row.displayName !== row.id && <span className="ae-mono truncate" style={{ color: 'var(--ae-faint)' }}>{row.id}</span>}
          </span>
          {row.platforms && row.platforms.length > 0 && (
            <span className="flex flex-wrap items-center gap-1.5 pt-1">
              <span className="ae-eyebrow mr-1">Platforms</span>
              {row.platforms.slice(0, 4).map(p => (
                <span key={p} className="rounded-full px-2.5 py-0.5 text-[12px]" style={{ background: 'var(--ae-edge-soft)' }}>{p}</span>
              ))}
            </span>
          )}
        </span>
      </button>
      {expanded && <ExpandedProfile row={row} profileId={row.id} />}
    </div>
  );
}

function MapView({ users, selected, onSelect }: { users: readonly UserRow[]; selected: string; onSelect: (id: string) => void }) {
  const navigate = useNavigate();
  const graph = useUserGraph(selected);
  const network = useMemo(() => profileNetwork(graph.data, selected), [graph.data, selected]);
  const row = users.find(u => u.id === selected);
  const label = row?.displayName ?? selected;
  return (
    <div className="flex flex-col gap-3" data-testid="profiles-map">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Mapping</span>
        {users.slice(0, 8).map(u => (
          <ChoiceChip key={u.id} size="sm" selected={u.id === selected} onClick={() => onSelect(u.id)}>{u.displayName}</ChoiceChip>
        ))}
      </div>
      {graph.isLoading ? (
        <span className="flex items-center gap-2 py-10 text-[13px]" style={{ color: 'var(--ae-mute)' }}><Spinner size={18} /> Loading relationships…</span>
      ) : graph.error ? (
        <InlineNotice tone="amber">Relationships for {label} are unavailable right now.</InlineNotice>
      ) : network.nodes.length === 0 ? (
        <p className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No relationships are recorded in the graph for {label} yet.</p>
      ) : (
        <ProfileNetworkMap network={network} rootLabel={label} />
      )}
      <div className="ae-glass-card flex flex-wrap items-center justify-between gap-3 rounded-[18px] px-4 py-3">
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-[15px] font-medium">{label}</span>
          <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
            {graph.isLoading || graph.error ? 'relationships' : `${network.links.length} relationship${network.links.length === 1 ? '' : 's'}`}
            {row?.lastSeenAt ? ` · active ${ago(row.lastSeenAt)}` : ''}
          </span>
        </span>
        <PrimaryButton onClick={() => void navigate(`/users/${encodeURIComponent(selected)}`)}>Open Profile 360 →</PrimaryButton>
      </div>
    </div>
  );
}

function ActivityView({ users, onOpen }: { users: readonly UserRow[]; onOpen: (id: string) => void }) {
  const seen = sortUsers(users.filter(u => u.lastSeenAt), 'recent');
  const unseen = users.length - seen.length;
  if (seen.length === 0) {
    return <p className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No last-seen activity is reported for these profiles yet.</p>;
  }
  return (
    <div className="flex flex-col" data-testid="profiles-activity">
      <ol className="flex flex-col">
        {seen.map(u => (
          <li key={u.id} className="grid gap-x-3" style={{ gridTemplateColumns: 'minmax(64px, 90px) 14px 1fr' }}>
            <span className="ae-mono pt-0.5 text-right text-[11px]" style={{ color: 'var(--ae-mute)' }}>{ago(u.lastSeenAt)}</span>
            <span className="flex flex-col items-center">
              <span className="mt-1 h-2.5 w-2.5 rounded-full" style={{ background: u.churnRisk ? `var(--ae-${churnTone(u.churnRisk)})` : 'var(--ae-blue)' }} />
              <span className="w-px flex-1" style={{ background: 'var(--ae-edge)' }} />
            </span>
            <button type="button" onClick={() => onOpen(u.id)} className="ae-focus min-w-0 pb-4 text-left">
              <span className="block truncate text-[14px] font-medium hover:underline">{u.displayName}</span>
              <span className="block truncate text-[13px]" style={{ color: 'var(--ae-mute)' }}>
                {[
                  u.sessionCount30d !== undefined ? `${u.sessionCount30d} sessions in 30 days` : null,
                  u.platforms?.length ? u.platforms.slice(0, 3).join(', ') : null,
                  u.churnRisk ? `${u.churnRisk} churn risk` : null,
                ].filter(Boolean).join(' · ') || 'last seen'}
              </span>
            </button>
          </li>
        ))}
      </ol>
      {unseen > 0 && <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>{unseen} profile{unseen === 1 ? '' : 's'} without a reported last-seen time are not shown.</span>}
    </div>
  );
}

/**
 * Profiles (design: Aether Profiles). Lists the tenant's profiles from the
 * entity registry; a row expands in place, and `?profile=<id>` opens the page
 * with that profile expanded at the top (links from Home and the Profile 360
 * breadcrumb use it). "Open Profile 360" goes to /users/:id.
 */
export function UsersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { users, search, setSearch, isLoading, error, reload } = useUsers();
  const [sort, setSort] = useState<SortKey>('recent');
  const selected = searchParams.get('profile');
  const modeParam = searchParams.get('view');
  const mode: Mode = modeParam === 'map' || modeParam === 'activity' ? modeParam : 'list';

  const setParam = (key: string, value: string | null) => {
    const params = new URLSearchParams(searchParams);
    if (value === null) params.delete(key);
    else params.set(key, value);
    setSearchParams(params);
  };

  const sorted = useMemo(() => {
    const list = sortUsers(users, sort);
    // The selected profile sits first, already expanded.
    const i = selected ? list.findIndex(u => u.id === selected) : -1;
    if (i > 0) list.unshift(...list.splice(i, 1));
    return list;
  }, [users, sort, selected]);
  const selectedMissing = !!selected && !isLoading && !error && !users.some(u => u.id === selected);
  const mapTarget = selected ?? sorted[0]?.id ?? null;

  return (
    <GlassPage>
      <div className="flex min-w-0 flex-col gap-4" data-testid="aether-profiles">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-1">
            <h1 className="text-[clamp(26px,3.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Profiles</h1>
            <span className="text-[14px]" style={{ color: 'var(--ae-mute)' }}>Understand the people and entities Aether knows.</span>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
            <label className="ae-card flex min-w-0 flex-1 items-center gap-2 rounded-full px-4 py-2 sm:min-w-[260px]">
              <Icon name="search" decorative size="sm" className="opacity-60" />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search by name, email, wallet, device ID…"
                aria-label="Search profiles"
                className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-[var(--ae-faint)]"
              />
            </label>
            <button type="button" onClick={reload} className="ae-focus ae-card flex items-center gap-1.5 rounded-full px-3.5 py-2 text-[13px]">
              <Icon name="refresh-cw" decorative size="sm" /> Refresh
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="inline-flex flex-wrap gap-0.5 rounded-[22px] p-[3px]" style={{ background: 'var(--ae-edge-soft)' }} role="tablist" aria-label="Profiles view">
            {MODES.map(([m, label]) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => setParam('view', m === 'list' ? null : m)}
                className="ae-focus rounded-full px-3.5 py-1.5 text-[13px]"
                style={{ background: mode === m ? 'var(--ae-chip-on)' : 'transparent', color: mode === m ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)' }}
              >
                {label}
              </button>
            ))}
          </span>
          {mode === 'list' && (
            <span className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Sort profiles">
              <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Sort</span>
              {SORTS.map(([k, label]) => (
                <ChoiceChip key={k} size="sm" selected={sort === k} onClick={() => setSort(k)}>{label}</ChoiceChip>
              ))}
            </span>
          )}
        </div>

        {error ? (
          <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-4" role="alert">
            <span className="text-[15px] font-medium">Failed to load profiles</span>
            <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{error}</span>
            <SecondaryButton onClick={reload}>Try again</SecondaryButton>
          </div>
        ) : isLoading ? (
          <div className="flex items-center gap-2.5 py-10 text-[13px]" style={{ color: 'var(--ae-mute)' }} data-testid="profiles-loading">
            <Spinner size={20} /> Loading profiles…
          </div>
        ) : users.length === 0 ? (
          <div className="ae-card flex flex-col items-start gap-2 rounded-[20px] px-5 py-5">
            <span className="text-[15px] font-medium">No profiles found</span>
            <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
              {search
                ? `No results for "${search}"`
                : 'Profiles appear here once your first source sends events — connect an SDK or a connector to get started.'}
            </span>
            {!search && (
              <Link to="/activation" className="ae-btn-primary ae-focus mt-1 px-5 py-[9px]">Connect your first source</Link>
            )}
          </div>
        ) : (
          <>
            <div className="flex flex-wrap justify-between gap-2 text-[13px]" style={{ color: 'var(--ae-mute)' }}>
              <span>
                <span className="font-medium" style={{ color: 'var(--ae-ink)' }}>{users.length}</span> profile{users.length === 1 ? '' : 's'}
                {search ? ` matching "${search}"` : users.length >= LIST_LIMIT ? ` · showing the first ${LIST_LIMIT}, search to find others` : ''}
              </span>
              {selected && mode === 'list' && <LinkButton onClick={() => setParam('profile', null)} tone="mute">Collapse</LinkButton>}
            </div>

            {mode === 'list' && (
              <div className="flex flex-col gap-3" data-testid="profiles-list">
                {selectedMissing && (
                  <div className="ae-glass-card flex flex-col gap-1.5 rounded-[20px] px-5 py-4" style={{ borderColor: 'var(--ae-blue)' }} data-profile-row={selected}>
                    <span className="ae-mono truncate text-[15px]">{selected}</span>
                    <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Linked profile · not in the current list</span>
                    <ExpandedProfile row={null} profileId={selected} />
                  </div>
                )}
                {sorted.map(u => (
                  <ProfileCard
                    key={u.id}
                    row={u}
                    expanded={selected === u.id}
                    onToggle={() => setParam('profile', selected === u.id ? null : u.id)}
                  />
                ))}
              </div>
            )}
            {mode === 'map' && mapTarget && (
              <MapView users={sorted} selected={mapTarget} onSelect={id => setParam('profile', id)} />
            )}
            {mode === 'activity' && (
              <ActivityView
                users={users}
                onOpen={id => {
                  const params = new URLSearchParams(searchParams);
                  params.delete('view');
                  params.set('profile', id);
                  setSearchParams(params);
                }}
              />
            )}
          </>
        )}
      </div>
    </GlassPage>
  );
}
