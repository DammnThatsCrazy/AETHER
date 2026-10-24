import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { GraphNode } from '@aether-app/components/graph/graph-canvas';
import { Eyebrow, InlineNotice, LinkButton, Panel, Spinner, TonePill } from '@aether-app/components/ae-ui';
import {
  FLOW_COLUMNS,
  LENSES,
  buildFlow,
  buildPlaces,
  defaultLens,
  flowColumn,
  formatMeasure,
  indexGraph,
  lensMeasure,
  lensRows,
  nodePlace,
  objectLinks,
  type GraphIndex,
  type GraphSnapshot,
  type LensId,
} from './explore-model';
import { scopeSnapshot } from './explore-network';
import { GraphFlow, GraphGlobe, PlaceList, ReplayBar } from './explore-visuals';

/**
 * Graph trace (Claude Design handoff: Aether Graph Trace), opened from the
 * Graph page with `?view=trace`. With `entity` in the URL the trace is scoped
 * to that object's neighbourhood (two hops), which is how "Open in Graph"
 * links from a profile, journey or episode land on a trace of what happened
 * around it. The flow, globe, lenses and replay are all drawn from the page's
 * one graph read — never from a second request or from illustrative data.
 */

const mute = { color: 'var(--ae-mute)' } as const;

// ── Lens chips ──────────────────────────────────────────────────────────────

