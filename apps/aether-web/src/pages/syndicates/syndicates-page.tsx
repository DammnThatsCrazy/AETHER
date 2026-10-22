import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { GlassPage } from '@aether-app/components/app-shell';
import { Eyebrow, InlineNotice, MetricTile, TonePill } from '@aether-app/components/ae-ui';
import {
  EmptySlot,
  GlassSearch,
  GlassSection,
  LoadingRow,
  OutlineChip,
  SegmentedTabs,
  ShareRow,
  type SegmentOption,
} from '@aether-app/components/ae-campaigns-geo-ui';
import {
  MEMBER_READ_LIMIT,
  useDiscoveredClusters,
  useOverlap,
  usePopulationGroup,
  usePopulationGroups,
  usePopulationMembers,
  useTenantScope,
  type DiscoveredCluster,
  type SyndicateGroup,
  type SyndicateMember,
} from '@aether-app/features/syndicates/use-syndicates';
import { entityHref } from '@aether-app/features/relationships/use-relationships';

// ── Formatting ──────────────────────────────────────────────────────────────

function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 10_000) return `${(value / 1_000).toFixed(1)}k`;
  return value.toLocaleString('en-US');
}

function relative(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const days = Math.floor((Date.now() - t) / 86_400_000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

function shortDate(ms: number): string {
  return new Date(ms).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function plural(n: number, word: string): string {
  return `${count(n)} ${word}${n === 1 ? '' : 's'}`;
}

const RECENT_DAYS = 14;
const DAY = 86_400_000;

function changedRecently(iso: string | null): boolean {
  if (!iso) return false;
  const t = Date.parse(iso);
  return !Number.isNaN(t) && Date.now() - t <= RECENT_DAYS * DAY;
}

const PALETTE = ['var(--ae-blue)', 'var(--ae-teal)', 'var(--ae-sage)', 'var(--ae-amber)', 'var(--ae-violet)', 'var(--ae-mute)'];

// ── List ────────────────────────────────────────────────────────────────────

type Filter = 'all' | 'defined' | 'discovered' | 'recent';
type Mode = 'list' | 'overlap';

function isFilter(v: string | null): v is Filter {
  return v === 'all' || v === 'defined' || v === 'discovered' || v === 'recent';
}

function GroupRow({ group }: { readonly group: SyndicateGroup }) {
  const updated = relative(group.updatedAt ?? group.createdAt);
  return (
    <Link
      to={`/syndicates/${encodeURIComponent(group.id)}`}
      className="ae-glass-card ae-focus flex flex-wrap items-center gap-4 rounded-[24px] px-5 py-4 transition-colors hover:border-[color:var(--ae-blue)]"
      style={{ color: 'var(--ae-ink)', textDecoration: 'none' }}
      data-testid="syndicate-row"
    >
      <span className="flex min-w-0 flex-[1_1_280px] flex-col gap-1.5">
        <span className="flex flex-wrap items-center gap-2">
          <span className="text-[18px] font-medium tracking-[-0.3px]">{group.name}</span>
          <TonePill tone="blue">Rules · {group.type}</TonePill>
        </span>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
          {group.memberCount === null ? 'Member count not reported' : plural(group.memberCount, 'member')}
          {group.definitionVersion ? ` · rules v${group.definitionVersion}` : ''}
          {updated ? ` · updated ${updated}` : ''}
        </span>
        {group.description && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{group.description}</span>}
        {group.rules.length > 0 && (
          <span className="flex flex-wrap gap-1.5">
            {group.rules.slice(0, 3).map(rule => (
              <span key={rule} className="rounded-full px-2.5 py-0.5 text-[11px]" style={{ background: 'var(--ae-edge-soft)' }}>{rule}</span>
            ))}
            {group.rules.length > 3 && <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>+{group.rules.length - 3} more</span>}
          </span>
        )}
      </span>
      <span className="text-[13px]" style={{ color: 'var(--ae-blue-ink)' }}>Open →</span>
    </Link>
  );
}

function ClusterRow({ cluster }: { readonly cluster: DiscoveredCluster }) {
  const formed = relative(cluster.updatedAt ?? cluster.createdAt);
  return (
    <Link
      to={`/clusters/${encodeURIComponent(cluster.id)}`}
      className="ae-glass-card ae-focus flex flex-wrap items-center gap-4 rounded-[24px] px-5 py-4 transition-colors hover:border-[color:var(--ae-blue)]"
      style={{ color: 'var(--ae-ink)', textDecoration: 'none' }}
      data-testid="cluster-row"
    >
      <span className="flex min-w-0 flex-[1_1_280px] flex-col gap-1.5">
        <span className="flex flex-wrap items-center gap-2">
          <span className="text-[18px] font-medium tracking-[-0.3px]">{cluster.label}</span>
          <TonePill tone="sage">Discovered · {cluster.type}</TonePill>
        </span>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
          {cluster.memberCount === null ? 'Members listed in Cluster 360' : plural(cluster.memberCount, 'member')}
          {cluster.lifecycleState ? ` · ${cluster.lifecycleState}` : ''}
          {cluster.confidence !== null ? ` · ${Math.round(cluster.confidence * 100)}% confidence` : ''}
          {formed ? ` · ${formed}` : ''}
        </span>
        {cluster.formationReason && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{cluster.formationReason}</span>}
      </span>
      <span className="text-[13px]" style={{ color: 'var(--ae-blue-ink)' }}>Open in Cluster 360 →</span>
    </Link>
  );
}

function Venn({ a, b, onlyA, both, onlyB }: { readonly a: string; readonly b: string; readonly onlyA: number; readonly both: number; readonly onlyB: number }) {
  return (
    <svg viewBox="0 0 360 210" className="w-full" style={{ maxHeight: 320 }} role="img" aria-label={`${count(both)} members belong to both ${a} and ${b}`}>
      <circle cx="140" cy="105" r="88" fill="var(--ae-blue-tint)" stroke="var(--ae-blue)" strokeWidth="1.5" />
      <circle cx="220" cy="105" r="88" fill="var(--ae-sage-tint)" stroke="var(--ae-sage)" strokeWidth="1.5" fillOpacity={0.7} />
      <text x="100" y="110" textAnchor="middle" className="ae-mono" fontSize="18" fill="var(--ae-ink)">{count(onlyA)}</text>
      <text x="180" y="110" textAnchor="middle" className="ae-mono" fontSize="20" fontWeight="600" fill="var(--ae-ink)">{count(both)}</text>
      <text x="260" y="110" textAnchor="middle" className="ae-mono" fontSize="18" fill="var(--ae-ink)">{count(onlyB)}</text>
      <text x="100" y="132" textAnchor="middle" fontSize="10" fill="var(--ae-mute)">only</text>
      <text x="180" y="132" textAnchor="middle" fontSize="10" fill="var(--ae-mute)">both</text>
      <text x="260" y="132" textAnchor="middle" fontSize="10" fill="var(--ae-mute)">only</text>
    </svg>
  );
}

function OverlapView({ tenantId, groups }: { readonly tenantId: string; readonly groups: readonly SyndicateGroup[] }) {
  const [params, setParams] = useSearchParams();
  const picked = [params.get('a'), params.get('b')].filter((v): v is string => !!v);
  const a = groups.find(g => g.id === picked[0]) ?? null;
  const b = groups.find(g => g.id === picked[1]) ?? null;
  const overlap = useOverlap(tenantId, a, b);

  function toggle(id: string) {
    const current = picked.filter(p => groups.some(g => g.id === p));
    const next = current.includes(id) ? current.filter(p => p !== id) : [...current.slice(-1), id];
    setParams(prev => {
      const p = new URLSearchParams(prev);
      p.delete('a');
      p.delete('b');
      if (next[0]) p.set('a', next[0]);
      if (next[1]) p.set('b', next[1]);
      return p;
    }, { replace: true });
  }

  if (groups.length < 2) {
    return <EmptySlot testId="overlap-empty">Overlap needs at least two rule-defined syndicates. Discovered clusters are compared in Cluster 360.</EmptySlot>;
  }

  return (
    <GlassSection testId="overlap">
      <Eyebrow>Overlap · select two</Eyebrow>
      <span className="flex flex-wrap gap-1.5">
        {groups.map(g => (
          <OutlineChip key={g.id} selected={picked.includes(g.id)} onClick={() => toggle(g.id)}>
            {g.name}{g.memberCount !== null ? ` · ${count(g.memberCount)}` : ''}
          </OutlineChip>
        ))}
      </span>
      {(!a || !b) && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Select two syndicates to see how many members they share.</span>}
      {a && b && overlap.error && <InlineNotice>Members could not be read right now, so the overlap is unavailable.</InlineNotice>}
      {a && b && !overlap.error && !overlap.data && <LoadingRow label="Comparing members…" />}
      {a && b && overlap.data && (
        <>
          <Venn a={a.name} b={b.name} onlyA={overlap.data.onlyA} both={overlap.data.both} onlyB={overlap.data.onlyB} />
          <span className="flex flex-wrap justify-between gap-2 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
            <span><span style={{ color: 'var(--ae-blue-ink)' }}>●</span> {a.name}</span>
            <span><span style={{ color: 'var(--ae-sage)' }}>●</span> {b.name}</span>
          </span>
          <span className="text-[13px]" data-testid="overlap-note">
            {count(overlap.data.both)} active member{overlap.data.both === 1 ? '' : 's'} belong to both {a.name} and {b.name}.
            {!overlap.data.exact && ` Compared over the first ${count(MEMBER_READ_LIMIT)} members of each, so the shared count is a lower bound.`}
          </span>
        </>
      )}
    </GlassSection>
  );
}

function SyndicateList() {
  const [params, setParams] = useSearchParams();
  const filterParam = params.get('view');
  const filter: Filter = isFilter(filterParam) ? filterParam : 'all';
  const mode: Mode = params.get('mode') === 'overlap' ? 'overlap' : 'list';
  const [query, setQuery] = useState('');
  const tenant = useTenantScope();
  const groups = usePopulationGroups(tenant.tenantId);
  const clusters = useDiscoveredClusters(tenant.tenantId);

  function setParam(key: string, value: string | null) {
    setParams(prev => {
      const p = new URLSearchParams(prev);
      if (value === null) p.delete(key);
      else p.set(key, value);
      return p;
    }, { replace: true });
  }

  const q = query.trim().toLowerCase();
  const groupRows = useMemo(() => (groups.data ?? []).filter(g => {
    if (filter === 'discovered') return false;
    if (filter === 'recent' && !changedRecently(g.updatedAt ?? g.createdAt)) return false;
    return !q || g.name.toLowerCase().includes(q) || g.rules.some(r => r.toLowerCase().includes(q));
  }), [groups.data, filter, q]);
  const clusterRows = useMemo(() => (clusters.data ?? []).filter(c => {
    if (filter === 'defined') return false;
    if (filter === 'recent' && !changedRecently(c.updatedAt ?? c.createdAt)) return false;
    return !q || c.label.toLowerCase().includes(q) || c.type.toLowerCase().includes(q);
  }), [clusters.data, filter, q]);

  const filters: SegmentOption<Filter>[] = [
    { value: 'all', label: 'All' },
    { value: 'defined', label: 'Defined by rules' },
    { value: 'discovered', label: 'Discovered' },
    { value: 'recent', label: 'Changed recently' },
  ];
  const modes: SegmentOption<Mode>[] = [
    { value: 'list', label: 'Syndicates' },
    { value: 'overlap', label: 'Overlap' },
  ];

  const groupsPending = !groups.data && !groups.error;
  const clustersPending = !clusters.data && !clusters.error;
  const anyData = groups.data !== null || clusters.data !== null;
  const nothingAtAll = (groups.data?.length ?? 0) === 0 && (clusters.data?.length ?? 0) === 0;

  return (
    <div className="flex flex-col gap-4" data-testid="aether-syndicates">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <span className="flex flex-col gap-1">
          <h1 className="text-[clamp(26px,4.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Syndicates</h1>
          <span className="max-w-[560px] text-[14px] leading-[1.45]" style={{ color: 'var(--ae-mute)' }}>
            Groups of people and agents that behave alike. Some are defined by rules; others the graph discovers on its own.
          </span>
        </span>
        {mode === 'list' && (
          <span className="flex w-full flex-wrap gap-2 sm:w-auto">
            <GlassSearch value={query} onChange={setQuery} placeholder="Search syndicates" label="Search syndicates" />
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        {mode === 'list' ? (
          <SegmentedTabs label="Syndicate filters" options={filters} value={filter} onChange={v => setParam('view', v === 'all' ? null : v)} />
        ) : <span />}
        <SegmentedTabs label="Syndicate views" options={modes} value={mode} onChange={v => setParam('mode', v === 'list' ? null : v)} />
      </div>

      {tenant.error && <InlineNotice>Syndicates are unavailable: your workspace could not be resolved ({tenant.error}).</InlineNotice>}
      {groups.error && <InlineNotice>Rule-defined syndicates are unavailable right now.</InlineNotice>}
      {clusters.error && mode === 'list' && filter !== 'defined' && <InlineNotice>Discovered clusters are unavailable right now.</InlineNotice>}

      <div className="ae-rise flex flex-col gap-3" key={mode} role="tabpanel">
        {mode === 'overlap' && (
          groupsPending ? <LoadingRow label="Loading syndicates…" /> : groups.data ? <OverlapView tenantId={tenant.tenantId} groups={groups.data} /> : null
        )}
        {mode === 'list' && !tenant.error && (
          <>
            {(groupsPending || clustersPending) && <LoadingRow label="Loading syndicates…" />}
            {groupRows.map(g => <GroupRow key={`g:${g.id}`} group={g} />)}
            {clusterRows.map(c => <ClusterRow key={`c:${c.id}`} cluster={c} />)}
            {!groupsPending && !clustersPending && anyData && groupRows.length === 0 && clusterRows.length === 0 && (
              <EmptySlot testId="syndicates-empty">
                {nothingAtAll
                  ? 'No syndicates yet. Rule-defined groups appear here once they are created through the population API, and discovered clusters appear as the graph forms them.'
                  : 'No syndicates match.'}
              </EmptySlot>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Open syndicate ──────────────────────────────────────────────────────────

const RANGES = [7, 30, 90] as const;
type Range = typeof RANGES[number];

function MembersOverTime({ members, range }: { readonly members: readonly SyndicateMember[]; readonly range: Range }) {
  const [hover, setHover] = useState<number | null>(null);
  const series = useMemo(() => {
    const joins = members.map(m => (m.joinedAt ? Date.parse(m.joinedAt) : NaN)).filter(t => !Number.isNaN(t)).sort((x, y) => x - y);
    if (joins.length === 0) return null;
    const end = Date.now();
    const days = range;
    const points: Array<{ t: number; v: number }> = [];
    let i = 0;
    for (let d = days; d >= 0; d -= 1) {
      const t = end - d * DAY;
      while (i < joins.length && joins[i]! <= t) i += 1;
      points.push({ t, v: i });
    }
    return points;
  }, [members, range]);

  if (!series) return <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Join dates are not reported for these members.</span>;
  const max = Math.max(...series.map(p => p.v));
  const min = Math.min(...series.map(p => p.v));
  const y = (v: number) => 94 - ((v - min) / ((max - min) || 1)) * 80;
  const line = series.map((p, k) => `${k ? 'L' : 'M'}${((k / (series.length - 1)) * 100).toFixed(2)} ${y(p.v).toFixed(2)}`).join(' ');
  const h = hover !== null ? series[hover] : null;
  return (
    <>
      <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-blue-ink)' }} data-testid="members-readout">
        {h ? `${shortDate(h.t)} · ${count(h.v)} members` : `${count(series[series.length - 1]!.v)} members now`}
      </span>
      <div
        className="relative cursor-crosshair"
        style={{ height: 'clamp(130px, 20vw, 170px)' }}
        onMouseMove={e => {
          const r = e.currentTarget.getBoundingClientRect();
          setHover(Math.max(0, Math.min(series.length - 1, Math.round(((e.clientX - r.left) / r.width) * (series.length - 1)))));
        }}
        onMouseLeave={() => setHover(null)}
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">
          <defs>
            <linearGradient id="syndicate-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--ae-blue)" stopOpacity=".26" />
              <stop offset="1" stopColor="var(--ae-blue)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`${line} L100 100 L0 100 Z`} fill="url(#syndicate-fill)" />
          <path d={line} fill="none" stroke="var(--ae-blue)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        </svg>
        {hover !== null && h && (
          <>
            <span className="pointer-events-none absolute bottom-0 top-0" style={{ left: `${(hover / (series.length - 1)) * 100}%`, borderLeft: '1px solid var(--ae-faint)' }} />
            <span
              className="pointer-events-none absolute rounded-full"
              style={{ left: `${(hover / (series.length - 1)) * 100}%`, top: `${y(h.v)}%`, width: 10, height: 10, margin: '-5px 0 0 -5px', background: 'var(--ae-blue)', border: '2px solid var(--ae-card)' }}
            />
          </>
        )}
      </div>
      <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>Active members by the date they joined. Members who have left are not part of this read.</span>
    </>
  );
}

type Dim = 'type' | 'basis' | 'source';
const DIM_LABEL: Record<Dim, string> = { type: 'Entity type', basis: 'How they joined', source: 'Source' };

function dimValue(m: SyndicateMember, dim: Dim): string | null {
  if (dim === 'type') return m.entityType;
  if (dim === 'basis') return m.basis ? m.basis.replace(/_/g, ' ') : null;
  return m.sourceTag;
}

function Composition({ members }: { readonly members: readonly SyndicateMember[] }) {
  const dims = (['type', 'basis', 'source'] as const).filter(d => members.some(m => dimValue(m, d)));
  const [dim, setDim] = useState<Dim>('type');
  const active = dims.includes(dim) ? dim : dims[0];
  const rows = useMemo(() => {
    if (!active) return [];
    const counts = new Map<string, number>();
    for (const m of members) {
      const v = dimValue(m, active) ?? 'Not reported';
      counts.set(v, (counts.get(v) ?? 0) + 1);
    }
    return [...counts.entries()].sort((x, y) => y[1] - x[1]).slice(0, 6);
  }, [members, active]);
  if (!active) return <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No member attributes are reported yet.</span>;
  return (
    <>
      <span className="flex flex-wrap gap-1.5">
        {dims.map(d => <OutlineChip key={d} selected={d === active} onClick={() => setDim(d)}>{DIM_LABEL[d]}</OutlineChip>)}
      </span>
      {rows.map(([label, n], i) => (
        <ShareRow key={label} label={label} value={count(n)} share={(n / members.length) * 100} color={PALETTE[i % PALETTE.length]!} />
      ))}
    </>
  );
}

function SyndicateDetail({ id }: { readonly id: string }) {
  const navigate = useNavigate();
  const tenant = useTenantScope();
  const group = usePopulationGroup(tenant.tenantId, id);
  const members = usePopulationMembers(tenant.tenantId, id);
  const [range, setRange] = useState<Range>(30);

  const list = members.data ?? [];
  const joinedInRange = list.filter(m => m.joinedAt && Date.now() - Date.parse(m.joinedAt) <= range * DAY).length;
  const withConfidence = list.filter(m => m.confidence !== null);
  const avgConfidence = withConfidence.length ? withConfidence.reduce((s, m) => s + m.confidence!, 0) / withConfidence.length : null;
  const top = [...list].sort((x, y) => (y.confidence ?? -1) - (x.confidence ?? -1)).slice(0, 6);
  const g = group.data?.group ?? null;
  const partial = g !== null && g.memberCount !== null && list.length < g.memberCount;

  const back = (
    <button type="button" onClick={() => navigate('/syndicates')} className="ae-focus self-start text-[13px] hover:underline" style={{ color: 'var(--ae-mute)' }}>
      ← Syndicates{g ? <> / <span style={{ color: 'var(--ae-ink)' }}>{g.name}</span></> : null}
    </button>
  );

  if (tenant.error || group.error) {
    return (
      <div className="flex flex-col gap-4" data-testid="syndicate-detail">
        {back}
        <InlineNotice>This syndicate is unavailable right now{group.error ? '' : `: ${tenant.error}`}.</InlineNotice>
      </div>
    );
  }
  if (!group.data) {
    return (
      <div className="flex flex-col gap-4" data-testid="syndicate-detail">
        {back}
        <LoadingRow label="Loading syndicate…" />
      </div>
    );
  }
  if (!g) {
    return (
      <div className="flex flex-col gap-4" data-testid="syndicate-detail">
        {back}
        <EmptySlot>This syndicate was not found in your workspace.</EmptySlot>
      </div>
    );
  }
  const s = g;

  return (
    <div className="flex flex-col gap-3.5" data-testid="syndicate-detail">
      {back}
      <GlassSection className="!flex-row flex-wrap items-center justify-between gap-3.5">
        <span className="flex min-w-0 flex-col gap-1.5">
          <h1 className="text-[clamp(22px,4.6vw,28px)] font-medium leading-[1.1] tracking-[-0.56px]">{s.name}</h1>
          <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
            {s.type}{s.status ? ` · ${s.status}` : ''}{s.definitionVersion ? ` · rules v${s.definitionVersion}` : ''}
          </span>
          {s.rules.length > 0 ? (
            <span className="flex flex-wrap gap-1.5" data-testid="syndicate-rules">
              {s.rules.map(rule => <TonePill key={rule} tone="blue" className="!text-[11px] !px-2.5 !py-0.5">{rule}</TonePill>)}
            </span>
          ) : (
            <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>No rules are recorded on this definition.</span>
          )}
          {s.description && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{s.description}</span>}
        </span>
        <Link
          to={`/syndicates?mode=overlap&a=${encodeURIComponent(s.id)}`}
          className="ae-focus rounded-full border px-3.5 py-1.5 text-[12px]"
          style={{ borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)', textDecoration: 'none' }}
        >
          Compare overlap →
        </Link>
      </GlassSection>

      <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(170px, 100%), 1fr))' }}>
        <MetricTile label="Members" value={count(s.memberCount)} sub="active now" />
        <MetricTile label="Joined" value={members.data ? `+${count(joinedInRange)}` : '—'} sub={`last ${range} days`} tone="sage" />
        <MetricTile label="Average confidence" value={avgConfidence === null ? '—' : `${Math.round(avgConfidence * 100)}%`} sub={avgConfidence === null ? 'not reported' : 'membership confidence'} tone="blue" />
        <MetricTile label="Created" value={relative(s.createdAt) ?? '—'} sub={s.updatedAt ? `updated ${relative(s.updatedAt) ?? '—'}` : 'no update recorded'} />
      </div>

      {members.error && <InlineNotice>Members could not be read right now, so membership charts are unavailable.</InlineNotice>}
      {!members.error && !members.data && <LoadingRow label="Loading members…" />}

      {members.data && (
        <>
          <GlassSection testId="members-over-time">
            <span className="flex flex-wrap items-center justify-between gap-2">
              <Eyebrow>Members over time</Eyebrow>
              <SegmentedTabs
                label="Range"
                options={RANGES.map(r => ({ value: String(r) as `${Range}`, label: `${r}d` }))}
                value={String(range) as `${Range}`}
                onChange={v => setRange(Number(v) as Range)}
              />
            </span>
            {list.length === 0 ? <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No active members yet.</span> : <MembersOverTime members={list} range={range} />}
          </GlassSection>

          <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(300px, 100%), 1fr))' }}>
            <GlassSection testId="composition">
              <Eyebrow>Who is in it · by</Eyebrow>
              {list.length === 0 ? <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No active members yet.</span> : <Composition members={list} />}
              {partial && <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>Based on the first {count(list.length)} of {count(s.memberCount)} members.</span>}
            </GlassSection>

            <GlassSection testId="movement">
              <Eyebrow>Movement · last {range} days</Eyebrow>
              <div className="flex gap-2.5">
                <span className="flex flex-1 flex-col rounded-[14px] px-3 py-2.5" style={{ background: 'var(--ae-sage-tint)' }}>
                  <span className="ae-mono text-[18px] font-medium" style={{ color: 'var(--ae-sage)' }}>+{count(joinedInRange)}</span>
                  <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>Joined</span>
                </span>
                <span className="flex flex-1 flex-col rounded-[14px] px-3 py-2.5" style={{ background: 'var(--ae-edge-soft)' }}>
                  <span className="ae-mono text-[18px] font-medium" style={{ color: 'var(--ae-mute)' }}>—</span>
                  <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>Left · not reported</span>
                </span>
              </div>
              <Eyebrow className="pt-2">Top members · by confidence</Eyebrow>
              {top.length === 0 && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No active members yet.</span>}
              {top.map(m => {
                const href = entityHref(m.entityType, m.entityId);
                return (
                  <Link
                    key={m.entityId}
                    to={href.to}
                    className="ae-focus flex items-center gap-2.5 py-2 text-[13px]"
                    style={{ borderTop: '1px solid var(--ae-edge-soft)', color: 'var(--ae-ink)', textDecoration: 'none' }}
                    data-testid="top-member"
                  >
                    <span className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full text-[10px] font-medium uppercase" style={{ background: 'var(--ae-edge-soft)', border: '1px solid var(--ae-edge)' }}>
                      {m.entityType.slice(0, 2)}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{m.entityId}</span>
                    <span className="ae-mono" style={{ color: 'var(--ae-mute)' }}>{m.confidence === null ? '—' : `${Math.round(m.confidence * 100)}%`}</span>
                  </Link>
                );
              })}
            </GlassSection>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Syndicates (Claude Design handoff: Aether Syndicates). Rule-defined
 * population groups open here; discovered graph clusters open in Cluster 360.
 * Every figure is a read from the population and graph endpoints.
 */
export function SyndicatesPage() {
  const { syndicateId } = useParams<{ syndicateId: string }>();
  return (
    <GlassPage>
      {syndicateId ? <SyndicateDetail id={syndicateId} key={syndicateId} /> : <SyndicateList />}
    </GlassPage>
  );
}
