import { useMemo } from 'react';
import { cn } from '@aether/ui';
import { Eyebrow } from '@aether-app/components/ae-ui';
import type { GraphEdge, GraphNode } from '@aether-app/components/graph/graph-canvas';
import {
  edgeTime,
  edgeValue,
  formatMeasure,
  lensMeasure,
  type FlowColumnId,
  type FlowLayout,
  type FlowNode,
  type GraphIndex,
  type LensId,
  type Place,
} from './explore-model';
import { landDots, makeProjection } from './globe-geometry';

const COLUMN_COLOR: Record<FlowColumnId, string> = {
  sources: 'var(--ae-mute)',
  people: 'var(--ae-blue)',
  agents: 'var(--ae-violet)',
  destinations: 'var(--ae-amber)',
};

function riskColor(score: number): string {
  if (score >= 0.7) return 'var(--ae-ember)';
  if (score >= 0.4) return 'var(--ae-amber)';
  return 'var(--ae-sage)';
}

/** Marker colour for an object under a lens; falls back to its lane colour. */
export function markerColor(lens: LensId, node: GraphNode, column: FlowColumnId, index: GraphIndex): string {
  if (lens === 'risk') return typeof node.riskScore === 'number' ? riskColor(node.riskScore) : 'var(--ae-faint)';
  if (lens === 'authority') return (index.authority.get(node.id) ?? 0) > 0 ? 'var(--ae-violet)' : 'var(--ae-faint)';
  if (lens === 'value') return index.value.has(node.id) ? 'var(--ae-sage)' : 'var(--ae-faint)';
  if (lens === 'time') return index.time.has(node.id) ? 'var(--ae-teal)' : 'var(--ae-faint)';
  return COLUMN_COLOR[column];
}

// ── Flow ────────────────────────────────────────────────────────────────────

