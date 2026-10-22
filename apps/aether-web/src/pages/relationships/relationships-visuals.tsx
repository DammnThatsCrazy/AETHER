import { useMemo, useState } from 'react';
import {
  entityClass,
  hopDistances,
  type EntityClass,
  type RelEdge,
  type RelNode,
} from '@aether-app/features/relationships/use-relationships';

/**
 * Data-driven SVG visuals for the Relationships page (Claude Design handoff:
 * Aether Relationships — radial ego network, arc diagram by type, formation
 * strip). Every mark is a node or edge from the graph read; positions are
 * deterministic from the response.
 */

export const CLASS_COLOR: Record<EntityClass, string> = {
  human: 'var(--ae-blue)',
  agent: 'var(--ae-sage)',
  organization: 'var(--ae-amber)',
  cluster: 'var(--ae-teal)',
  other: 'var(--ae-mute)',
};

export function layerColor(layer: RelEdge['layer']): string {
  if (layer === 'H2H') return 'var(--ae-blue)';
  if (layer === 'H2A' || layer === 'A2H') return 'var(--ae-sage)';
  if (layer === 'A2A') return 'var(--ae-violet)';
  return 'var(--ae-mute)';
}

const TYPE_COLORS = ['var(--ae-blue)', 'var(--ae-sage)', 'var(--ae-amber)', 'var(--ae-violet)', 'var(--ae-teal)', 'var(--ae-solar)', 'var(--ae-ember)', 'var(--ae-mute)'];

export function typeColor(types: readonly string[], type: string): string {
  const i = types.indexOf(type);
  return TYPE_COLORS[(i < 0 ? 0 : i) % TYPE_COLORS.length]!;
}

export function verb(type: string): string {
  return type.toLowerCase().replace(/_/g, ' ');
}

const MAX_DRAWN = 120;

// ── Radial ego network ──────────────────────────────────────────────────────

