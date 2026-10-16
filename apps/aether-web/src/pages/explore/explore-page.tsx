import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { GraphContext, GraphObjectRef } from '@aether/shared/graph-context-contract';
import {
  GraphTimeRail,
  NoesisContextStrip,
  allBlueprintLenses,
  FilterBar,
  FilterBuilder,
  resolveLensAvailability,
  useExplorationFilters,
  useGraph,
  useGraphActions,
  useGraphContext,
  useGraphHistory,
} from '@aether/ui/exploration';
import { GraphPage, type GraphReadSnapshot } from '@aether-app/pages/graph/graph-page';
import { deriveGraphMaturity, useTenantReadiness } from '@aether-app/features/activation/use-tenant-readiness';
import type { LensResolution } from '@aether/ui/exploration';
import type { GraphEdge, GraphNode } from '@aether-app/components/graph/graph-canvas';
import type { GraphCluster } from '@aether-app/features/graph/use-graph-data';
import { ExploreSnapshotControls } from '@aether-app/features/graph/explore-snapshot-controls';
import { Eyebrow, InlineNotice, LinkButton, Panel, Spinner, TonePill, type Tone } from '@aether-app/components/ae-ui';
import {
  FLOW_COLUMNS,
  LENSES,
  LOADING_SNAPSHOT,
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
import { GraphFlow, GraphGlobe, PlaceList, ReplayBar } from './explore-visuals';

function temporalLabel(context: GraphContext): string {
  const temporal = context.temporal;
  if (temporal.mode === 'as_of') return temporal.as_of ? `As of ${temporal.as_of}` : 'Point-in-time graph';
  if (temporal.mode === 'compare') return temporal.compare_to ? `Compared with ${temporal.compare_to}` : 'Comparison graph';
  if (temporal.mode === 'relative') return `Relative ${temporal.field}`;
  return `Window · ${temporal.field}`;
}

interface ScopeLabels {
  readonly tenant: string;
  readonly workspace: string;
  readonly environment: string;
  readonly account?: string;
  readonly organization?: string;
}

function scopeLabels(context: GraphContext): ScopeLabels {
  const scope = context.scope;
  return {
    tenant: scope.tenant_id,
    workspace: scope.workspace_id,
    environment: scope.environment_id,
    ...(scope.account_id ? { account: scope.account_id } : {}),
    ...(scope.organization_id ? { organization: scope.organization_id } : {}),
  };
}

const mute = { color: 'var(--ae-mute)' } as const;

function ContextPill({ name, value }: { readonly name: string; readonly value: string }) {
  const available = value.trim().length > 0;
  return (
    <span
      className="ae-card inline-flex min-w-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-[12px]"
      data-context-key={name.toLowerCase()}
      data-availability={available ? 'available' : 'unavailable'}
      aria-label={`${name}: ${available ? value : 'Unavailable'}`}
    >
      <span style={mute}>{name}</span>
      <span className="truncate">{available ? value : 'Unavailable'}</span>
    </span>
  );
}

// ── Graph maturity (tenant readiness) ───────────────────────────────────────

function GraphMaturityPanel() {
  const { data, isLoading, error } = useTenantReadiness();

  let tone: Tone = 'mute';
  let label = 'Checking';
  let body: ReactNode;
  if (isLoading && !data) {
    body = <p data-testid="graph-maturity-loading">Checking graph foundations…</p>;
  } else if (error) {
    tone = 'amber';
    label = 'Unavailable';
    body = <p data-testid="graph-maturity-error">Graph foundation readiness could not be checked.</p>;
  } else if (!data) {
    tone = 'amber';
    label = 'Unavailable';
    body = <p data-testid="graph-maturity-unavailable">Graph foundation readiness is unavailable.</p>;
  } else {
    const maturity = deriveGraphMaturity(data);
    if (maturity.state === 'no_data') {
      tone = 'blue';
      label = 'No data yet';
      body = (
        <div data-testid="graph-maturity-no-data" className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p>The graph needs observed events and links before it can mature.</p>
          <Link className="ae-focus hover:underline" style={{ color: 'var(--ae-blue-ink)' }} to="/activate">
            Connect a source in Activation
          </Link>
        </div>
      );
    } else if (maturity.state === 'building') {
      tone = 'amber';
      label = 'Building';
      body = (
        <div data-testid="graph-maturity-building">
          <p>Graph foundations are building — {maturity.blocking.length} check{maturity.blocking.length === 1 ? '' : 's'} still blocking verification.</p>
          <ul className="mt-1 flex flex-wrap gap-1.5" aria-label="Blocking graph foundation checks">
            {maturity.blocking.map((check) => (
              <li key={check} className="ae-mono rounded-full px-2 py-px text-[11px]" style={{ background: 'var(--ae-amber-tint)', color: 'var(--ae-amber)' }}>{check}</li>
            ))}
          </ul>
        </div>
      );
    } else {
      tone = 'sage';
      label = 'Verified';
      body = <p data-testid="graph-maturity-ready">Graph foundations are verified.</p>;
    }
  }

  return (
    <section data-testid="graph-maturity-panel" className="ae-card flex flex-wrap items-start gap-x-3 gap-y-1 rounded-2xl px-4 py-3 text-[13px]">
      <span className="flex items-center gap-2">
        <Eyebrow>Graph maturity</Eyebrow>
        <TonePill tone={tone}>{label}</TonePill>
      </span>
      <div className="min-w-0 flex-1" style={mute}>{body}</div>
    </section>
  );
}

// ── Registered lens registry + query builder ───────────────────────────────

function lensStatusLabel(resolution: LensResolution): string {
  if (resolution.availability === 'available') return 'Available';
  if (resolution.availability === 'not_entitled') return 'Not included';
  if (resolution.availability === 'unauthorized') return 'No access';
  return resolution.entry?.pending ? 'Pending engine binding' : 'Not ready';
}

function lensStatusTone(resolution: LensResolution): Tone {
  if (resolution.availability === 'available') return 'sage';
  if (resolution.availability === 'not_entitled' || resolution.availability === 'unauthorized') return 'mute';
  return 'amber';
}

function RegistryPanel({ objectKind }: { readonly objectKind: string }) {
  const { population, addFilter, removeFilterAt, setPopulation } = useExplorationFilters();
  const resolutions = useMemo(() => allBlueprintLenses().map((lens) => resolveLensAvailability(lens.id, {
    objectKind,
    surfaceId: 'graph',
    // Capability and readiness facts are intentionally absent here: the
    // registry resolver must represent those lenses as not-ready, never infer
    // entitlement from the presence of a UI control.
    temporalMode: 'window',
  })), [objectKind]);
  return (
    <Panel className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="flex flex-col gap-0.5">
          <Eyebrow>Registered lenses</Eyebrow>
          <span className="text-[12px]" style={mute}>Registry availability for this graph context. Unavailable lenses stay visible with their state.</span>
        </span>
        <span className="ae-mono text-[11px]" style={mute} data-testid="lens-object-kind">{objectKind}</span>
      </div>
      <div className="flex flex-col" role="list" aria-label="Registered graph lenses">
        {resolutions.map((resolution) => {
          const entry = resolution.entry;
          if (!entry) return null;
          return (
            <div
              key={resolution.lensId}
              role="listitem"
              data-lens-availability={resolution.availability}
              className="flex items-center justify-between gap-2 border-t py-2 text-[13px]"
              style={{ borderColor: 'var(--ae-edge-soft)' }}
            >
              <span className="truncate">{entry.displayName}</span>
              <TonePill tone={lensStatusTone(resolution)}>{lensStatusLabel(resolution)}</TonePill>
            </div>
          );
        })}
      </div>
      <details className="rounded-xl border" style={{ borderColor: 'var(--ae-edge)' }} data-testid="graph-query-controls">
        <summary className="ae-focus cursor-pointer px-3 py-2 text-[13px] font-medium">Query builder</summary>
        <div className="flex flex-col gap-2 border-t p-3" style={{ borderColor: 'var(--ae-edge-soft)' }}>
          <FilterBar
            population={population}
            onRemove={removeFilterAt}
            onClear={() => setPopulation(null)}
          />
          <FilterBuilder surface="graph" onAdd={addFilter} />
        </div>
      </details>
    </Panel>
  );
}

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
        <span className="text-[12px]" style={mute}>Select an object in the flow, a lens row or the explorer to see what it is connected to.</span>
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
        <LinkButton onClick={() => onFocus(node)}>Focus in graph context</LinkButton>
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
      {nodes.length > 8 && <span className="text-[12px]" style={mute}>{nodes.length - 8} more in the explorer below.</span>}
    </Panel>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────

type VisualView = 'flow' | 'globe';

/**
 * Graph workspace (Claude Design handoff: Aether Explore → Graph, Aether Graph
 * Trace). GraphPage is deliberately composed rather than reimplemented: its
 * loading, empty, error, partial/truth, table, path, canvas and first-click
 * inspector behaviour stays the source of truth. The flow, globe, lenses and
 * replay above it are drawn from the same graph read GraphPage performs,
 * reported back through `onGraphData` — never from a second request or from
 * illustrative data.
 */
export function ExplorePage() {
  const navigate = useNavigate();
  // GraphContextProvider is the host authority for tenant/workspace and
  // environment identity. This route is intentionally not renderable without
  // that provider; no route or deployment label can stand in for its scope.
  const context = useGraphContext();
  const graph = useGraph();
  const history = useGraphHistory();
  const actions = useGraphActions();
  const [noesisExpanded, setNoesisExpanded] = useState(false);

  const [snapshot, setSnapshot] = useState<GraphSnapshot>(LOADING_SNAPSHOT);
  const handleGraphData = useCallback((data: GraphReadSnapshot) => setSnapshot(data), []);
  const index = useMemo(() => indexGraph(snapshot), [snapshot]);
  const [lensChoice, setLensChoice] = useState<LensId | null>(null);
  const lens: LensId = lensChoice && index.lenses[lensChoice].available ? lensChoice : defaultLens(index);
  const [view, setView] = useState<VisualView>('flow');
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

  const labels = useMemo(() => scopeLabels(context), [context]);
  const currentFocus = context.selection.focused;
  const historyEntries = history.entries;
  const currentTemporalLabel = temporalLabel(context);
  const selectedObjectKind = currentFocus?.kind ?? 'entity';
  const navigateWithContext = useCallback(() => {
    const query = graph.toQuery();
    navigate(query ? `/explore?${query}` : '/explore');
  }, [graph, navigate]);
  const selectGraphObject = useCallback((object: Pick<GraphObjectRef, 'id' | 'kind'>) => {
    const ref = {
      tenant_id: context.scope.tenant_id,
      environment_id: context.scope.environment_id,
      kind: object.kind,
      id: object.id,
    } satisfies GraphObjectRef;
    actions.selectObject(ref);
    actions.focusObject(ref);
    actions.appendHistory({
      object: ref,
      action: 'select',
      occurred_at: new Date().toISOString(),
    });
    navigateWithContext();
  }, [actions, context.scope.environment_id, context.scope.tenant_id, navigateWithContext]);
  const handleObjectSelected = useCallback((node: GraphNode) => {
    setPickedId(node.id);
    selectGraphObject(node);
  }, [selectGraphObject]);
  const handleClusterSelected = useCallback((cluster: GraphCluster) => {
    selectGraphObject({ id: cluster.id, kind: 'cluster' });
  }, [selectGraphObject]);
  const handleEdgeSelected = useCallback((edge: GraphEdge) => {
    selectGraphObject({ id: edge.id, kind: 'edge' });
  }, [selectGraphObject]);
  const pickNode = useCallback((node: GraphNode) => {
    setPickedId(node.id);
    setSelectedPlace(null);
  }, []);

  function moveThroughHistory(direction: 'previous' | 'next') {
    const next = direction === 'previous'
      ? actions.previousFocus(currentFocus)
      : actions.nextFocus(currentFocus);
    if (!next) return;
    actions.focusObject(next);
    navigateWithContext();
  }

  const selectedNode = index.byId.get(pickedId ?? currentFocus?.id ?? '') ?? null;
  const flow = useMemo(() => buildFlow(snapshot, index, lens, { cutoff: activeCutoff }), [snapshot, index, lens, activeCutoff]);
  const places = useMemo(() => buildPlaces(snapshot.nodes), [snapshot.nodes]);
  const timedTotal = index.time.size;
  const timedShown = activeCutoff === null ? timedTotal : [...index.time.values()].filter(t => t <= activeCutoff).length;
  const unavailableLenses = LENSES.filter(l => !index.lenses[l.id].available);

  const historyPosition = currentFocus
    ? historyEntries.findIndex((entry) => entry.object.id === currentFocus.id) + 1
    : historyEntries.length;

  let visual: ReactNode;
  if (snapshot.status === 'loading') {
    visual = (
      <div className="flex min-h-[260px] flex-col items-center justify-center gap-3" data-testid="graph-visual-loading">
        <Spinner />
        <span className="text-[13px]" style={mute}>Reading the graph…</span>
      </div>
    );
  } else if (snapshot.status === 'error') {
    visual = (
      <div data-testid="graph-visual-error">
        <InlineNotice tone="ember">The graph read failed, so the flow and globe are unavailable. The explorer below shows the error.</InlineNotice>
      </div>
    );
  } else if (snapshot.nodes.length === 0) {
    visual = (
      <div className="flex min-h-[220px] flex-col items-center justify-center gap-2 text-center" data-testid="graph-visual-empty">
        <span className="text-[15px] font-medium">No objects in this graph read yet</span>
        <span className="max-w-[420px] text-[13px]" style={mute}>Objects and relationships appear here once a connected source or SDK sends events.</span>
        <LinkButton onClick={() => navigate('/activation')}>Connect a source →</LinkButton>
      </div>
    );
  } else if (view === 'flow') {
    visual = <GraphFlow layout={flow} lens={lens} index={index} selectedId={selectedNode?.id ?? null} onSelect={pickNode} />;
  } else {
    visual = (
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_220px]">
        <GraphGlobe places={places.places} unknown={places.unknown} selectedPlace={selectedPlace} onSelectPlace={setSelectedPlace} />
        <div className="flex flex-col gap-1">
          <Eyebrow>Places</Eyebrow>
          <PlaceList places={places.places} selectedPlace={selectedPlace} onSelectPlace={setSelectedPlace} />
        </div>
      </div>
    );
  }

  return (
    <div data-testid="explore-page" className="flex min-w-0 flex-col gap-4">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[28px] font-medium leading-tight tracking-[-0.56px]">Graph</h1>
          <span className="text-[14px]" style={mute}>How is everything connected?</span>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2" data-testid="graph-context-bar" role="list" aria-label="Graph context">
          <ContextPill name="Workspace" value={labels.workspace} />
          <ContextPill name="Environment" value={labels.environment} />
          <ContextPill name="Time" value={currentTemporalLabel} />
        </div>
      </div>

      <GraphMaturityPanel />

      {/* Lens + view */}
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <LensChips index={index} lens={lens} onLens={setLensChoice} />
          <span className="inline-flex gap-0.5 rounded-full p-[3px]" style={{ background: 'var(--ae-edge-soft)' }} role="group" aria-label="Graph view">
            {(['flow', 'globe'] as const).map(v => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setView(v)}
                className="ae-focus rounded-full px-3 py-1 text-[13px]"
                style={{ background: view === v ? 'var(--ae-chip-on)' : 'transparent', color: view === v ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)' }}
              >
                {v === 'flow' ? 'Network flow' : 'Globe'}
              </button>
            ))}
          </span>
        </div>
        <span className="text-[12px]" style={mute} data-testid="graph-lens-note">
          {LENSES.find(l => l.id === lens)!.note} A lens changes how the graph reads, not the objects in it.
          {snapshot.status === 'ready' && unavailableLenses.length > 0 && (
            <> Not in this read: {unavailableLenses.map(l => l.label).join(', ')}.</>
          )}
        </span>
      </div>

      {/* Visual + side panels */}
      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Panel className="flex min-w-0 flex-col gap-3 p-4">
          <Eyebrow>{view === 'flow' ? 'Who and what is involved' : 'Where it happened'}</Eyebrow>
          {visual}
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
                Replay needs timestamped objects or links; this read carries none. Use “As of” in the explorer for a point-in-time graph.
              </span>
            )
          )}
        </Panel>
        <div className="flex min-w-0 flex-col gap-4">
          <LensPanel snapshot={snapshot} index={index} lens={lens} selectedId={selectedNode?.id ?? null} onSelect={pickNode} />
          {view === 'globe' && selectedPlace ? (
            <PlaceDetail placeKey={selectedPlace} snapshot={snapshot} index={index} onSelect={pickNode} />
          ) : (
            <SelectedPanel node={selectedNode} snapshot={snapshot} index={index} lens={lens} onFocus={(node) => selectGraphObject(node)} />
          )}
        </div>
      </div>

      {/* Full explorer: canvas, table, path finder, inspector */}
      <section data-testid="graph-workspace-frame" aria-label="Graph workspace" className="ae-glass-card flex min-w-0 flex-col overflow-hidden rounded-[22px]">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4">
          <span className="flex flex-col gap-0.5">
            <Eyebrow>Explorer</Eyebrow>
            <span className="text-[12px]" style={mute}>Every object and relationship in this read: canvas, table, path finder and inspector.</span>
          </span>
        </div>
        <div className="min-w-0">
          <GraphPage
            embedded
            onObjectSelected={handleObjectSelected}
            onClusterSelected={handleClusterSelected}
            onEdgeSelected={handleEdgeSelected}
            onGraphData={handleGraphData}
          />
        </div>
        <GraphTimeRail
          context={context}
          temporal={context.temporal}
          historyPosition={historyPosition}
          historyCount={historyEntries.length}
          onPrevious={() => moveThroughHistory('previous')}
          onNext={() => moveThroughHistory('next')}
        />
        <NoesisContextStrip
          contextChips={[
            labels.workspace,
            labels.environment,
            currentTemporalLabel,
            ...(currentFocus ? [`Focus · ${currentFocus.kind}:${currentFocus.id}`] : []),
          ]}
          expanded={noesisExpanded}
          onToggle={() => setNoesisExpanded((expanded) => !expanded)}
        >
          {noesisExpanded && (
            <div data-testid="noesis-context-expanded" className="flex flex-wrap items-center gap-2 py-2 text-[12px]" style={mute}>
              <span>Noesis opens with this graph context. Query and context handoff remain read-only until an explicit action is chosen.</span>
              <button
                type="button"
                className="ae-focus hover:underline"
                style={{ color: 'var(--ae-blue-ink)' }}
                onClick={() => {
                  const query = graph.toQuery();
                  navigate(query ? `/noesis?${query}` : '/noesis');
                }}
              >
                Open Noesis
              </button>
            </div>
          )}
        </NoesisContextStrip>
      </section>

      <RegistryPanel objectKind={selectedObjectKind} />

      <ExploreSnapshotControls />
    </div>
  );
}
