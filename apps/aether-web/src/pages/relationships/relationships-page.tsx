import { useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { GlassPage } from '@aether-app/components/app-shell';
import { Bar, Eyebrow, InlineNotice, MetricTile, PrimaryButton, TonePill, type Tone } from '@aether-app/components/ae-ui';
import {
  EmptySlot,
  GlassSearch,
  GlassSection,
  LoadingRow,
  OutlineChip,
  SegmentedTabs,
  type SegmentOption,
} from '@aether-app/components/ae-campaigns-geo-ui';
import { useTenantScope } from '@aether-app/features/syndicates/use-syndicates';
import { useUsers } from '@aether-app/features/users/use-users';
import {
  entityHref,
  hopDistances,
  useEgoNetwork,
  usePath,
  type EvidenceItem,
  type RelEdge,
  type RelNode,
} from '@aether-app/features/relationships/use-relationships';
import { ArcDiagram, FormationStrip, RadialNetwork, layerColor, verb } from './relationships-visuals';

// ── Helpers ─────────────────────────────────────────────────────────────────

type ClassFilter = 'all' | 'h2h' | 'h2a' | 'a2a' | 'other';
type View = 'network' | 'list' | 'types' | 'history' | 'paths';

const VIEWS: readonly View[] = ['network', 'list', 'types', 'history', 'paths'];
function isView(v: string | null): v is View {
  return v !== null && (VIEWS as readonly string[]).includes(v);
}

function edgeClass(e: RelEdge): Exclude<ClassFilter, 'all'> {
  if (e.layer === 'H2H') return 'h2h';
  if (e.layer === 'H2A' || e.layer === 'A2H') return 'h2a';
  if (e.layer === 'A2A') return 'a2a';
  return 'other';
}

const LAYER_LABEL: Record<Exclude<ClassFilter, 'all'>, string> = {
  h2h: 'Human ↔ Human',
  h2a: 'Human ↔ Agent',
  a2a: 'Agent ↔ Agent',
  other: 'Other',
};

const LAYER_TONE: Record<Exclude<ClassFilter, 'all'>, Tone> = { h2h: 'blue', h2a: 'sage', a2a: 'solar', other: 'mute' };

function date(iso: string | null): string | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function pct(v: number | null): string {
  return v === null ? '—' : `${Math.round(v * 100)}`;
}

function nodeLabel(nodes: readonly RelNode[], id: string): string {
  return nodes.find(n => n.id === id)?.label ?? id;
}

function nodeKind(nodes: readonly RelNode[], id: string): string {
  return nodes.find(n => n.id === id)?.kind ?? 'entity';
}

const HIDDEN_PROPS = new Set(['tenant_id', 'tenantId', 'evidence', 'evidence_refs', 'evidenceRefs', 'relationship_score', 'confidence', 'valid_from', 'valid_to', 'created_at']);

// ── Anchor picker ───────────────────────────────────────────────────────────

function AnchorPicker() {
  const navigate = useNavigate();
  const { users, search, setSearch, isLoading, error } = useUsers();
  const [manual, setManual] = useState('');

  function openManual(e: FormEvent) {
    e.preventDefault();
    const id = manual.trim();
    if (id) navigate(`/relationships/${encodeURIComponent(id)}`);
  }

  return (
    <div className="flex flex-col gap-4" data-testid="relationships-picker">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <span className="flex flex-col gap-1">
          <h1 className="text-[clamp(26px,4.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Relationships</h1>
          <span className="max-w-[560px] text-[14px] leading-[1.45]" style={{ color: 'var(--ae-mute)' }}>
            What connects people, agents and organizations, and how it has changed. Pick who to centre on.
          </span>
        </span>
        <span className="flex w-full flex-wrap gap-2 sm:w-auto">
          <GlassSearch value={search} onChange={setSearch} placeholder="Search profiles" label="Search profiles" />
        </span>
      </div>

      <GlassSection>
        <Eyebrow>Centre on a profile</Eyebrow>
        {error && <InlineNotice>Profiles are unavailable right now. You can still open an entity by its id below.</InlineNotice>}
        {!error && isLoading && users.length === 0 && <LoadingRow label="Loading profiles…" />}
        {!error && !isLoading && users.length === 0 && (
          <EmptySlot testId="picker-empty">{search.trim() ? 'No profiles match.' : 'No profiles yet. Relationships appear once events resolve into profiles.'}</EmptySlot>
        )}
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(220px, 100%), 1fr))' }}>
          {users.slice(0, 24).map(u => (
            <Link
              key={u.id}
              to={`/relationships/${encodeURIComponent(u.id)}?kind=user`}
              className="ae-focus flex min-w-0 flex-col rounded-[14px] px-3.5 py-2.5 text-[13px]"
              style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)', color: 'var(--ae-ink)', textDecoration: 'none' }}
              data-testid="anchor-option"
            >
              <span className="truncate font-medium">{u.displayName}</span>
              <span className="truncate text-[11px]" style={{ color: 'var(--ae-mute)' }}>{u.email ?? u.id}</span>
            </Link>
          ))}
        </div>
      </GlassSection>

      <GlassSection>
        <Eyebrow>Or open any entity by id</Eyebrow>
        <form onSubmit={openManual} className="flex flex-wrap gap-2">
          <input
            value={manual}
            onChange={e => setManual(e.target.value)}
            aria-label="Entity id"
            placeholder="Agent, wallet, organization or profile id"
            className="ae-focus min-w-0 flex-1 rounded-full border px-4 py-[9px] text-[13px] outline-none"
            style={{ background: 'var(--ae-glass-card)', borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)' }}
          />
          <PrimaryButton type="submit" disabled={!manual.trim()}>Open</PrimaryButton>
        </form>
      </GlassSection>
    </div>
  );
}