function LensChips({ index, lens, onLens }: { readonly index: GraphIndex; readonly lens: LensId; readonly onLens: (lens: LensId) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Graph lens">
      <Eyebrow className="mr-1">Lens</Eyebrow>
      {LENSES.map(l => {
        const availability = index.lenses[l.id];
        const on = lens === l.id;
        return (
          <button
            key={l.id}
            type="button"
            aria-pressed={on}
            disabled={!availability.available}
            title={availability.reason ?? l.note}
            onClick={() => onLens(l.id)}
            data-lens={l.id}
            data-lens-state={availability.available ? 'available' : 'unavailable'}
            className="ae-focus inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] disabled:cursor-not-allowed disabled:opacity-45"
            style={{
              background: on ? 'var(--ae-chip-on)' : 'transparent',
              color: on ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)',
              borderColor: on ? 'var(--ae-chip-on)' : 'var(--ae-edge)',
            }}
          >
            <span aria-hidden="true" className="h-[7px] w-[7px] rounded-full" style={{ background: l.color }} />
            {l.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Side panels ─────────────────────────────────────────────────────────────

const LENS_TITLES: Record<LensId, { readonly title: string; readonly sub: string }> = {
  value: { title: 'Value by object', sub: 'Value reported on objects, or carried by their links.' },
  activity: { title: 'Most connected', sub: 'Objects with the most relationships in this read.' },
  authority: { title: 'Authority in this read', sub: 'Who delegates, approves or deploys, and who acts for them.' },
  risk: { title: 'Highest risk', sub: 'Risk scores reported by the graph.' },
  time: { title: 'When each part appeared', sub: 'Earliest first. Use the replay to step through.' },
};

function LensPanel({
  snapshot,
  index,
  lens,
  selectedId,
  onSelect,
}: {
  readonly snapshot: GraphSnapshot;
  readonly index: GraphIndex;
  readonly lens: LensId;
  readonly selectedId: string | null;
  readonly onSelect: (node: GraphNode) => void;
}) {
  const rows = useMemo(() => lensRows(snapshot, index, lens), [snapshot, index, lens]);
  const meta = LENS_TITLES[lens];
  const color = LENSES.find(l => l.id === lens)?.color ?? 'var(--ae-blue)';
  return (
    <Panel className="flex flex-col gap-2 p-4">
      <span className="flex flex-col gap-0.5" data-testid="graph-lens-panel">
        <Eyebrow>{meta.title}</Eyebrow>
        <span className="text-[12px]" style={mute}>{meta.sub}</span>
      </span>
      {snapshot.status !== 'ready' ? (
        <span className="text-[12px]" style={mute}>{snapshot.status === 'error' ? 'Unavailable while the graph read is failing.' : 'Waiting for the graph read…'}</span>
      ) : rows.length === 0 ? (
        <span className="text-[12px]" style={mute}>{index.lenses[lens].reason ?? 'Nothing to rank under this lens yet.'}</span>
      ) : (
        <ul className="flex flex-col">
          {rows.map(row => (
            <li key={row.id}>
              <button
                type="button"
                onClick={() => {
                  const node = index.byId.get(row.id);
                  if (node) onSelect(node);
                }}
                className="ae-focus flex w-full flex-col gap-1 rounded-xl px-2 py-1.5 text-left"
                style={{ background: row.id === selectedId ? 'var(--ae-blue-tint)' : 'transparent' }}
              >
                <span className="flex items-center justify-between gap-2 text-[13px]">
                  <span className="truncate">{row.label}</span>
                  <span className="ae-mono flex-none text-[12px]" style={mute}>{row.value}</span>
                </span>
                <span className="block h-[5px] overflow-hidden rounded-full" style={{ background: 'var(--ae-edge-soft)' }}>
                  <span className="block h-full rounded-full" style={{ width: `${row.share}%`, background: color }} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function SelectedPanel({
  node,
  snapshot,
  index,
  lens,
  onFocus,
}: {
  readonly node: GraphNode | null;
  readonly snapshot: GraphSnapshot;
  readonly index: GraphIndex;
  readonly lens: LensId;
  readonly onFocus: (node: GraphNode) => void;
}) {
  const navigate = useNavigate();
  if (!node) {
    return (
      <Panel className="flex flex-col gap-1 p-4">
        <Eyebrow>Selected</Eyebrow>
        <span className="text-[12px]" style={mute}>Select an object in the flow, a lens row or a place to see what it is connected to.</span>
      </Panel>
    );
  }
  const place = nodePlace(node);
  const relations = snapshot.edges.filter(e => e.source === node.id || e.target === node.id);
  const relationTypes = [...new Set(relations.map(e => e.relationType.replace(/_/g, ' ').toLowerCase()))].slice(0, 4);
  const column = FLOW_COLUMNS.find(c => c.id === flowColumn(node.kind))?.label ?? '';
  const rows: Array<[string, string]> = [
    ['Kind', node.kind],
    ['Lane', column],
    ['Relationships', String(relations.length)],
    ['Place', place.label ?? (place.lat !== null ? `${place.lat.toFixed(2)}, ${place.lng!.toFixed(2)}` : 'Not reported')],
    [LENSES.find(l => l.id === lens)!.label, formatMeasure(lens, lensMeasure(lens, node, index))],
  ];
  if (typeof node.trustScore === 'number') rows.push(['Trust', node.trustScore.toFixed(2)]);
  if (typeof node.riskScore === 'number' && lens !== 'risk') rows.push(['Risk', node.riskScore.toFixed(2)]);
  const links = objectLinks(node, snapshot.clusters);
  return (
    <Panel className="flex flex-col gap-2 p-4">
      <span className="flex flex-col gap-0.5" data-testid="graph-selected-panel">
        <Eyebrow>Selected · {node.kind}</Eyebrow>
        <span className="truncate text-[16px] font-medium">{node.label}</span>
        <span className="ae-mono truncate text-[11px]" style={mute}>{node.id}</span>
      </span>
      <dl className="flex flex-col">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-3 border-t py-1.5 text-[13px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>
            <dt style={mute}>{k}</dt>
            <dd className="truncate text-right">{v}</dd>
          </div>
        ))}
      </dl>
      {relationTypes.length > 0 && (
        <span className="flex flex-wrap gap-1">
          {relationTypes.map(t => <TonePill key={t} tone="blue">{t}</TonePill>)}
        </span>
      )}
      <span className="flex flex-wrap gap-x-3 gap-y-1 pt-1">
        <LinkButton onClick={() => onFocus(node)}>Show in graph</LinkButton>
        {links.map(l => (
          <LinkButton key={l.to} onClick={() => navigate(l.to)}>{l.label} →</LinkButton>
        ))}
      </span>
    </Panel>
  );
}

function PlaceDetail({ placeKey, snapshot, index, onSelect }: {
  readonly placeKey: string;
  readonly snapshot: GraphSnapshot;
  readonly index: GraphIndex;
  readonly onSelect: (node: GraphNode) => void;
}) {
  const place = useMemo(() => buildPlaces(snapshot.nodes).places.find(p => p.key === placeKey) ?? null, [snapshot.nodes, placeKey]);
  if (!place) return null;
  const nodes = place.nodeIds.map(id => index.byId.get(id)).filter((n): n is GraphNode => Boolean(n));
  return (
    <Panel className="flex flex-col gap-2 p-4">
      <span className="flex flex-col gap-0.5" data-testid="graph-place-panel">
        <Eyebrow>Place</Eyebrow>
        <span className="text-[16px] font-medium">{place.label}</span>
        <span className="text-[12px]" style={mute}>
          {nodes.length} object{nodes.length === 1 ? '' : 's'} in this read{place.lat === null ? ' · no coordinates reported' : ''}
        </span>
      </span>
      <ul className="flex flex-col">
        {nodes.slice(0, 8).map(n => (
          <li key={n.id}>
            <button type="button" onClick={() => onSelect(n)} className="ae-focus flex w-full items-center justify-between gap-2 border-t py-1.5 text-left text-[13px]" style={{ borderColor: 'var(--ae-edge-soft)' }}>
              <span className="truncate">{n.label}</span>
              <span className="flex-none text-[11px]" style={mute}>{n.kind}</span>
            </button>
          </li>
        ))}
      </ul>
      {nodes.length > 8 && <span className="text-[12px]" style={mute}>{nodes.length - 8} more in this place.</span>}
    </Panel>
  );
}

// ── Trace ───────────────────────────────────────────────────────────────────

export type TraceVisual = 'globe' | 'flow' | 'both';

const TRACE_VISUALS: ReadonlyArray<{ readonly id: TraceVisual; readonly label: string }> = [
  { id: 'globe', label: 'Globe' },
  { id: 'flow', label: 'Network flow' },
  { id: 'both', label: 'Both' },
];

/** Objects within this many hops of the scoped object make up its trace. */
export const TRACE_HOPS = 2;

export function ExploreTraceView({
  snapshot: fullSnapshot,
  scopeId,
  visual,
  onVisual,
  onBack,
  onShowInGraph,
}: {
  readonly snapshot: GraphSnapshot;
  readonly scopeId: string | null;
  readonly visual: TraceVisual;
  readonly onVisual: (visual: TraceVisual) => void;
  readonly onBack: () => void;
  readonly onShowInGraph: (node: GraphNode) => void;
}) {
  const navigate = useNavigate();
  const snapshot = useMemo(() => scopeSnapshot(fullSnapshot, scopeId, TRACE_HOPS), [fullSnapshot, scopeId]);
  const scopeNode = scopeId ? fullSnapshot.nodes.find(n => n.id === scopeId) ?? null : null;
  const index = useMemo(() => indexGraph(snapshot), [snapshot]);
  const [lensChoice, setLensChoice] = useState<LensId | null>(null);
  const lens: LensId = lensChoice && index.lenses[lensChoice].available ? lensChoice : defaultLens(index);
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [selectedPlace, setSelectedPlace] = useState<string | null>(null);

  // Replay over the read's own timestamps (null cutoff = everything shown).
  const [cutoff, setCutoff] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const range = index.timeRange;
  useEffect(() => {
    if (!playing || !range) return;
    const span = Math.max(1, range[1] - range[0]);
    const id = window.setInterval(() => {
      setCutoff(prev => Math.min(range[1], (prev === null || prev >= range[1] ? range[0] : prev) + (span / 240) * speed));
    }, 50);
    return () => window.clearInterval(id);
  }, [playing, range, speed]);
  useEffect(() => {
    if (playing && range && cutoff !== null && cutoff >= range[1]) setPlaying(false);
  }, [playing, range, cutoff]);
  const activeCutoff = range && cutoff !== null ? cutoff : null;

  const pickNode = (node: GraphNode) => {
    setPickedId(node.id);
    setSelectedPlace(null);
  };

  const selectedNode = index.byId.get(pickedId ?? scopeId ?? '') ?? null;
  const flow = useMemo(() => buildFlow(snapshot, index, lens, { cutoff: activeCutoff }), [snapshot, index, lens, activeCutoff]);
  const places = useMemo(() => buildPlaces(snapshot.nodes), [snapshot.nodes]);
  const timedTotal = index.time.size;
  const timedShown = activeCutoff === null ? timedTotal : [...index.time.values()].filter(t => t <= activeCutoff).length;
  const unavailableLenses = LENSES.filter(l => !index.lenses[l.id].available);

  const globe = (
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_220px]">
      <GraphGlobe
        places={places.places}
        unknown={places.unknown}
        edges={snapshot.edges}
        cutoff={activeCutoff}
        selectedPlace={selectedPlace}
        onSelectPlace={setSelectedPlace}
      />
      <div className="flex flex-col gap-1">
        <Eyebrow>Places</Eyebrow>
        <PlaceList places={places.places} selectedPlace={selectedPlace} onSelectPlace={setSelectedPlace} />
      </div>
    </div>
  );
  const flowView = <GraphFlow layout={flow} lens={lens} index={index} selectedId={selectedNode?.id ?? null} onSelect={pickNode} />;

  let body: ReactNode;
  if (snapshot.status === 'loading') {
    body = (
      <div className="flex min-h-[260px] flex-col items-center justify-center gap-3" data-testid="graph-visual-loading">
        <Spinner />
        <span className="text-[13px]" style={mute}>Reading the graph…</span>
      </div>
    );
  } else if (snapshot.status === 'error') {
    body = (
      <div data-testid="graph-visual-error">
        <InlineNotice tone="ember">The graph read failed, so the flow and globe are unavailable. The advanced explorer shows the error.</InlineNotice>
      </div>
    );
  } else if (snapshot.nodes.length === 0) {
    body = (
      <div className="flex min-h-[220px] flex-col items-center justify-center gap-2 text-center" data-testid="graph-visual-empty">
        <span className="text-[15px] font-medium">No objects in this graph read yet</span>
        <span className="max-w-[420px] text-[13px]" style={mute}>Objects and relationships appear here once a connected source or SDK sends events.</span>
        <LinkButton onClick={() => navigate('/activation')}>Connect a source →</LinkButton>
      </div>
    );
  } else if (visual === 'flow') {
    body = flowView;
  } else if (visual === 'globe') {
    body = globe;
  } else {
    body = <div className="flex flex-col gap-5">{globe}{flowView}</div>;
  }

  const title = scopeNode ? `${scopeNode.label} · trace` : 'Graph trace';
  const sub = snapshot.status === 'ready'
    ? `${snapshot.nodes.length} object${snapshot.nodes.length === 1 ? '' : 's'} and ${snapshot.edges.length} link${snapshot.edges.length === 1 ? '' : 's'}${scopeNode ? ` within ${TRACE_HOPS} hops` : ' in this read'} · what it was, who was involved and where`
    : 'What it was, who was involved and where';

  return (
    <div data-testid="explore-trace" className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <button type="button" onClick={onBack} className="ae-focus self-start text-[12px] hover:underline" style={mute}>← Back to graph</button>
          <Eyebrow>Graph · Trace</Eyebrow>
          <h1 className="truncate text-[28px] font-medium leading-tight tracking-[-0.56px]">{title}</h1>
          <span className="text-[14px]" style={mute} data-testid="graph-trace-sub">{sub}</span>
        </div>
        <span className="inline-flex gap-0.5 rounded-full p-[3px]" style={{ background: 'var(--ae-edge-soft)' }} role="group" aria-label="Trace view">
          {TRACE_VISUALS.map(v => (
            <button
              key={v.id}
              type="button"
              aria-pressed={visual === v.id}
              onClick={() => onVisual(v.id)}
              className="ae-focus rounded-full px-3.5 py-1.5 text-[13px]"
              style={{ background: visual === v.id ? 'var(--ae-chip-on)' : 'transparent', color: visual === v.id ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)' }}
            >
              {v.label}
            </button>
          ))}
        </span>
      </div>

      <div className="flex flex-col gap-1.5">
        <LensChips index={index} lens={lens} onLens={setLensChoice} />
        <span className="text-[12px]" style={mute} data-testid="graph-lens-note">
          {LENSES.find(l => l.id === lens)!.note} A lens changes how the graph reads, not the objects in it.
          {snapshot.status === 'ready' && unavailableLenses.length > 0 && (
            <> Not in this read: {unavailableLenses.map(l => l.label).join(', ')}.</>
          )}
        </span>
      </div>

      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Panel className="flex min-w-0 flex-col gap-3 p-4">
          <Eyebrow>{visual === 'flow' ? 'Who and what is involved' : visual === 'globe' ? 'Where it happened' : 'Where it happened and who was involved'}</Eyebrow>
          {body}
          {snapshot.status === 'ready' && snapshot.nodes.length > 0 && (
            range ? (
              <ReplayBar
                range={range}
                cutoff={activeCutoff ?? range[1]}
                onScrub={(value) => { setPlaying(false); setCutoff(value); }}
                playing={playing}
                onTogglePlay={() => {
                  if (!playing && (cutoff === null || cutoff >= range[1])) setCutoff(range[0]);
                  setPlaying(p => !p);
                }}
                speed={speed}
                onSpeed={setSpeed}
                shown={timedShown}
                total={timedTotal}
              />
            ) : (
              <span className="text-[12px]" style={mute} data-testid="graph-replay-unavailable">
                Replay needs timestamped objects or links; this read carries none. Use “As of” in the advanced explorer for a point-in-time graph.
              </span>
            )
          )}
        </Panel>
        <div className="flex min-w-0 flex-col gap-4">
          <LensPanel snapshot={snapshot} index={index} lens={lens} selectedId={selectedNode?.id ?? null} onSelect={pickNode} />
          {visual !== 'flow' && selectedPlace ? (
            <PlaceDetail placeKey={selectedPlace} snapshot={snapshot} index={index} onSelect={pickNode} />
          ) : (
            <SelectedPanel node={selectedNode} snapshot={snapshot} index={index} lens={lens} onFocus={onShowInGraph} />
          )}
        </div>
      </div>
    </div>
  );
}