export function GraphFlow({
  layout,
  lens,
  index,
  selectedId,
  onSelect,
}: {
  readonly layout: FlowLayout;
  readonly lens: LensId;
  readonly index: GraphIndex;
  readonly selectedId: string | null;
  readonly onSelect: (node: GraphNode) => void;
}) {
  const height = Math.max(300, layout.rows * 58 + 70);
  const related = useMemo(() => {
    if (!selectedId) return null;
    return new Set(layout.links.filter(l => l.source === selectedId || l.target === selectedId).map(l => l.id));
  }, [layout.links, selectedId]);

  return (
    <div className="flex flex-col gap-2" data-testid="graph-flow">
      <div className="grid grid-cols-4 gap-1 text-center">
        {layout.columns.map(col => (
          <span key={col.id} className="flex flex-col leading-tight" data-flow-column={col.id}>
            <span className="truncate text-[11px] font-medium uppercase tracking-[0.04em]" style={{ color: 'var(--ae-mute)' }}>{col.label}</span>
            <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-faint)' }}>
              {col.total}{col.hidden > 0 ? ` · ${col.hidden} not shown` : ''}
            </span>
          </span>
        ))}
      </div>
      <div className="relative w-full overflow-hidden rounded-2xl" style={{ height, background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
          {layout.links.map(link => {
            const isRelated = related?.has(link.id) ?? false;
            const stroke = lens === 'authority' && link.authority ? 'var(--ae-violet)' : 'var(--ae-blue)';
            const opacity = link.pending ? 0.1 : related ? (isRelated ? 0.9 : 0.15) : 0.45;
            return (
              <path
                key={link.id}
                d={link.path}
                fill="none"
                stroke={stroke}
                strokeOpacity={opacity}
                strokeWidth={lens === 'authority' && link.authority ? 2.2 : isRelated ? 2 : 1.3}
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
        </svg>
        {related && layout.links.filter(l => related.has(l.id)).map(link => (
          <span
            key={`label-${link.id}`}
            className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full px-1.5 py-px text-[10px]"
            style={{ left: `${link.mid.x}%`, top: `${link.mid.y}%`, background: 'var(--ae-raised)', border: '1px solid var(--ae-edge-soft)', color: 'var(--ae-mute)' }}
          >
            {[...new Set(link.edges.map(e => e.relationType.replace(/_/g, ' ').toLowerCase()))].join(' · ')}
          </span>
        ))}
        {layout.nodes.map(item => (
          <FlowPill key={item.node.id} item={item} lens={lens} index={index} selected={item.node.id === selectedId} dimmed={Boolean(selectedId) && item.node.id !== selectedId} onSelect={onSelect} />
        ))}
      </div>
      <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
        Left to right: where it came from, who acted, what acted for them, where it ended up. Select an object to label its links.
      </span>
    </div>
  );
}

function FlowPill({
  item,
  lens,
  index,
  selected,
  dimmed,
  onSelect,
}: {
  readonly item: FlowNode;
  readonly lens: LensId;
  readonly index: GraphIndex;
  readonly selected: boolean;
  readonly dimmed: boolean;
  readonly onSelect: (node: GraphNode) => void;
}) {
  const color = markerColor(lens, item.node, item.column, index);
  const dot = 7 + Math.round(item.weight * 7);
  const timeShade = lens === 'time' && item.measure !== null ? 0.4 + item.weight * 0.6 : 1;
  return (
    <button
      type="button"
      onClick={() => onSelect(item.node)}
      aria-pressed={selected}
      data-flow-node={item.node.id}
      title={`${item.node.label} · ${item.node.kind} · ${formatMeasure(lens, lensMeasure(lens, item.node, index))}`}
      className="ae-focus absolute flex max-w-[23%] -translate-x-1/2 -translate-y-1/2 items-center gap-1.5 rounded-full px-2 py-1 text-left text-[12px] transition-opacity"
      style={{
        left: `${item.x}%`,
        top: `${item.y}%`,
        background: selected ? 'var(--ae-chip-on)' : 'var(--ae-raised)',
        color: selected ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)',
        border: `1px solid ${selected ? 'var(--ae-chip-on)' : 'var(--ae-edge)'}`,
        boxShadow: selected ? '0 0 0 3px var(--ae-blue-tint)' : 'var(--ae-lift)',
        opacity: item.pending ? 0.3 : dimmed ? 0.6 : 1,
      }}
    >
      <span aria-hidden="true" className="flex-none rounded-full" style={{ width: dot, height: dot, background: color, opacity: timeShade }} />
      <span className="truncate">{item.node.label}</span>
    </button>
  );
}

// ── Globe ───────────────────────────────────────────────────────────────────

export function GraphGlobe({
  places,
  unknown,
  edges = [],
  cutoff = null,
  selectedPlace,
  onSelectPlace,
}: {
  readonly places: readonly Place[];
  readonly unknown: number;
  /** Links in the read; those joining two located places are drawn as arcs. */
  readonly edges?: readonly GraphEdge[];
  /** Replay cutoff: arcs first observed after it are faded. */
  readonly cutoff?: number | null;
  readonly selectedPlace: string | null;
  readonly onSelectPlace: (key: string) => void;
}) {
  const located = useMemo(
    () => places.filter((p): p is Place & { lat: number; lng: number } => p.lat !== null && p.lng !== null),
    [places],
  );
  const center = useMemo(() => {
    if (!located.length) return { lon: -40, lat: 30 };
    const lats = located.map(p => p.lat);
    return { lon: circularMeanLongitude(located.map(p => p.lng)), lat: (Math.min(...lats) + Math.max(...lats)) / 2 };
  }, [located]);
  const project = useMemo(() => makeProjection(center.lon, center.lat), [center]);
  const dots = useMemo(
    () => landDots().map(([lon, lat]) => project(lat, lon)).filter(p => p.visible),
    [project],
  );
  const arcs = useMemo(() => placeArcs(located, edges), [located, edges]);
  const maxCount = Math.max(1, ...located.map(p => p.nodeIds.length));
  const maxArc = Math.max(1, ...arcs.map(a => a.count));

  // Markers first, then labels placed greedily (biggest place first, the
  // selected one always) so no two labels overlap.
  const markers = located
    .map(place => ({ place, p: project(place.lat, place.lng), size: 1.6 + (place.nodeIds.length / maxCount) * 2.4 }))
    .filter(m => m.p.visible);
  const labels = placeLabels(markers, selectedPlace);

  return (
    <div className="flex flex-col gap-2" data-testid="graph-globe">
      <div className="mx-auto w-full max-w-[460px]">
        <svg viewBox="0 0 100 100" className="block h-auto w-full" role="img" aria-label={`Globe with ${located.length} located place${located.length === 1 ? '' : 's'} and ${arcs.length} link${arcs.length === 1 ? '' : 's'} between places`}>
          <circle cx="50" cy="50" r="44.4" fill="var(--ae-blue-tint)" fillOpacity={0.5} stroke="var(--ae-blue)" strokeOpacity={0.25} strokeWidth={0.3} />
          {dots.map((d, i) => (
            <circle key={i} cx={d.x.toFixed(2)} cy={d.y.toFixed(2)} r={0.42} fill="var(--ae-mute)" opacity={0.4} />
          ))}
          {arcs.map(arc => {
            const d = arcPath(arc.from, arc.to, project);
            if (!d) return null;
            const touchesSelected = selectedPlace !== null && (arc.from.key === selectedPlace || arc.to.key === selectedPlace);
            const pending = cutoff !== null && arc.firstObserved !== null && arc.firstObserved > cutoff;
            return (
              <path
                key={arc.id}
                d={d}
                data-globe-arc={arc.id}
                fill="none"
                stroke={arc.value ? 'var(--ae-sage)' : 'var(--ae-blue)'}
                strokeWidth={0.5 + (arc.count / maxArc) * 0.9}
                strokeOpacity={pending ? 0.12 : selectedPlace === null || touchesSelected ? 0.85 : 0.25}
                strokeLinecap="round"
              />
            );
          })}
          {markers.map(({ place, p, size }) => {
            const selected = place.key === selectedPlace;
            const color = selected ? 'var(--ae-ink)' : 'var(--ae-blue)';
            const label = labels.get(place.key);
            return (
              <g key={place.key} onClick={() => onSelectPlace(place.key)} style={{ cursor: 'pointer' }} data-globe-place={place.key}>
                <circle cx={p.x} cy={p.y} r={size + 1} fill={color} fillOpacity={0.22} stroke={color} strokeWidth={0.4} />
                <circle cx={p.x} cy={p.y} r={0.9} fill={color} />
                {label && (
                  <text
                    x={label.x}
                    y={label.y}
                    fontSize={2.4}
                    textAnchor={label.anchor}
                    fill="var(--ae-ink)"
                    stroke="var(--ae-raised)"
                    strokeWidth={0.7}
                    paintOrder="stroke"
                  >
                    {label.text}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      {located.length === 0 && (
        <span className="text-center text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          No object in this graph read carries coordinates, so nothing is pinned on the globe.
        </span>
      )}
      {unknown > 0 && (
        <span className="text-center text-[12px]" style={{ color: 'var(--ae-mute)' }} data-testid="graph-globe-unknown">
          Location not reported for {unknown} object{unknown === 1 ? '' : 's'}. Not counted as any place.
        </span>
      )}
    </div>
  );
}

export function PlaceList({
  places,
  selectedPlace,
  onSelectPlace,
}: {
  readonly places: readonly Place[];
  readonly selectedPlace: string | null;
  readonly onSelectPlace: (key: string) => void;
}) {
  if (places.length === 0) {
    return (
      <p className="text-[12px]" style={{ color: 'var(--ae-mute)' }} data-testid="graph-places-empty">
        No object in this graph read reports a place.
      </p>
    );
  }
  const max = Math.max(...places.map(p => p.nodeIds.length));
  return (
    <ul className="flex flex-col" aria-label="Places in this graph read" data-testid="graph-places">
      {places.slice(0, 8).map(place => (
        <li key={place.key}>
          <button
            type="button"
            onClick={() => onSelectPlace(place.key)}
            aria-pressed={place.key === selectedPlace}
            className={cn('ae-focus flex w-full flex-col gap-1 rounded-xl px-2 py-2 text-left')}
            style={{ background: place.key === selectedPlace ? 'var(--ae-blue-tint)' : 'transparent' }}
          >
            <span className="flex items-center justify-between gap-2 text-[13px]">
              <span className="truncate">{place.label}</span>
              <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-mute)' }}>{place.nodeIds.length}</span>
            </span>
            <span className="block h-[5px] overflow-hidden rounded-full" style={{ background: 'var(--ae-edge-soft)' }}>
              <span className="block h-full rounded-full" style={{ width: `${(place.nodeIds.length / max) * 100}%`, background: 'var(--ae-blue)' }} />
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

// ── Replay ──────────────────────────────────────────────────────────────────

export const REPLAY_SPEEDS = [1, 4, 16] as const;

export function ReplayBar({
  range,
  cutoff,
  onScrub,
  playing,
  onTogglePlay,
  speed,
  onSpeed,
  shown,
  total,
}: {
  readonly range: readonly [number, number];
  readonly cutoff: number;
  readonly onScrub: (value: number) => void;
  readonly playing: boolean;
  readonly onTogglePlay: () => void;
  readonly speed: number;
  readonly onSpeed: (speed: number) => void;
  readonly shown: number;
  readonly total: number;
}) {
  const [start, end] = range;
  const day = (t: number) => new Date(t).toISOString().slice(0, 10);
  return (
    <div className="flex flex-col gap-2" data-testid="graph-replay">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5">
          <button type="button" onClick={onTogglePlay} className="ae-btn-secondary ae-focus px-3 py-1 text-[12px]">
            {playing ? 'Pause' : 'Play'}
          </button>
          {REPLAY_SPEEDS.map(s => (
            <button
              key={s}
              type="button"
              aria-pressed={speed === s}
              onClick={() => onSpeed(s)}
              className="ae-focus rounded-full border px-2 py-0.5 text-[11px]"
              style={{
                background: speed === s ? 'var(--ae-chip-on)' : 'transparent',
                color: speed === s ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)',
                borderColor: speed === s ? 'var(--ae-chip-on)' : 'var(--ae-edge)',
              }}
            >
              {s}x
            </button>
          ))}
        </span>
        <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>
          {day(cutoff)} · {shown} of {total} timed objects so far
        </span>
      </div>
      <input
        type="range"
        min={start}
        max={end}
        step={Math.max(1, Math.round((end - start) / 200))}
        value={cutoff}
        onChange={e => onScrub(Number(e.target.value))}
        aria-label="Replay position"
        className="w-full"
        style={{ accentColor: 'var(--ae-blue)' }}
      />
      <span className="flex justify-between">
        <Eyebrow>{day(start)}</Eyebrow>
        <Eyebrow>{day(end)}</Eyebrow>
      </span>
    </div>
  );
}

// ── Globe arcs and labels ───────────────────────────────────────────────────

type LocatedPlace = Place & { readonly lat: number; readonly lng: number };

export interface PlaceArc {
  readonly id: string;
  readonly from: LocatedPlace;
  readonly to: LocatedPlace;
  /** Links in the read joining the two places. */
  readonly count: number;
  /** Value carried by those links, when any reports one. */
  readonly value: number | null;
  readonly firstObserved: number | null;
}

/** Links whose two ends sit in two different located places, merged per pair of places. */
export function placeArcs(located: readonly LocatedPlace[], edges: readonly GraphEdge[]): PlaceArc[] {
  const placeOf = new Map<string, LocatedPlace>();
  for (const place of located) for (const id of place.nodeIds) placeOf.set(id, place);
  const arcs = new Map<string, { from: LocatedPlace; to: LocatedPlace; count: number; value: number | null; first: number | null }>();
  for (const edge of edges) {
    const a = placeOf.get(edge.source);
    const b = placeOf.get(edge.target);
    if (!a || !b || a.key === b.key) continue;
    const key = [a.key, b.key].sort().join(' ↔ ');
    const v = edgeValue(edge);
    const t = edgeTime(edge);
    const entry = arcs.get(key);
    if (entry) {
      entry.count += 1;
      if (v !== null) entry.value = (entry.value ?? 0) + v;
      if (t !== null && (entry.first === null || t < entry.first)) entry.first = t;
    } else {
      arcs.set(key, { from: a, to: b, count: 1, value: v, first: t });
    }
  }
  return [...arcs.entries()].map(([id, e]) => ({ id, from: e.from, to: e.to, count: e.count, value: e.value, firstObserved: e.first }));
}

const DEG = Math.PI / 180;

/** Great-circle arc lifted off the surface; hidden stretches (far side) are skipped. */
function arcPath(from: LocatedPlace, to: LocatedPlace, project: ReturnType<typeof makeProjection>): string | null {
  const v = (lat: number, lng: number) => [Math.cos(lat * DEG) * Math.cos(lng * DEG), Math.cos(lat * DEG) * Math.sin(lng * DEG), Math.sin(lat * DEG)] as const;
  const a = v(from.lat, from.lng);
  const b = v(to.lat, to.lng);
  const omega = Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2])));
  if (omega < 1e-6) return null;
  const steps = 28;
  let d = '';
  let pen = false;
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const s1 = Math.sin((1 - t) * omega) / Math.sin(omega);
    const s2 = Math.sin(t * omega) / Math.sin(omega);
    const x = s1 * a[0] + s2 * b[0];
    const y = s1 * a[1] + s2 * b[1];
    const z = s1 * a[2] + s2 * b[2];
    const lat = Math.atan2(z, Math.hypot(x, y)) / DEG;
    const lng = Math.atan2(y, x) / DEG;
    const p = project(lat, lng, 1 + Math.sin(Math.PI * t) * Math.min(0.18, omega * 0.12));
    if (!p.visible) { pen = false; continue; }
    d += `${pen ? 'L' : 'M'}${p.x.toFixed(2)} ${p.y.toFixed(2)} `;
    pen = true;
  }
  return d.trim() || null;
}

interface PlaceLabel {
  readonly x: number;
  readonly y: number;
  readonly anchor: 'start' | 'middle' | 'end';
  readonly text: string;
}

/**
 * Greedy label placement for globe markers: the selected place first, then the
 * largest; each tries right, left, above and below its marker and is dropped
 * (still listed beside the globe) when every slot would overlap another label.
 */
export function placeLabels(
  markers: ReadonlyArray<{ readonly place: Place; readonly p: { readonly x: number; readonly y: number }; readonly size: number }>,
  selectedPlace: string | null,
): Map<string, PlaceLabel> {
  const order = [...markers].sort((a, b) =>
    (a.place.key === selectedPlace ? -1 : b.place.key === selectedPlace ? 1 : 0) || b.place.nodeIds.length - a.place.nodeIds.length);
  const boxes: Array<{ x0: number; y0: number; x1: number; y1: number }> = [];
  const out = new Map<string, PlaceLabel>();
  for (const { place, p, size } of order) {
    const text = `${place.label.split(',')[0]}${place.nodeIds.length > 1 ? ` · ${place.nodeIds.length}` : ''}`;
    const w = text.length * 1.3;
    const h = 2.8;
    const r = size + 1.4;
    const slots: PlaceLabel[] = [
      { x: p.x + r, y: p.y + 0.85, anchor: 'start', text },
      { x: p.x - r, y: p.y + 0.85, anchor: 'end', text },
      { x: p.x, y: p.y - r, anchor: 'middle', text },
      { x: p.x, y: p.y + r + 2.2, anchor: 'middle', text },
    ];
    for (const slot of slots) {
      const x0 = slot.anchor === 'start' ? slot.x : slot.anchor === 'end' ? slot.x - w : slot.x - w / 2;
      const box = { x0, y0: slot.y - h + 0.6, x1: x0 + w, y1: slot.y + 0.6 };
      if (box.x0 < 0.5 || box.x1 > 99.5 || box.y0 < 0.5 || box.y1 > 99.5) continue;
      if (boxes.some(o => box.x0 < o.x1 && box.x1 > o.x0 && box.y0 < o.y1 && box.y1 > o.y0)) continue;
      boxes.push(box);
      out.set(place.key, slot);
      break;
    }
  }
  return out;
}

/**
 * Mean longitude on the circle, so places either side of the antimeridian
 * (170° and -170°) centre the globe at 180°, not 0°.
 */
export function circularMeanLongitude(lons: readonly number[]): number {
  let x = 0;
  let y = 0;
  for (const lon of lons) {
    const r = (lon * Math.PI) / 180;
    x += Math.cos(r);
    y += Math.sin(r);
  }
  if (Math.abs(x) < 1e-9 && Math.abs(y) < 1e-9) return lons[0] ?? 0;
  return (Math.atan2(y, x) * 180) / Math.PI;
}