// ── Side panel ──────────────────────────────────────────────────────────────

function SelectedPanel({
  nodes,
  edges,
  edge,
  focus,
  anchorId,
  onOpen,
}: {
  readonly nodes: readonly RelNode[];
  readonly edges: readonly RelEdge[];
  readonly edge: RelEdge | null;
  readonly focus: RelNode | null;
  readonly anchorId: string;
  readonly onOpen: (edge: RelEdge) => void;
}) {
  if (focus && !edge) {
    const href = entityHref(focus.kind, focus.id);
    const links = edges.filter(e => e.from === focus.id || e.to === focus.id).length;
    return (
      <GlassSection testId="selected-panel">
        <Eyebrow>Selected entity</Eyebrow>
        <span className="text-[18px] font-medium leading-tight">{focus.label}</span>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>{focus.kind} · {links} link{links === 1 ? '' : 's'} in view</span>
        <span className="flex flex-wrap gap-3 pt-1 text-[13px]">
          <Link to={href.to} style={{ color: 'var(--ae-blue-ink)' }}>{href.label} →</Link>
          {focus.id !== anchorId && (
            <Link to={`/relationships/${encodeURIComponent(focus.id)}?kind=${encodeURIComponent(focus.kind)}`} style={{ color: 'var(--ae-blue-ink)' }}>Centre here →</Link>
          )}
        </span>
      </GlassSection>
    );
  }
  if (!edge) {
    return (
      <GlassSection testId="selected-panel">
        <Eyebrow>Selected relationship</Eyebrow>
        <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Select a link or an entity to inspect it.</span>
      </GlassSection>
    );
  }
  const cls = edgeClass(edge);
  return (
    <GlassSection testId="selected-panel">
      <Eyebrow>Selected relationship</Eyebrow>
      <span className="text-[17px] leading-snug">
        <span className="font-medium">{nodeLabel(nodes, edge.from)}</span>{' '}
        <span style={{ color: 'var(--ae-mute)' }}>{verb(edge.type)}</span>{' '}
        <span className="font-medium">{nodeLabel(nodes, edge.to)}</span>
      </span>
      <span className="flex flex-wrap gap-1.5"><TonePill tone={LAYER_TONE[cls]}>{LAYER_LABEL[cls]}</TonePill></span>
      {date(edge.validFrom) && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Since {date(edge.validFrom)}{edge.validTo ? ` · ended ${date(edge.validTo)}` : ''}</span>}
      <span className="flex items-center gap-2 text-[12px]">
        <span style={{ color: 'var(--ae-mute)' }}>Strength</span>
        {edge.score === null ? (
          <span style={{ color: 'var(--ae-mute)' }}>not scored</span>
        ) : (
          <>
            <span className="flex-1"><Bar value={edge.score * 100} color={layerColor(edge.layer)} /></span>
            <span className="ae-mono">{pct(edge.score)}</span>
          </>
        )}
      </span>
      <button type="button" onClick={() => onOpen(edge)} className="ae-focus self-start text-[13px] hover:underline" style={{ color: 'var(--ae-blue-ink)' }} data-testid="open-relationship">
        Open relationship →
      </button>
    </GlassSection>
  );
}

