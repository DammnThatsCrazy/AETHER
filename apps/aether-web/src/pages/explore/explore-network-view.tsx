import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon, cn } from '@aether/ui';
import type { GraphNode } from '@aether-app/components/graph/graph-canvas';
import { Eyebrow, InlineNotice, LinkButton, Panel, PrimaryButton, SecondaryButton, Spinner } from '@aether-app/components/ae-ui';
import { nodePlace, objectLinks, type GraphSnapshot } from './explore-model';
import {
  CATEGORIES,
  LINK_KINDS,
  buildNetwork,
  categoryMeta,
  directConnections,
  findReadPath,
  initials,
  nodeCategory,
  type CardLink,
  type NodeCategory,
  type Perspective,
  type PrincipalCard,
} from './explore-network';

/**
 * Graph network view (Claude Design handoff: Aether Explore → Graph): a
 * toolbar (search, scope, All/Human/Agent, hops, type counts), principal cards
 * with what each owns or uses, labelled links between principals, an
 * inspector listing the selected object's direct connections, and a path
 * strip from the scoped object to the selection. All of it is the page's one
 * graph read; a money label only appears where an edge carries an amount.
 */

const mute = { color: 'var(--ae-mute)' } as const;

const HOP_CHOICES: ReadonlyArray<{ readonly value: number | null; readonly label: string }> = [
  { value: 1, label: '1' },
  { value: 2, label: '2' },
  { value: 3, label: '3' },
  { value: 4, label: '4' },
  { value: null, label: '∞' },
];

const PERSPECTIVES: ReadonlyArray<{ readonly id: Perspective; readonly label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'human', label: 'Human' },
  { id: 'agent', label: 'Agent' },
];

export const DEFAULT_HOPS = 2;

function day(t: number): string {
  return new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
}

function describe(node: GraphNode): string {
  const place = nodePlace(node).label;
  const parts = [node.kind.toLowerCase()];
  if (place) parts.push(place);
  return parts.join(' · ');
}

