import type { PatternGraphView } from './use-patterns';

const ROLE_COLOR: Record<string, string> = {
  pattern: 'var(--ae-ember)',
  member: 'var(--ae-blue)',
  member_pattern: 'var(--ae-amber)',
  principal: 'var(--ae-sage)',
  attribute: 'var(--ae-mute)',
};

const SIZE = 420;
const CENTER = SIZE / 2;

/** Deterministic radial layout: the pattern in the middle, its members on an
 *  inner ring, attributes / principals / member patterns on an outer ring. */
function layout(graph: PatternGraphView): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>();
  const inner = graph.nodes.filter(n => n.role === 'member');
  const outer = graph.nodes.filter(n => n.role !== 'member' && n.role !== 'pattern');
  for (const n of graph.nodes.filter(n => n.role === 'pattern')) pos.set(n.id, { x: CENTER, y: CENTER });
  const ring = (nodes: typeof graph.nodes, r: number, offset: number) => nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(nodes.length, 1) + offset;
    pos.set(n.id, { x: CENTER + r * Math.cos(a), y: CENTER + r * Math.sin(a) });
  });
  ring(inner, SIZE * 0.26, 0);
  ring(outer, SIZE * 0.43, Math.PI / Math.max(outer.length, 1));
  return pos;
}

/** The pattern drawn as a graph: members, the shared values linking them, and its links. */
export function PatternGraphCanvas({ graph, onNodeClick }: {
  readonly graph: PatternGraphView;
  readonly onNodeClick?: (nodeId: string) => void;
}) {
  const pos = layout(graph);
  return (
    <figure className="flex flex-col gap-2" data-testid="pattern-graph-canvas">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={`Graph of ${graph.title ?? 'pattern'}`} className="w-full max-w-[460px] self-center">
        {graph.edges.map((e, i) => {
          const a = pos.get(e.source);
          const b = pos.get(e.target);
          if (!a || !b) return null;
          return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--ae-edge)" strokeWidth={1} />;
        })}
        {graph.nodes.map(n => {
          const p = pos.get(n.id);
          if (!p) return null;
          const r = n.role === 'pattern' ? 13 : n.role === 'member' ? 7 : 5;
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} style={{ cursor: onNodeClick && n.role === 'member' ? 'pointer' : 'default' }}
              onClick={() => n.role === 'member' && onNodeClick?.(n.id)}>
              <circle r={r} fill={ROLE_COLOR[n.role] ?? 'var(--ae-mute)'} />
              <title>{`${n.kind}: ${n.label}`}</title>
              {(n.role === 'pattern' || graph.nodes.length <= 40) && (
                <text y={r + 11} textAnchor="middle" fontSize={9} fill="currentColor">{n.label.slice(0, 18)}</text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="flex flex-wrap gap-3 text-[11px]" style={{ color: 'var(--ae-mute)' }}>
        <span>{graph.nodes.filter(n => n.role === 'member').length} members</span>
        <span>{graph.nodes.filter(n => n.role === 'attribute').length} shared values</span>
        <span>{graph.edges.length} links</span>
        {graph.truncated && <span>· truncated</span>}
      </figcaption>
    </figure>
  );
}