export function RadialNetwork({
  anchorId,
  nodes,
  edges,
  selectedEdgeId,
  focusId,
  onSelectEdge,
  onFocusNode,
}: {
  readonly anchorId: string;
  readonly nodes: readonly RelNode[];
  readonly edges: readonly RelEdge[];
  readonly selectedEdgeId: string | null;
  readonly focusId: string | null;
  readonly onSelectEdge: (edge: RelEdge) => void;
  readonly onFocusNode: (node: RelNode) => void;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const layout = useMemo(() => {
    const dist = hopDistances(anchorId, edges);
    const byId = new Map(nodes.map(n => [n.id, n]));
    const maxD = Math.max(1, ...[...dist.values()]);
    const rings = new Map<number, RelNode[]>();
    let drawn = 0;
    [...dist.entries()]
      .filter(([id, d]) => d > 0 && byId.has(id))
      .sort((a, b) => a[1] - b[1])
      .forEach(([id, d]) => {
        if (drawn >= MAX_DRAWN) return;
        drawn += 1;
        rings.set(d, [...(rings.get(d) ?? []), byId.get(id)!]);
      });
    const pos = new Map<string, { x: number; y: number; d: number }>([[anchorId, { x: 300, y: 300, d: 0 }]]);
    rings.forEach((list, d) => {
      const sorted = [...list].sort((a, b) => entityClass(a.kind).localeCompare(entityClass(b.kind)) || a.label.localeCompare(b.label));
      const r = (d / maxD) * 245;
      sorted.forEach((n, i) => {
        const angle = (2 * Math.PI * i) / sorted.length - Math.PI / 2 + d * 0.35;
        pos.set(n.id, { x: 300 + r * Math.cos(angle), y: 300 + r * Math.sin(angle), d });
      });
    });
    return { pos, maxD, rings, hidden: dist.size - 1 - drawn };
  }, [anchorId, nodes, edges]);

  const active = hover ?? focusId;
  const touches = (e: RelEdge, id: string | null) => !!id && (e.from === id || e.to === id);
  const anchor = nodes.find(n => n.id === anchorId);
  const ringOneSmall = (layout.rings.get(1)?.length ?? 0) <= 16;

  return (
    <div className="flex flex-col gap-1.5">
      <svg viewBox="0 0 600 600" className="mx-auto w-full" style={{ maxWidth: 560 }} role="img" aria-label={`Ego network with ${layout.pos.size - 1} connected entities`}>
        {Array.from({ length: layout.maxD }, (_, i) => i + 1).map(d => (
          <g key={`ring-${d}`}>
            <circle cx="300" cy="300" r={(d / layout.maxD) * 245} fill="none" stroke="var(--ae-edge)" strokeDasharray="3 5" />
            <text x="300" y={300 - (d / layout.maxD) * 245 - 6} textAnchor="middle" fontSize="11" fill="var(--ae-faint)">{d === 1 ? '1 hop' : `${d} hops`}</text>
          </g>
        ))}
        {edges.map(e => {
          const a = layout.pos.get(e.from);
          const b = layout.pos.get(e.to);
          if (!a || !b) return null;
          const on = e.id === selectedEdgeId || touches(e, active);
          return (
            <g key={e.id} data-testid="network-edge" onClick={() => onSelectEdge(e)} style={{ cursor: 'pointer' }}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth="12" />
              <line
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={layerColor(e.layer)}
                strokeWidth={e.id === selectedEdgeId ? 3.5 : on ? 2.5 : 1.4}
                strokeOpacity={active && !on ? 0.2 : 0.85}
                strokeDasharray={e.properties['inferred'] === true ? '5 4' : undefined}
              >
                <title>{`${verb(e.type)}${e.score !== null ? ` · strength ${Math.round(e.score * 100)}` : ''}`}</title>
              </line>
            </g>
          );
        })}
        {[...layout.pos.entries()].map(([id, p]) => {
          const node = id === anchorId ? anchor ?? { id, kind: 'entity', label: id, properties: {} } : nodes.find(n => n.id === id)!;
          const isAnchor = id === anchorId;
          const lit = !active || active === id || edges.some(e => touches(e, active) && touches(e, id));
          const showLabel = isAnchor || id === active || (p.d === 1 && ringOneSmall);
          return (
            <g
              key={id}
              data-testid="network-node"
              transform={`translate(${p.x} ${p.y})`}
              style={{ cursor: 'pointer', opacity: lit ? 1 : 0.35 }}
              onMouseEnter={() => setHover(id)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onFocusNode(node)}
            >
              <circle
                r={isAnchor ? 15 : 9}
                fill={CLASS_COLOR[entityClass(node.kind)]}
                stroke={id === focusId ? 'var(--ae-ink)' : 'var(--ae-card)'}
                strokeWidth={id === focusId ? 2.5 : 2}
              />
              {showLabel && (
                <text y={isAnchor ? 32 : 22} textAnchor="middle" fontSize={isAnchor ? 14 : 11} fontWeight={isAnchor ? 600 : 400} fill="var(--ae-ink)">
                  {node.label.length > 22 ? `${node.label.slice(0, 21)}…` : node.label}
                </text>
              )}
              <title>{`${node.label} · ${node.kind}`}</title>
            </g>
          );
        })}
      </svg>
      <span className="flex flex-wrap justify-center gap-3 text-[11px]" style={{ color: 'var(--ae-mute)' }}>
        {(['human', 'agent', 'organization', 'cluster', 'other'] as const).map(c => (
          <span key={c} className="inline-flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full" style={{ background: CLASS_COLOR[c] }} />{c}</span>
        ))}
        {layout.hidden > 0 && <span>{layout.hidden} more not drawn</span>}
      </span>
    </div>
  );
}

// ── Arc diagram by relationship type ────────────────────────────────────────

export function ArcDiagram({
  anchorId,
  nodes,
  edges,
  selectedEdgeId,
  onSelectEdge,
}: {
  readonly anchorId: string;
  readonly nodes: readonly RelNode[];
  readonly edges: readonly RelEdge[];
  readonly selectedEdgeId: string | null;
  readonly onSelectEdge: (edge: RelEdge) => void;
}) {
  const types = useMemo(() => {
    const counts = new Map<string, number>();
    edges.forEach(e => counts.set(e.type, (counts.get(e.type) ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [edges]);
  const typeNames = types.map(([t]) => t);
  const [only, setOnly] = useState<string | null>(null);

  const order = useMemo(() => {
    const dist = hopDistances(anchorId, edges);
    return [...dist.entries()].sort((a, b) => a[1] - b[1]).map(([id]) => id).slice(0, MAX_DRAWN);
  }, [anchorId, edges]);
  const x = new Map(order.map((id, i) => [id, order.length === 1 ? 300 : 24 + (i * 552) / (order.length - 1)]));
  const labelOf = (id: string) => nodes.find(n => n.id === id)?.label ?? id;
  const baseY = 210;

  return (
    <div className="flex flex-col gap-2.5">
      <span className="flex flex-wrap gap-1.5">
        {types.map(([t, n]) => (
          <button
            key={t}
            type="button"
            aria-pressed={only === t}
            onClick={() => setOnly(only === t ? null : t)}
            className="ae-focus inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px]"
            style={{ borderColor: only === t ? 'var(--ae-chip-on)' : 'var(--ae-edge)', background: only === t ? 'var(--ae-chip-on)' : 'transparent', color: only === t ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)' }}
          >
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: typeColor(typeNames, t) }} />
            {verb(t)} <span className="ae-mono" style={{ opacity: 0.7 }}>{n}</span>
          </button>
        ))}
      </span>
      <svg viewBox="0 0 600 240" className="w-full" role="img" aria-label="Arc diagram of relationships by type">
        {edges.map(e => {
          const x1 = x.get(e.from);
          const x2 = x.get(e.to);
          if (x1 === undefined || x2 === undefined || x1 === x2) return null;
          const dim = only !== null && e.type !== only;
          const r = Math.abs(x2 - x1) / 2;
          const [l, rr] = x1 < x2 ? [x1, x2] : [x2, x1];
          return (
            <path
              key={e.id}
              data-testid="arc"
              d={`M ${l} ${baseY} A ${r} ${Math.min(r, 195)} 0 0 1 ${rr} ${baseY}`}
              fill="none"
              stroke={typeColor(typeNames, e.type)}
              strokeWidth={e.id === selectedEdgeId ? 3.5 : 1.8}
              strokeOpacity={dim ? 0.12 : 0.85}
              style={{ cursor: 'pointer' }}
              onClick={() => onSelectEdge(e)}
            >
              <title>{`${labelOf(e.from)} ${verb(e.type)} ${labelOf(e.to)}`}</title>
            </path>
          );
        })}
        {order.map(id => (
          <circle key={id} cx={x.get(id)} cy={baseY} r={id === anchorId ? 7 : 4.5} fill={id === anchorId ? 'var(--ae-ink)' : CLASS_COLOR[entityClass(nodes.find(n => n.id === id)?.kind ?? '')]}>
            <title>{labelOf(id)}</title>
          </circle>
        ))}
        <text x={x.get(anchorId) ?? 24} y={baseY + 22} fontSize="11" fill="var(--ae-mute)" textAnchor="start">{labelOf(anchorId)}</text>
      </svg>
      <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>Entities are ordered by hops from the centre. Select a type to isolate it; select an arc to inspect it.</span>
    </div>
  );
}

// ── Formation strip (when each link formed) ─────────────────────────────────

export function FormationStrip({ edges, onSelectEdge }: { readonly edges: readonly RelEdge[]; readonly onSelectEdge: (edge: RelEdge) => void }) {
  const dated = edges
    .map(e => ({ e, t: e.validFrom ? Date.parse(e.validFrom) : NaN }))
    .filter(d => !Number.isNaN(d.t));
  if (dated.length === 0) return null;
  const min = Math.min(...dated.map(d => d.t));
  const max = Math.max(...dated.map(d => d.t));
  const span = max - min || 1;
  const fmt = (t: number) => new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  return (
    <div className="flex flex-col gap-1">
      <div className="relative h-8" data-testid="formation-strip">
        <span className="absolute left-0 right-0 top-1/2" style={{ borderTop: '1px solid var(--ae-edge)' }} />
        {dated.map(({ e, t }) => (
          <button
            key={e.id}
            type="button"
            aria-label={`${verb(e.type)} formed ${fmt(t)}`}
            onClick={() => onSelectEdge(e)}
            className="ae-focus absolute top-1/2 h-3 w-3 rounded-full"
            style={{ left: `calc(${((t - min) / span) * 100}% - 6px)`, marginTop: -6, background: layerColor(e.layer), border: '2px solid var(--ae-card)' }}
          />
        ))}
      </div>
      <span className="flex justify-between text-[11px]" style={{ color: 'var(--ae-faint)' }}>
        <span>{fmt(min)}</span>
        <span>{fmt(max)}</span>
      </span>
    </div>
  );
}