// ── Open relationship ───────────────────────────────────────────────────────

function evidenceTone(item: EvidenceItem): Tone {
  const b = (item.basis ?? '').toLowerCase();
  if (/verif|determin|exact|observed|source/.test(b)) return 'sage';
  if (/infer|probab|model|fuzzy/.test(b)) return 'amber';
  return 'mute';
}

function RelationshipDetail({ edge, nodes, anchorId, onBack }: { readonly edge: RelEdge; readonly nodes: readonly RelNode[]; readonly anchorId: string; readonly onBack: () => void }) {
  const a = { id: edge.from, kind: nodeKind(nodes, edge.from), label: nodeLabel(nodes, edge.from) };
  const b = { id: edge.to, kind: nodeKind(nodes, edge.to), label: nodeLabel(nodes, edge.to) };
  const cls = edgeClass(edge);
  const ladder = [...edge.evidence].sort((x, y) => {
    const rank = (t: Tone) => (t === 'sage' ? 0 : t === 'mute' ? 1 : 2);
    return rank(evidenceTone(x)) - rank(evidenceTone(y));
  });
  const facts = Object.entries(edge.properties).filter(([k, v]) => !HIDDEN_PROPS.has(k) && v !== null && v !== undefined && typeof v !== 'object');
  const ha = entityHref(a.kind, a.id);
  const hb = entityHref(b.kind, b.id);
  const other = a.id === anchorId ? b : a;

  return (
    <div className="flex flex-col gap-3.5" data-testid="relationship-detail">
      <button type="button" onClick={onBack} className="ae-focus self-start text-[13px] hover:underline" style={{ color: 'var(--ae-mute)' }}>
        ← Relationships / <span style={{ color: 'var(--ae-ink)' }}>{a.label} {verb(edge.type)} {b.label}</span>
      </button>
      <GlassSection className="!flex-row flex-wrap items-center justify-between gap-3.5">
        <span className="flex min-w-0 flex-col gap-1.5">
          <h1 className="text-[clamp(20px,4.2vw,26px)] font-medium leading-[1.15] tracking-[-0.5px]">
            {a.label} <span style={{ color: 'var(--ae-mute)' }}>{verb(edge.type)}</span> {b.label}
          </h1>
          <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
            {LAYER_LABEL[cls]}{date(edge.validFrom) ? ` · since ${date(edge.validFrom)}` : ''}
          </span>
        </span>
        <span className="flex flex-wrap gap-2">
          {[
            { to: ha.to, label: `Open ${a.label}` },
            { to: hb.to, label: `Open ${b.label}` },
            ...(other.id !== anchorId ? [{ to: `/relationships/${encodeURIComponent(other.id)}?kind=${encodeURIComponent(other.kind)}`, label: `Centre on ${other.label}` }] : []),
          ].map(l => (
            <Link
              key={l.label}
              to={l.to}
              className="ae-focus max-w-full truncate rounded-full border px-3.5 py-1.5 text-[12px]"
              style={{ borderColor: 'var(--ae-edge)', background: 'var(--ae-glass-card)', color: 'var(--ae-ink)', textDecoration: 'none' }}
            >
              {l.label} →
            </Link>
          ))}
        </span>
      </GlassSection>

      <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(170px, 100%), 1fr))' }}>
        <MetricTile label="Strength" value={pct(edge.score)} sub={edge.score === null ? 'not scored by the graph' : 'relationship score'} {...(edge.score !== null ? { tone: edge.score >= 0.7 ? 'sage' as const : 'amber' as const } : {})} />
        <MetricTile label="Confidence" value={edge.confidence === null ? '—' : `${pct(edge.confidence)}%`} sub={edge.confidence === null ? 'not reported' : 'on this link'} />
        <MetricTile label="Since" value={date(edge.validFrom) ?? '—'} sub={date(edge.validFrom) ? 'first recorded' : 'not recorded'} />
        <MetricTile label="Status" value={edge.validTo ? 'Ended' : 'Active'} sub={edge.validTo ? date(edge.validTo) ?? '' : 'no end recorded'} tone={edge.validTo ? 'amber' : 'blue'} />
      </div>

      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(280px, 100%), 1fr))' }}>
        <GlassSection testId="evidence-ladder">
          <Eyebrow>Evidence · why Aether believes this</Eyebrow>
          {ladder.length === 0 && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No evidence is recorded on this link.</span>}
          {ladder.map((item, i) => (
            <div key={`${item.text}-${i}`} className="flex items-center justify-between gap-3 py-1.5 text-[13px]" style={{ borderTop: i ? '1px solid var(--ae-edge-soft)' : undefined }}>
              <span className="min-w-0 break-words">{item.text}</span>
              {item.basis && <TonePill tone={evidenceTone(item)}>{item.basis}</TonePill>}
            </div>
          ))}
        </GlassSection>
        <GlassSection testId="recorded-facts">
          <Eyebrow>What the graph recorded</Eyebrow>
          {facts.length === 0 && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No further attributes on this link.</span>}
          {facts.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3 text-[13px]">
              <span style={{ color: 'var(--ae-mute)' }}>{k.replace(/_/g, ' ')}</span>
              <span className="ae-mono min-w-0 truncate">{String(v)}</span>
            </div>
          ))}
        </GlassSection>
        <GlassSection testId="relationship-history">
          <Eyebrow>History</Eyebrow>
          {!edge.validFrom && !edge.validTo && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No dates are recorded on this link.</span>}
          {edge.validFrom && <div className="flex gap-3 text-[13px]"><span className="ae-mono w-[96px] shrink-0" style={{ color: 'var(--ae-mute)' }}>{date(edge.validFrom)}</span><span>Relationship recorded</span></div>}
          {edge.validTo && <div className="flex gap-3 text-[13px]"><span className="ae-mono w-[96px] shrink-0" style={{ color: 'var(--ae-mute)' }}>{date(edge.validTo)}</span><span>Relationship ended</span></div>}
        </GlassSection>
      </div>
    </div>
  );
}