function Segmented<T extends string>({ items, value, onChange, label, size = 'sm' }: {
  readonly items: ReadonlyArray<{ readonly id: T; readonly label: string }>;
  readonly value: T;
  readonly onChange: (id: T) => void;
  readonly label: string;
  readonly size?: 'sm' | 'md';
}) {
  return (
    <span className="inline-flex flex-none gap-0.5 rounded-full p-[3px]" style={{ background: 'var(--ae-edge-soft)' }} role="group" aria-label={label}>
      {items.map(item => (
        <button
          key={item.id}
          type="button"
          aria-pressed={value === item.id}
          onClick={() => onChange(item.id)}
          className={cn('ae-focus rounded-full', size === 'md' ? 'px-3.5 py-1.5 text-[13px]' : 'px-3 py-1 text-[12px]')}
          style={{ background: value === item.id ? 'var(--ae-chip-on)' : 'transparent', color: value === item.id ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)' }}
        >
          {item.label}
        </button>
      ))}
    </span>
  );
}

// ── Cards + links ───────────────────────────────────────────────────────────

function Avatar({ label }: { readonly label: string }) {
  return (
    <span
      aria-hidden="true"
      className="flex h-[22px] w-[22px] flex-none items-center justify-center rounded-full text-[9px] font-medium"
      style={{ border: '1px solid var(--ae-ink)', color: 'var(--ae-ink)' }}
    >
      {initials(label)}
    </span>
  );
}

function CategoryGlyph({ category }: { readonly category: NodeCategory }) {
  const meta = categoryMeta(category);
  return (
    <span className="flex flex-none" style={{ color: meta.color }} title={meta.singular}>
      <Icon name={meta.icon} decorative size="sm" />
    </span>
  );
}

function Card({ card, selectedId, scopeId, onSelect, refFor }: {
  readonly card: PrincipalCard;
  readonly selectedId: string | null;
  readonly scopeId: string | null;
  readonly onSelect: (node: GraphNode) => void;
  readonly refFor: (id: string) => (el: HTMLDivElement | null) => void;
}) {
  const selected = card.node.id === selectedId;
  return (
    <div
      ref={refFor(card.node.id)}
      data-graph-card={card.node.id}
      className="relative z-[1] flex min-w-0 flex-col rounded-[14px] sm:min-h-[150px]"
      style={{
        background: 'var(--ae-raised)',
        border: `1px solid ${selected ? 'var(--ae-blue)' : 'var(--ae-edge)'}`,
        boxShadow: selected ? '0 0 0 3px var(--ae-blue-tint)' : 'var(--ae-lift)',
      }}
    >
      <button
        type="button"
        onClick={() => onSelect(card.node)}
        aria-pressed={selected}
        className="ae-focus flex min-w-0 items-center gap-2 rounded-t-[14px] px-2.5 pb-2 pt-2.5 text-left"
      >
        <Avatar label={card.node.label} />
        <span className="flex min-w-0 flex-col leading-tight">
          <span className="truncate text-[13px] font-medium">{card.node.label}</span>
          <span className="truncate text-[11px]" style={mute}>
            {describe(card.node)}{card.node.id === scopeId ? ' · scope' : ''}
          </span>
        </span>
      </button>
      <div className="mx-2.5 border-t" style={{ borderColor: 'var(--ae-edge-soft)' }} />
      {card.rows.length === 0 ? (
        <span className="px-2.5 py-2 text-[11px]" style={{ color: 'var(--ae-faint)' }}>Nothing owned or used in this read.</span>
      ) : (
        <ul className="flex flex-col gap-0.5 px-1.5 py-1.5">
          {card.rows.map(row => (
            <li key={row.node.id}>
              <button
                type="button"
                onClick={() => onSelect(row.node)}
                data-graph-card-row={row.node.id}
                className="ae-focus flex w-full min-w-0 items-center gap-1.5 rounded-lg px-1 py-[3px] text-left text-[11.5px]"
                style={{ background: row.node.id === selectedId ? 'var(--ae-blue-tint)' : 'transparent' }}
              >
                <CategoryGlyph category={row.category} />
                <span className="min-w-0 flex-1 truncate">{row.node.label}</span>
                <span className="max-w-[45%] flex-none truncate text-[10px]" style={mute}>{row.label}</span>
              </button>
            </li>
          ))}
          {card.hidden > 0 && <li className="px-1 text-[10.5px]" style={mute}>+{card.hidden} more</li>}
        </ul>
      )}
    </div>
  );
}

interface Segment {
  readonly link: CardLink;
  readonly x1: number;
  readonly y1: number;
  readonly x2: number;
  readonly y2: number;
}

/** Point where the ray from a rect's centre toward (tx, ty) leaves the rect. */
function exitPoint(r: DOMRect, ox: number, oy: number, tx: number, ty: number) {
  const cx = r.left - ox + r.width / 2;
  const cy = r.top - oy + r.height / 2;
  const dx = tx - cx;
  const dy = ty - cy;
  if (dx === 0 && dy === 0) return { x: cx, y: cy };
  const sx = dx === 0 ? Infinity : (r.width / 2) / Math.abs(dx);
  const sy = dy === 0 ? Infinity : (r.height / 2) / Math.abs(dy);
  const s = Math.min(sx, sy);
  return { x: cx + dx * s, y: cy + dy * s };
}

function CardGrid({ cards, links, selectedId, scopeId, onSelect }: {
  readonly cards: readonly PrincipalCard[];
  readonly links: readonly CardLink[];
  readonly selectedId: string | null;
  readonly scopeId: string | null;
  readonly onSelect: (node: GraphNode) => void;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const els = useRef(new Map<string, HTMLDivElement>());
  const refs = useRef(new Map<string, (el: HTMLDivElement | null) => void>());
  const refFor = (id: string) => {
    let fn = refs.current.get(id);
    if (!fn) {
      fn = (el) => { if (el) els.current.set(id, el); else els.current.delete(id); };
      refs.current.set(id, fn);
    }
    return fn;
  };
  const [segments, setSegments] = useState<readonly Segment[]>([]);
  const [box, setBox] = useState({ w: 0, h: 0 });

  useLayoutEffect(() => {
    const root = container.current;
    if (!root) return;
    const measure = () => {
      const o = root.getBoundingClientRect();
      const next: Segment[] = [];
      for (const link of links) {
        const a = els.current.get(link.source)?.getBoundingClientRect();
        const b = els.current.get(link.target)?.getBoundingClientRect();
        if (!a || !b || a.width === 0 || b.width === 0) continue;
        const acx = a.left - o.left + a.width / 2;
        const acy = a.top - o.top + a.height / 2;
        const bcx = b.left - o.left + b.width / 2;
        const bcy = b.top - o.top + b.height / 2;
        const p1 = exitPoint(a, o.left, o.top, bcx, bcy);
        const p2 = exitPoint(b, o.left, o.top, acx, acy);
        next.push({ link, x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y });
      }
      setSegments(next);
      setBox({ w: o.width, h: o.height });
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    return () => ro.disconnect();
  }, [cards, links]);

  const kindOf = (id: string) => LINK_KINDS.find(k => k.id === id)!;
  const byId = new Map(cards.map(c => [c.node.id, c.node] as const));

  return (
    <div ref={container} className="relative" data-testid="graph-card-grid">
      <svg className="pointer-events-none absolute inset-0 z-0" width={box.w} height={box.h} aria-hidden="true">
        <defs>
          {LINK_KINDS.map(k => (
            <marker key={k.id} id={`graph-arrow-${k.id}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0 L8 4 L0 8 z" fill={k.color} />
            </marker>
          ))}
        </defs>
        {segments.map(s => {
          const k = kindOf(s.link.kind);
          const touches = selectedId !== null && (s.link.source === selectedId || s.link.target === selectedId);
          return (
            <line
              key={s.link.id}
              x1={s.x1}
              y1={s.y1}
              x2={s.x2}
              y2={s.y2}
              stroke={k.color}
              strokeWidth={touches ? 2 : 1.4}
              strokeOpacity={selectedId === null || touches ? 0.95 : 0.45}
              strokeDasharray={k.dash}
              markerEnd={`url(#graph-arrow-${k.id})`}
            />
          );
        })}
      </svg>
      <div className="grid gap-x-7 gap-y-6 sm:grid-cols-[repeat(auto-fill,minmax(186px,1fr))]">
        {cards.map(card => (
          <Card key={card.node.id} card={card} selectedId={selectedId} scopeId={scopeId} onSelect={onSelect} refFor={refFor} />
        ))}
      </div>
      {segments.map(s => {
        const k = kindOf(s.link.kind);
        // The pill sits in the gap just before the target card, so a link that
        // passes behind another card is still labelled where it lands.
        const len = Math.hypot(s.x2 - s.x1, s.y2 - s.y1) || 1;
        const back = Math.min(len / 2, 13);
        const left = s.x2 - ((s.x2 - s.x1) / len) * back;
        const top = s.y2 - ((s.y2 - s.y1) / len) * back;
        return (
          <span
            key={`pill-${s.link.id}`}
            className="pointer-events-none absolute z-[2] max-w-[120px] -translate-x-1/2 -translate-y-1/2 truncate whitespace-nowrap rounded-full px-1.5 py-px text-[10px]"
            style={{ left, top, background: 'var(--ae-raised)', border: `1px solid ${k.color}`, color: 'var(--ae-ink)' }}
          >
            {s.link.label}
          </span>
        );
      })}
      <ul className="sr-only" data-testid="graph-card-links" aria-label="Links between the cards">
        {links.map(link => (
          <li key={link.id} data-link-kind={link.kind}>
            {byId.get(link.source)?.label} → {byId.get(link.target)?.label}: {link.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl px-3 py-2 text-[11px]" style={{ border: '1px solid var(--ae-edge-soft)', ...mute }} data-testid="graph-legend">
      {LINK_KINDS.map(k => (
        <span key={k.id} className="inline-flex items-center gap-1.5">
          <svg width="18" height="6" aria-hidden="true"><line x1="0" y1="3" x2="18" y2="3" stroke={k.color} strokeWidth="2" strokeDasharray={k.dash} /></svg>
          {k.label}
        </span>
      ))}
      <span>Arrows follow each link’s direction. Rows are what each principal owns or uses; a pill shows an amount only when the link reports one.</span>
    </div>
  );
}

// ── Inspector + path strip ──────────────────────────────────────────────────

function Inspector({ node, snapshot, scopeId, onSelect, onScope, onTrace }: {
  readonly node: GraphNode | null;
  readonly snapshot: GraphSnapshot;
  readonly scopeId: string | null;
  readonly onSelect: (node: GraphNode) => void;
  readonly onScope: (id: string) => void;
  readonly onTrace: (id: string) => void;
}) {
  const navigate = useNavigate();
  const connections = useMemo(() => (node ? directConnections(node.id, snapshot) : []), [node, snapshot]);
  if (!node) {
    return (
      <Panel className="flex flex-col gap-2 p-4" style={{ minHeight: 160 }}>
        <Eyebrow>Inspector</Eyebrow>
        <span className="text-[13px]" style={mute}>Select a card or a row to see what it is directly connected to.</span>
      </Panel>
    );
  }
  const links = objectLinks(node, snapshot.clusters);
  const [primary, ...secondary] = links;
  const risk = typeof node.riskScore === 'number' ? `risk ${node.riskScore.toFixed(2)}` : null;
  const shown = connections.slice(0, 10);
  return (
    <Panel className="flex flex-col gap-2.5 p-4">
      <span className="flex flex-col gap-1" data-testid="graph-inspector">
        <Eyebrow>Inspector</Eyebrow>
        <span className="truncate text-[18px] font-medium">{node.label}</span>
        <span className="text-[12px]" style={mute}>{[describe(node), risk].filter(Boolean).join(' · ')}</span>
      </span>
      <Eyebrow className="pt-1">Direct connections</Eyebrow>
      {connections.length === 0 ? (
        <span className="text-[12px]" style={mute}>No relationships for this object in this read.</span>
      ) : (
        <dl className="flex flex-col" data-testid="graph-inspector-connections">
          {shown.map(c => (
            <div key={`${c.node.id}-${c.edge.id}`} className="flex items-start justify-between gap-3 border-t py-[7px] text-[13px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>
              <dt className="flex-none" style={mute}>{categoryMeta(c.category).label}</dt>
              <dd className="min-w-0 text-right">
                <button type="button" onClick={() => onSelect(c.node)} className="ae-focus hover:underline">{c.node.label}</button>
                <span style={mute}> · {c.label}</span>
              </dd>
            </div>
          ))}
          {connections.length > shown.length && (
            <span className="border-t pt-1.5 text-[12px]" style={{ borderColor: 'var(--ae-edge-soft)', ...mute }}>+{connections.length - shown.length} more connections</span>
          )}
        </dl>
      )}
      <div className="flex flex-col gap-2 pt-1">
        {primary && (
          <PrimaryButton className="w-full" onClick={() => navigate(primary.to)}>
            {primary.label === 'Open profile' ? 'Open Profile 360' : primary.label}
          </PrimaryButton>
        )}
        <div className="flex flex-wrap gap-2">
          {node.id !== scopeId && (
            <SecondaryButton className="flex-1 !px-3 text-[12px]" onClick={() => onScope(node.id)}>Scope here</SecondaryButton>
          )}
          <SecondaryButton className="flex-1 !px-3 text-[12px]" onClick={() => onTrace(node.id)}>Open trace</SecondaryButton>
        </div>
        {secondary.length > 0 && (
          <span className="flex flex-wrap gap-x-3 gap-y-1">
            {secondary.map(l => <LinkButton key={l.to} onClick={() => navigate(l.to)}>{l.label} →</LinkButton>)}
          </span>
        )}
      </div>
    </Panel>
  );
}

function PathStrip({ scope, target, snapshot, onSelect }: {
  readonly scope: GraphNode | null;
  readonly target: GraphNode | null;
  readonly snapshot: GraphSnapshot;
  readonly onSelect: (node: GraphNode) => void;
}) {
  const path = useMemo(
    () => (scope && target && scope.id !== target.id ? findReadPath(scope.id, target.id, snapshot) : null),
    [scope, target, snapshot],
  );
  let title = 'Path';
  let body: ReactNode;
  if (!scope) {
    body = <span className="text-[13px]" style={mute}>Scope the graph to an object, then select another to see how they connect.</span>;
  } else if (!target || target.id === scope.id) {
    title = `Path from ${scope.label}`;
    body = <span className="text-[13px]" style={mute}>Select another card or row to see how {scope.label} reaches it.</span>;
  } else if (!path) {
    title = `Path from ${scope.label} to ${target.label}`;
    body = <span className="text-[13px]" style={mute} data-testid="graph-path-none">No path between them in this read.</span>;
  } else {
    title = `Path from ${scope.label} to ${target.label}`;
    const facts = [
      `${path.hops} hop${path.hops === 1 ? '' : 's'}`,
      path.firstObserved !== null ? `first observed ${day(path.firstObserved)}` : null,
      path.lastObserved !== null ? `last observed ${day(path.lastObserved)}` : null,
      path.confidence !== null ? `confidence ${Math.round(path.confidence * 100)}%` : null,
    ].filter(Boolean);
    body = (
      <>
        <ol className="flex flex-wrap items-center gap-1.5" aria-label="Path steps">
          {path.steps.map(step => (
            <li key={step.node.id} className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => onSelect(step.node)}
                className="ae-focus rounded-full px-2.5 py-[3px] text-[13px]"
                style={{ background: 'var(--ae-edge-soft)' }}
              >
                {step.node.label}
              </button>
              {step.relation && <span className="text-[11px]" style={mute}>{step.relation} →</span>}
            </li>
          ))}
        </ol>
        <span className="ae-mono text-[11px]" style={mute}>{facts.join(' · ')}</span>
      </>
    );
  }
  return (
    <Panel className="flex flex-col gap-2 px-4 py-3.5">
      <span data-testid="graph-path-strip" className="flex flex-col gap-2">
        <Eyebrow>{title}</Eyebrow>
        {body}
      </span>
    </Panel>
  );
}

// ── View ────────────────────────────────────────────────────────────────────

export function ExploreNetworkView({
  snapshot,
  scopeId,
  onScope,
  onSelectObject,
  onOpenTrace,
  onOpenAdvanced,
}: {
  readonly snapshot: GraphSnapshot;
  readonly scopeId: string | null;
  readonly onScope: (id: string | null) => void;
  readonly onSelectObject: (node: GraphNode) => void;
  readonly onOpenTrace: (id: string | null, visual: 'globe' | 'flow') => void;
  readonly onOpenAdvanced: () => void;
}) {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [perspective, setPerspective] = useState<Perspective>('all');
  const [hops, setHops] = useState<number | null>(DEFAULT_HOPS);
  const [hidden, setHidden] = useState<ReadonlySet<NodeCategory>>(new Set());
  const [pickedId, setPickedId] = useState<string | null>(null);

  const layout = useMemo(
    () => buildNetwork(snapshot, { scopeId, hops, perspective, hiddenCategories: hidden, search }),
    [snapshot, scopeId, hops, perspective, hidden, search],
  );
  const byId = useMemo(() => new Map(snapshot.nodes.map(n => [n.id, n] as const)), [snapshot.nodes]);
  const scope = layout.scope;
  const selected = byId.get(pickedId ?? '') ?? scope ?? layout.cards[0]?.node ?? null;

  const select = (node: GraphNode) => {
    setPickedId(node.id);
    onSelectObject(node);
  };
  const toggleCategory = (id: NodeCategory) => setHidden(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  let content: ReactNode;
  if (snapshot.status === 'loading') {
    content = (
      <div className="flex min-h-[320px] flex-col items-center justify-center gap-3" data-testid="graph-visual-loading">
        <Spinner />
        <span className="text-[13px]" style={mute}>Reading the graph…</span>
      </div>
    );
  } else if (snapshot.status === 'error') {
    content = (
      <div className="flex flex-col gap-2" data-testid="graph-visual-error">
        <InlineNotice tone="ember">The graph read failed, so principals and their connections are unavailable.</InlineNotice>
        <LinkButton className="self-start" onClick={onOpenAdvanced}>See the error in the advanced explorer →</LinkButton>
      </div>
    );
  } else if (snapshot.nodes.length === 0) {
    content = (
      <div className="flex min-h-[300px] flex-col items-center justify-center gap-2 text-center" data-testid="graph-visual-empty">
        <span className="text-[15px] font-medium">No objects in this graph read yet</span>
        <span className="max-w-[420px] text-[13px]" style={mute}>People, agents, wallets and the links between them appear here once a connected source or SDK sends events.</span>
        <LinkButton onClick={() => navigate('/activation')}>Connect a source →</LinkButton>
      </div>
    );
  } else if (layout.cards.length === 0) {
    content = (
      <div className="flex min-h-[220px] flex-col items-center justify-center gap-2 text-center" data-testid="graph-cards-none">
        <span className="text-[14px] font-medium">Nothing matches these filters</span>
        <span className="max-w-[420px] text-[13px]" style={mute}>
          {search.trim() ? `No principal or row matches “${search.trim()}”.` : 'No principals of this kind are within reach.'} Widen the hops, switch perspective or turn a type back on.
        </span>
      </div>
    );
  } else {
    content = (
      <div className="flex flex-col gap-4">
        <CardGrid cards={layout.cards} links={layout.links} selectedId={selected?.id ?? null} scopeId={scope?.id ?? null} onSelect={select} />
        <Legend />
      </div>
    );
  }

  const presentCategories = CATEGORIES.filter(c => (layout.counts.get(c.id) ?? 0) > 0 || hidden.has(c.id));
  const hopsDisabled = !scope;

  return (
    <div data-testid="explore-network" className="flex min-w-0 flex-col gap-4">
      {/* Toolbar */}
      <Panel className="flex flex-col gap-3 px-4 py-4 md:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <h1 className="text-[24px] font-medium leading-tight tracking-[-0.48px]">Graph</h1>
            <span className="text-[13px]" style={mute}>How is everything connected?</span>
          </div>
          <Segmented
            label="Graph view"
            size="md"
            items={[{ id: 'network', label: 'Network' }, { id: 'globe', label: 'Globe' }]}
            value="network"
            onChange={(v) => { if (v === 'globe') onOpenTrace(scope?.id ?? null, 'globe'); }}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative flex min-w-[200px] flex-1 items-center sm:max-w-[240px]">
            <span className="pointer-events-none absolute left-3 flex" style={mute}><Icon name="search" decorative size="sm" /></span>
            <input
              type="search"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search the graph…"
              aria-label="Search the graph"
              className="ae-focus w-full rounded-full py-1.5 pl-8 pr-3 text-[12px]"
              style={{ background: 'transparent', border: '1px solid var(--ae-edge)', color: 'var(--ae-ink)' }}
            />
          </label>
          {scope ? (
            <span
              className="inline-flex items-center gap-1 rounded-full py-1 pl-3 pr-1.5 text-[12px]"
              style={{ background: 'var(--ae-blue-tint)', color: 'var(--ae-blue-ink)', border: '1px solid var(--ae-blue)' }}
              data-testid="graph-scope-chip"
            >
              Scope: {scope.label}
              <button type="button" onClick={() => onScope(null)} className="ae-focus flex rounded-full p-0.5" aria-label="Clear scope">
                <Icon name="x" decorative size="sm" />
              </button>
            </span>
          ) : (
            <span className="rounded-full px-3 py-1 text-[12px]" style={{ border: '1px solid var(--ae-edge)', ...mute }} data-testid="graph-scope-chip">
              {scopeId ? 'Scoped object not in this read' : 'Scope: whole read'}
            </span>
          )}
          <Segmented label="Perspective" items={PERSPECTIVES} value={perspective} onChange={setPerspective} />
          <LinkButton className="ml-auto" onClick={onOpenAdvanced}>Advanced explorer →</LinkButton>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Eyebrow className="mr-1">Hops</Eyebrow>
          {HOP_CHOICES.map(h => {
            const on = !hopsDisabled && hops === h.value;
            return (
              <button
                key={h.label}
                type="button"
                aria-pressed={on}
                disabled={hopsDisabled}
                title={hopsDisabled ? 'Scope the graph to an object to limit hops' : `${h.label} hop${h.value === 1 ? '' : 's'} from ${scope?.label}`}
                onClick={() => setHops(h.value)}
                data-hops={h.label}
                className="ae-focus ae-mono h-[26px] min-w-[30px] rounded-full px-2 text-[12px] disabled:cursor-not-allowed disabled:opacity-40"
                style={{ background: on ? 'var(--ae-blue)' : 'transparent', color: on ? 'var(--ae-raised)' : 'var(--ae-mute)' }}
              >
                {h.label}
              </button>
            );
          })}
          <span aria-hidden="true" className="mx-1.5 h-[18px] w-px" style={{ background: 'var(--ae-edge)' }} />
          <span className="flex flex-wrap gap-1.5" role="group" aria-label="Object types" data-testid="graph-type-counts">
            {presentCategories.length === 0 && snapshot.status === 'ready' && (
              <span className="text-[12px]" style={mute}>No object types in reach.</span>
            )}
            {presentCategories.map(c => {
              const on = !hidden.has(c.id);
              return (
                <button
                  key={c.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggleCategory(c.id)}
                  data-category={c.id}
                  className="ae-focus inline-flex items-center gap-1 rounded-full px-2.5 py-[3px] text-[12px]"
                  style={{
                    border: `1px solid ${on ? c.color : 'var(--ae-edge)'}`,
                    background: on ? 'var(--ae-raised)' : 'transparent',
                    color: on ? 'var(--ae-ink)' : 'var(--ae-faint)',
                  }}
                >
                  {c.label}
                  <span className="ae-mono" style={mute}>{layout.counts.get(c.id) ?? 0}</span>
                </button>
              );
            })}
          </span>
        </div>
      </Panel>

      {/* Cards + inspector */}
      <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_290px]">
        <Panel className="min-w-0 p-4 md:p-5">{content}</Panel>
        <div className="lg:sticky lg:top-4">
          {snapshot.status === 'ready' && snapshot.nodes.length > 0 ? (
            <Inspector
              node={selected}
              snapshot={snapshot}
              scopeId={scope?.id ?? null}
              onSelect={select}
              onScope={(id) => { setPickedId(null); onScope(id); }}
              onTrace={(id) => onOpenTrace(id, 'globe')}
            />
          ) : (
            <Panel className="flex flex-col gap-2 p-4">
              <Eyebrow>Inspector</Eyebrow>
              <span className="text-[13px]" style={mute}>
                {snapshot.status === 'loading' ? 'Waiting for the graph read…' : snapshot.status === 'error' ? 'Unavailable while the graph read is failing.' : 'Nothing to inspect yet.'}
              </span>
            </Panel>
          )}
        </div>
      </div>

      {snapshot.status === 'ready' && snapshot.nodes.length > 0 && (
        <PathStrip scope={scope} target={selected} snapshot={snapshot} onSelect={select} />
      )}
    </div>
  );
}