// ── Path explorer ───────────────────────────────────────────────────────────

function PathExplorer({ tenantId, anchor, nodes }: { readonly tenantId: string; readonly anchor: { readonly id: string; readonly kind: string }; readonly nodes: readonly RelNode[] }) {
  const [params, setParams] = useSearchParams();
  const targetId = params.get('to');
  const maxDepth = Math.min(6, Math.max(1, Number(params.get('depth') ?? 6) || 6));
  const [manual, setManual] = useState('');
  const candidates = nodes.filter(n => n.id !== anchor.id).slice(0, 24);
  const target = targetId ? { id: targetId, kind: nodeKind(nodes, targetId) } : null;
  const path = usePath(tenantId, anchor, target, maxDepth);

  function set(key: string, value: string | null) {
    setParams(prev => {
      const p = new URLSearchParams(prev);
      if (value === null) p.delete(key);
      else p.set(key, value);
      return p;
    }, { replace: true });
  }

  return (
    <GlassSection testId="path-explorer">
      <Eyebrow>Path explorer · up to {maxDepth} hops</Eyebrow>
      <span className="flex flex-wrap items-center gap-1.5 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
        Hops
        {[2, 3, 4, 5, 6].map(d => <OutlineChip key={d} selected={d === maxDepth} onClick={() => set('depth', String(d))}>{d}</OutlineChip>)}
      </span>
      <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Find the shortest path to</span>
      <span className="flex flex-wrap gap-1.5">
        {candidates.map(n => <OutlineChip key={n.id} selected={n.id === targetId} onClick={() => set('to', n.id)}>{n.label}</OutlineChip>)}
      </span>
      <form
        onSubmit={e => { e.preventDefault(); if (manual.trim()) set('to', manual.trim()); }}
        className="flex flex-wrap gap-2"
      >
        <input
          value={manual}
          onChange={e => setManual(e.target.value)}
          aria-label="Target entity id"
          placeholder="…or any entity id"
          className="ae-focus min-w-0 flex-1 rounded-full border px-4 py-[7px] text-[13px] outline-none"
          style={{ background: 'var(--ae-glass-card)', borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)' }}
        />
        <PrimaryButton type="submit" disabled={!manual.trim()}>Trace</PrimaryButton>
      </form>
      {!target && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>Pick an entity to trace how it connects.</span>}
      {target && target.id === anchor.id && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>That is the entity you are centred on.</span>}
      {target && target.id !== anchor.id && path.error && <InlineNotice>The path read is unavailable right now.</InlineNotice>}
      {target && target.id !== anchor.id && !path.error && !path.data && <LoadingRow label="Tracing…" />}
      {path.data && !path.data.found && target && <EmptySlot testId="path-none">No path within {maxDepth} hops.</EmptySlot>}
      {path.data?.found && (
        <ol className="flex flex-col gap-0" data-testid="path-steps">
          {path.data.steps.map(({ node, via }, i) => {
            const href = entityHref(node.kind, node.id);
            return (
              <li key={`${node.id}-${i}`} className="flex flex-col">
                {via && (
                  <span className="ml-3 border-l py-1 pl-4 text-[11px]" style={{ borderColor: layerColor(via.layer), color: 'var(--ae-mute)' }}>
                    {verb(via.type)}
                  </span>
                )}
                <Link to={href.to} className="ae-focus inline-flex items-center gap-2 self-start rounded-full border px-3 py-1 text-[13px]" style={{ borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)', textDecoration: 'none' }}>
                  <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>{i}</span>
                  {node.label}
                  <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{node.kind}</span>
                </Link>
              </li>
            );
          })}
        </ol>
      )}
    </GlassSection>
  );
}

// ── Anchored view ───────────────────────────────────────────────────────────

function AnchoredRelationships({ anchorId }: { readonly anchorId: string }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const kind = params.get('kind') ?? 'user';
  const viewParam = params.get('view');
  const view: View = isView(viewParam) ? viewParam : 'network';
  const hops = Math.min(3, Math.max(1, Number(params.get('hops') ?? 1) || 1));
  const relParam = params.get('rel');
  const [filter, setFilter] = useState<ClassFilter>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);

  const tenant = useTenantScope();
  const anchor = useMemo(() => ({ id: anchorId, kind }), [anchorId, kind]);
  const network = useEgoNetwork(tenant.tenantId, anchor, hops);
  const nodes = network.data?.nodes ?? [];
  const allEdges = network.data?.edges ?? [];
  const edges = filter === 'all' ? allEdges : allEdges.filter(e => edgeClass(e) === filter);
  const anchorLabel = nodeLabel(nodes, anchorId);

  function set(key: string, value: string | null) {
    setParams(prev => {
      const p = new URLSearchParams(prev);
      if (value === null) p.delete(key);
      else p.set(key, value);
      return p;
    });
  }

  const openEdge = relParam ? allEdges.find(e => e.id === relParam) ?? null : null;
  if (openEdge) {
    return <RelationshipDetail edge={openEdge} nodes={nodes} anchorId={anchorId} onBack={() => set('rel', null)} />;
  }

  const counts = allEdges.reduce<Record<string, number>>((acc, e) => ({ ...acc, [edgeClass(e)]: (acc[edgeClass(e)] ?? 0) + 1 }), {});
  const filters: SegmentOption<ClassFilter>[] = [
    { value: 'all', label: `All${network.data ? ` · ${allEdges.length}` : ''}` },
    ...(['h2h', 'h2a', 'a2a', 'other'] as const)
      .filter(c => (counts[c] ?? 0) > 0)
      .map(c => ({ value: c, label: `${LAYER_LABEL[c]} · ${counts[c]}` })),
  ];
  const views: SegmentOption<View>[] = [
    { value: 'network', label: 'Network' },
    { value: 'list', label: 'Relationships' },
    { value: 'types', label: 'By type' },
    { value: 'history', label: 'History' },
    { value: 'paths', label: 'Paths' },
  ];
  const selected = edges.find(e => e.id === selectedId) ?? null;
  const focus = nodes.find(n => n.id === focusId) ?? null;
  const dist = hopDistances(anchorId, allEdges);
  const ordered = [...edges].sort((x, y) => (y.score ?? -1) - (x.score ?? -1));
  const dated = [...edges].filter(e => e.validFrom).sort((x, y) => Date.parse(y.validFrom!) - Date.parse(x.validFrom!));

  const selectEdge = (e: RelEdge) => { setSelectedId(e.id); setFocusId(null); };
  const focusNode = (n: RelNode) => { setFocusId(n.id); setSelectedId(null); };
  const showSide = view === 'network' || view === 'list' || view === 'types';

  return (
    <div className="flex flex-col gap-4" data-testid="aether-relationships">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <span className="flex min-w-0 flex-col gap-1">
          <h1 className="text-[clamp(26px,4.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Relationships</h1>
          <span className="max-w-[620px] text-[14px] leading-[1.45]" style={{ color: 'var(--ae-mute)' }}>
            What connects <span style={{ color: 'var(--ae-ink)' }}>{anchorLabel}</span> to people, agents and organizations, and how it has changed.
          </span>
        </span>
        <span className="flex flex-wrap gap-3 text-[13px]">
          <Link to={entityHref(kind, anchorId).to} style={{ color: 'var(--ae-blue-ink)' }}>{entityHref(kind, anchorId).label} →</Link>
          <button type="button" onClick={() => navigate('/relationships')} className="ae-focus hover:underline" style={{ color: 'var(--ae-mute)' }}>Change centre</button>
        </span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedTabs label="Relationship types" options={filters} value={filters.some(f => f.value === filter) ? filter : 'all'} onChange={setFilter} />
        <SegmentedTabs label="Relationship views" options={views} value={view} onChange={v => set('view', v === 'network' ? null : v)} />
      </div>

      {tenant.error && <InlineNotice>Relationships are unavailable: your workspace could not be resolved ({tenant.error}).</InlineNotice>}
      {network.error && <InlineNotice>Relationships for this entity are unavailable right now.</InlineNotice>}
      {!tenant.error && !network.error && !network.data && <LoadingRow label="Reading the graph…" />}
      {relParam && network.data && !openEdge && <InlineNotice tone="mute">That relationship is not in the current view. Try more hops.</InlineNotice>}

      {network.data && view !== 'paths' && allEdges.length === 0 && (
        <EmptySlot testId="relationships-empty">No relationships are recorded for {anchorLabel} within {hops} hop{hops === 1 ? '' : 's'}.</EmptySlot>
      )}

      {network.data && (allEdges.length > 0 || view === 'paths') && (
        <div className={`ae-rise grid grid-cols-1 gap-3 ${showSide ? 'lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]' : ''}`} key={view}>
          <div className="min-w-0">
            {view === 'network' && (
              <GlassSection testId="ego-network">
                <span className="flex flex-wrap items-center justify-between gap-2">
                  <Eyebrow>Ego network · hop rings</Eyebrow>
                  <span className="flex items-center gap-1.5 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                    Reach
                    {[1, 2, 3].map(h => <OutlineChip key={h} selected={h === hops} onClick={() => set('hops', h === 1 ? null : String(h))}>{h === 1 ? '1 hop' : `${h} hops`}</OutlineChip>)}
                  </span>
                </span>
                {edges.length === 0
                  ? <EmptySlot>No relationships of this type.</EmptySlot>
                  : <RadialNetwork anchorId={anchorId} nodes={nodes} edges={edges} selectedEdgeId={selectedId} focusId={focusId} onSelectEdge={selectEdge} onFocusNode={focusNode} />}
                <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>Hover to trace · select a link or an entity to inspect it</span>
              </GlassSection>
            )}
            {view === 'list' && (
              <GlassSection testId="relationship-list">
                <Eyebrow>Relationships · strongest first</Eyebrow>
                {ordered.length === 0 && <EmptySlot>No relationships of this type.</EmptySlot>}
                {ordered.map(e => (
                  <button
                    key={e.id}
                    type="button"
                    onClick={() => selectEdge(e)}
                    data-testid="relationship-row"
                    className="ae-focus flex flex-wrap items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-[13px]"
                    style={{ background: e.id === selectedId ? 'var(--ae-blue-tint)' : 'transparent' }}
                  >
                    <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: layerColor(e.layer) }} />
                    <span className="min-w-0 flex-1 truncate">{nodeLabel(nodes, e.from)} ── {verb(e.type)} ── {nodeLabel(nodes, e.to)}</span>
                    <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{LAYER_LABEL[edgeClass(e)]}</span>
                    <span className="ae-mono w-8 text-right">{pct(e.score)}</span>
                  </button>
                ))}
              </GlassSection>
            )}
            {view === 'types' && (
              <GlassSection testId="arc-diagram">
                <Eyebrow>Arc diagram · by relationship type</Eyebrow>
                {edges.length === 0 ? <EmptySlot>No relationships of this type.</EmptySlot> : <ArcDiagram anchorId={anchorId} nodes={nodes} edges={edges} selectedEdgeId={selectedId} onSelectEdge={selectEdge} />}
              </GlassSection>
            )}
            {view === 'history' && (
              <GlassSection testId="relationship-history-list">
                <Eyebrow>When each link formed</Eyebrow>
                {dated.length === 0 && <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>No formation dates are recorded on these links.</span>}
                <FormationStrip edges={dated} onSelectEdge={e => set('rel', e.id)} />
                {dated.map((e, i) => (
                  <button
                    key={e.id}
                    type="button"
                    onClick={() => set('rel', e.id)}
                    className="ae-focus flex gap-3 py-2 text-left text-[13px]"
                    style={{ borderTop: i ? '1px solid var(--ae-edge-soft)' : undefined }}
                  >
                    <span className="ae-mono w-[96px] shrink-0" style={{ color: 'var(--ae-mute)' }}>{date(e.validFrom)}</span>
                    <span className="inline-block h-2 w-2 shrink-0 self-center rounded-full" style={{ background: layerColor(e.layer) }} />
                    <span className="min-w-0 flex-1">{nodeLabel(nodes, e.from)} {verb(e.type)} {nodeLabel(nodes, e.to)}{e.validTo ? ` · ended ${date(e.validTo)}` : ''}</span>
                  </button>
                ))}
                {edges.length > dated.length && <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>{edges.length - dated.length} link{edges.length - dated.length === 1 ? '' : 's'} carry no date.</span>}
              </GlassSection>
            )}
            {view === 'paths' && <PathExplorer tenantId={tenant.tenantId} anchor={anchor} nodes={nodes} />}
          </div>
          {showSide && (
            <div className="flex min-w-0 flex-col gap-3">
              <SelectedPanel nodes={nodes} edges={allEdges} edge={selected} focus={focus} anchorId={anchorId} onOpen={e => set('rel', e.id)} />
              <GlassSection>
                <Eyebrow>Reach</Eyebrow>
                {[1, 2, 3].filter(h => h <= hops).map(h => {
                  const n = [...dist.values()].filter(d => d === h).length;
                  return (
                    <div key={h} className="flex items-baseline justify-between text-[13px]">
                      <span style={{ color: 'var(--ae-mute)' }}>{h === 1 ? '1 hop' : `${h} hops`}</span>
                      <span className="ae-mono">{n}</span>
                    </div>
                  );
                })}
                {network.data?.summary && <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>{network.data.summary}</span>}
              </GlassSection>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Relationships (Claude Design handoff: Aether Relationships). Centred on one
 * entity; every node and link is read from the graph traversal engine
 * (`/v1/graph/traverse`, `/v1/graph/path`). Nothing is illustrative.
 */
export function RelationshipsPage() {
  const { entityId } = useParams<{ entityId: string }>();
  return (
    <GlassPage>
      {entityId ? <AnchoredRelationships anchorId={entityId} key={entityId} /> : <AnchorPicker />}
    </GlassPage>
  );
}
