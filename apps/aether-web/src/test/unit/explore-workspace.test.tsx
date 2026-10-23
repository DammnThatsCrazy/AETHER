// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';

const runtime = vi.hoisted(() => {
  const focused = { tenant_id: 'tenant-1', environment_id: 'staging', kind: 'entity', id: 'entity-2' };
  const previous = { tenant_id: 'tenant-1', environment_id: 'staging', kind: 'entity', id: 'entity-1' };
  return {
    context: {
      version: '1',
      scope: { tenant_id: 'tenant-1', workspace_id: 'workspace-7', environment_id: 'staging' },
      temporal: { mode: 'as_of', field: 'occurred_at', as_of: '2026-09-01', timezone: 'UTC' },
      selection: { selected: [focused], focused, pinned: [], compared: [], snapshot_bound: [] },
    },
    history: {
      scope: { tenant_id: 'tenant-1', workspace_id: 'workspace-7', environment_id: 'staging' },
      entries: [
        { object: previous, action: 'open', occurred_at: '2026-08-31T00:00:00Z' },
        { object: focused, action: 'select', occurred_at: '2026-09-01T00:00:00Z' },
      ],
    },
    actions: {
      previousFocus: vi.fn(() => previous),
      nextFocus: vi.fn(() => null),
      focusObject: vi.fn(),
      selectObject: vi.fn(),
      appendHistory: vi.fn(),
    },
    filters: {
      population: null,
      addFilter: vi.fn(),
      removeFilterAt: vi.fn(),
      setPopulation: vi.fn(),
    },
    graphQuery: 'tmode=as_of&tfield=occurred_at&tz=UTC&tas=2026-09-01&focus=entity%3Aentity-2&sel=entity%3Aentity-2',
    readiness: {
      data: undefined as unknown,
      isLoading: false,
      error: null as Error | null,
    },
    maturity: {
      state: 'ready' as 'no_data' | 'building' | 'ready',
      blocking: [] as readonly string[],
    },
    graphData: null as unknown,
  };
});

vi.mock('@aether-app/features/activation/use-tenant-readiness', () => ({
  useTenantReadiness: () => runtime.readiness,
  deriveGraphMaturity: () => runtime.maturity,
}));

vi.mock('@aether/ui/exploration', () => ({
  allBlueprintLenses: () => [{ id: 'object', displayName: 'Objects', description: 'Objects', pending: false }],
  resolveLensAvailability: (id: string) => ({ lensId: id, availability: 'available', entry: { id, displayName: 'Objects', pending: false } }),
  FilterBar: () => <div data-testid="filter-bar">No active filters.</div>,
  FilterBuilder: () => <div data-testid="filter-builder">Filter builder</div>,
  GraphContextBar: ({ workspaceLabel, environmentLabel, timeLabel }: Record<string, string>) => (
    <div data-testid="graph-context-bar">{workspaceLabel} · {environmentLabel} · {timeLabel}</div>
  ),
  GraphTimeRail: ({ historyPosition, historyCount, onPrevious, onNext }: Record<string, unknown>) => (
    <div data-testid="graph-time-rail">
      <span>History {String(historyPosition)} of {String(historyCount)}</span>
      <button type="button" onClick={onPrevious as () => void}>Previous</button>
      <button type="button" onClick={onNext as () => void}>Next</button>
    </div>
  ),
  NoesisContextStrip: ({ expanded, onToggle, children }: Record<string, unknown>) => (
    <div data-testid="noesis-context-strip">
      <button type="button" onClick={onToggle as () => void}>{expanded ? 'Hide context' : 'Show context'}</button>
      {expanded ? children as ReactNode : null}
    </div>
  ),
  GraphWorkspaceFrame: ({ contextBar, lensDock, canvas, timeRail, noesisStrip }: Record<string, unknown>) => (
    <section data-testid="graph-workspace-frame">
      {contextBar as ReactNode}
      {lensDock as ReactNode}
      {canvas as ReactNode}
      {timeRail as ReactNode}
      {noesisStrip as ReactNode}
    </section>
  ),
  useGraphContext: () => runtime.context,
  useExplorationContext: () => runtime.context,
  useGraph: () => ({ toQuery: () => runtime.graphQuery }),
  useGraphHistory: () => runtime.history,
  useGraphActions: () => runtime.actions,
  useExplorationFilters: () => runtime.filters,
}));

vi.mock('@aether-app/pages/graph/graph-page', async () => {
  const { useEffect } = await import('react');
  return {
  GraphPage: ({ embedded, onObjectSelected, onClusterSelected, onEdgeSelected, onGraphData }: {
    embedded?: boolean;
    onGraphData?: (data: unknown) => void;
    onObjectSelected?: (node: { id: string; kind: string; label: string; metadata: Record<string, unknown> }) => void;
    onClusterSelected?: (cluster: { id: string; label: string; nodeIds: string[]; size: number }) => void;
    onEdgeSelected?: (edge: { id: string; source: string; target: string; relationType: string; interactionClass: string; weight: number; metadata: Record<string, unknown> }) => void;
  }) => {
    useEffect(() => {
      if (runtime.graphData) onGraphData?.(runtime.graphData);
    }, [onGraphData]);
    return (
    <div data-testid="real-graph-page" data-graph-embedded={embedded ? 'true' : 'false'}>
      <button type="button">Real graph canvas</button>
      <button type="button">Real first-click inspector</button>
      <button
        type="button"
        onClick={() => onObjectSelected?.({ id: 'entity-3', kind: 'organization', label: 'Entity three', metadata: {} })}
      >Select object</button>
      <button type="button" onClick={() => onClusterSelected?.({ id: 'cluster-1', label: 'Cluster one', nodeIds: ['entity-3'], size: 1 })}>Select cluster</button>
      <button type="button" onClick={() => onEdgeSelected?.({ id: 'edge-1', source: 'entity-3', target: 'entity-4', relationType: 'DELEGATES', interactionClass: 'H2A', weight: 1, metadata: {} })}>Select edge</button>
    </div>
    );
  },
  };
});

vi.mock('@aether-app/pages/explore/explore-read', () => ({
  useExploreGraphRead: () => runtime.graphData ?? { status: 'loading', nodes: [], edges: [], clusters: [] },
}));

afterEach(cleanup);

beforeEach(() => {
  runtime.readiness = { data: { checks: [] }, isLoading: false, error: null };
  runtime.maturity = { state: 'ready', blocking: [] };
  runtime.graphData = null;
});

import { ExplorePage } from '@aether-app/pages/explore/explore-page';

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

function renderWorkspace(path = '/explore') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ExplorePage />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe('ExplorePage advanced explorer (?view=advanced)', () => {
  it('composes the real GraphPage and preserves canonical scope/time labels', () => {
    renderWorkspace('/explore?view=advanced');

    expect(screen.getByTestId('graph-workspace-frame')).toBeInTheDocument();
    expect(screen.getByTestId('real-graph-page')).toHaveAttribute('data-graph-embedded', 'true');
    expect(screen.getByTestId('real-graph-page')).toHaveTextContent('Real graph canvas');
    expect(screen.getByTestId('graph-context-bar')).toHaveTextContent('workspace-7');
    expect(screen.getByTestId('graph-context-bar')).toHaveTextContent('staging');
    expect(screen.getByTestId('graph-context-bar')).toHaveTextContent('As of 2026-09-01');
    expect(screen.getByTestId('graph-time-rail')).toHaveTextContent('History 2 of 2');
    expect(screen.getByTestId('graph-maturity-ready')).toHaveTextContent('Graph foundations are verified.');
  });

  it('exposes the registry-backed query builder from the canonical lens dock', async () => {
    renderWorkspace('/explore?view=advanced');

    await userEvent.click(screen.getByText('Query builder'));

    expect(screen.getByTestId('filter-builder')).toHaveTextContent('Filter builder');
    expect(screen.getByTestId('filter-bar')).toBeInTheDocument();
  });

  it('uses existing graph history actions and makes the selected destination explicit', async () => {
    renderWorkspace('/explore?view=advanced');
    runtime.actions.appendHistory.mockClear();

    await userEvent.click(screen.getByRole('button', { name: 'Previous' }));

    expect(runtime.actions.previousFocus).toHaveBeenCalledWith(runtime.context.selection.focused);
    expect(runtime.actions.focusObject).toHaveBeenCalledWith(expect.objectContaining({ id: 'entity-1' }));
    expect(runtime.actions.appendHistory).not.toHaveBeenCalled();
    expect(screen.getByTestId('location')).toHaveTextContent('/explore?tmode=as_of');
    expect(screen.getByTestId('location')).not.toHaveTextContent('entity=');
  });

  it('merges object selection into canonical context and records the production transition', async () => {
    renderWorkspace('/explore?view=advanced');

    await userEvent.click(screen.getByRole('button', { name: 'Select object' }));

    expect(runtime.actions.selectObject).toHaveBeenCalledWith(expect.objectContaining({
      tenant_id: 'tenant-1',
      environment_id: 'staging',
      kind: 'organization',
      id: 'entity-3',
    }));
    expect(runtime.actions.focusObject).toHaveBeenCalledWith(expect.objectContaining({ id: 'entity-3' }));
    expect(runtime.actions.appendHistory).toHaveBeenCalledWith(expect.objectContaining({
      action: 'select',
      object: expect.objectContaining({ id: 'entity-3' }),
    }));
    expect(screen.getByTestId('location')).toHaveTextContent('/explore?tmode=as_of');
    expect(screen.getByTestId('location')).not.toHaveTextContent('entity=');
  });

  it.each([
    ['cluster', 'Select cluster', 'cluster-1'],
    ['relationship', 'Select edge', 'edge-1'],
  ])('routes %s selection through the canonical graph context', async (_kind, button, id) => {
    renderWorkspace('/explore?view=advanced');

    await userEvent.click(screen.getByRole('button', { name: button }));

    expect(runtime.actions.selectObject).toHaveBeenCalledWith(expect.objectContaining({ id }));
    expect(runtime.actions.focusObject).toHaveBeenCalledWith(expect.objectContaining({ id }));
    expect(runtime.actions.appendHistory).toHaveBeenCalledWith(expect.objectContaining({
      action: 'select',
      object: expect.objectContaining({ id }),
    }));
    expect(screen.getByTestId('location')).not.toHaveTextContent('entity=');
  });

  it('keeps Noesis collapsed until explicitly expanded and offers a truthful route action', async () => {
    renderWorkspace('/explore?view=advanced');

    expect(screen.queryByTestId('noesis-context-expanded')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Show context' }));
    expect(screen.getByTestId('noesis-context-expanded')).toBeInTheDocument();
    expect(screen.getByText('Open Noesis')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Open Noesis' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/noesis?tmode=as_of');
  });

  it.each([
    ['loading', { data: undefined, isLoading: true, error: null }, 'graph-maturity-loading', 'Checking graph foundations'],
    ['error', { data: undefined, isLoading: false, error: new Error('unavailable') }, 'graph-maturity-error', 'could not be checked'],
    ['unavailable', { data: undefined, isLoading: false, error: null }, 'graph-maturity-unavailable', 'is unavailable'],
  ])('renders an explicit %s readiness state while keeping the real graph mounted', (_name, query, testId, text) => {
    runtime.readiness = query;
    renderWorkspace('/explore?view=advanced');

    expect(screen.getByTestId(testId)).toHaveTextContent(text);
    expect(screen.getByTestId('real-graph-page')).toBeInTheDocument();
  });

  it('renders observed-data guidance and links to Activation for no-data maturity', async () => {
    runtime.maturity = { state: 'no_data', blocking: ['events_received'] };
    renderWorkspace('/explore?view=advanced');

    expect(screen.getByTestId('graph-maturity-no-data')).toHaveTextContent('needs observed events and links');
    expect(screen.getByTestId('real-graph-page')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('link', { name: 'Connect a source in Activation' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/activate');
  });

  it('quantifies real blocking checks while the graph is building', () => {
    runtime.maturity = {
      state: 'building',
      blocking: ['identity_resolution_verified', 'graph_projection_verified'],
    };
    renderWorkspace('/explore?view=advanced');

    expect(screen.getByTestId('graph-maturity-building')).toHaveTextContent('2 checks still blocking verification');
    expect(screen.getByTestId('graph-maturity-building')).toHaveTextContent('identity_resolution_verified');
    expect(screen.getByTestId('graph-maturity-building')).toHaveTextContent('graph_projection_verified');
    expect(screen.getByTestId('real-graph-page')).toBeInTheDocument();
  });
});

const node = (id: string, kind: string, label: string, metadata: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({ id, kind, label, metadata, ...extra });
const edge = (id: string, source: string, target: string, relationType: string, metadata: Record<string, unknown> = {}) => ({
  id, source, target, relationType, interactionClass: 'H2A', weight: 1, metadata,
});

describe('ExplorePage trace view (?view=trace: flow, globe, lenses, replay)', () => {
  it('shows a loading state until the composed graph read reports back', () => {
    renderWorkspace('/explore?view=trace');
    expect(screen.getByTestId('graph-visual-loading')).toHaveTextContent('Reading the graph');
    expect(screen.queryByTestId('graph-flow')).not.toBeInTheDocument();
  });

  it('marks the views unavailable (never empty) when the graph read fails', async () => {
    runtime.graphData = { status: 'error', nodes: [], edges: [], clusters: [] };
    renderWorkspace('/explore?view=trace');
    expect(await screen.findByTestId('graph-visual-error')).toHaveTextContent('graph read failed');
    expect(screen.queryByTestId('graph-visual-empty')).not.toBeInTheDocument();
  });

  it('says the read is empty and links to a real setup route', async () => {
    runtime.graphData = { status: 'ready', nodes: [], edges: [], clusters: [] };
    renderWorkspace('/explore?view=trace');
    expect(await screen.findByTestId('graph-visual-empty')).toHaveTextContent('No objects in this graph read yet');
    await userEvent.click(screen.getByRole('button', { name: /Connect a source/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('/activation');
  });

  it('draws the left-to-right flow from real nodes and disables lenses the read cannot support', async () => {
    runtime.graphData = {
      status: 'ready',
      nodes: [
        node('p1', 'entity', 'Person one', { city: 'Atlanta', country: 'US', latitude: 33.75, longitude: -84.39 }, { riskScore: 0.8 }),
        node('a1', 'Agent', 'Agent one'),
        node('o1', 'Organization', 'Store one', { city: 'Manchester', country: 'UK' }),
      ],
      edges: [edge('e1', 'p1', 'a1', 'DELEGATES'), edge('e2', 'p1', 'o1', 'PAID_MERCHANT')],
      clusters: [],
    };
    renderWorkspace('/explore?view=trace&tv=flow');

    const flow = await screen.findByTestId('graph-flow');
    expect(flow.querySelector('[data-flow-node="p1"]')).toHaveTextContent('Person one');
    expect(flow.querySelector('[data-flow-node="a1"]')).toHaveTextContent('Agent one');
    expect(flow.querySelector('[data-flow-column="people"]')).toHaveTextContent('1');
    // Value and time are absent from this read, so their lenses cannot apply.
    expect(document.querySelector('[data-lens="value"]')).toBeDisabled();
    expect(document.querySelector('[data-lens="time"]')).toBeDisabled();
    expect(document.querySelector('[data-lens="risk"]')).not.toBeDisabled();
    expect(screen.getByTestId('graph-lens-note')).toHaveTextContent('Not in this read: Value, Time');
    expect(screen.getByTestId('graph-replay-unavailable')).toBeInTheDocument();

    await userEvent.click(document.querySelector('[data-lens="risk"]') as HTMLElement);
    expect(screen.getByTestId('graph-lens-panel')).toHaveTextContent('Highest risk');

    await userEvent.click(flow.querySelector('[data-flow-node="p1"]') as HTMLElement);
    const selected = screen.getByTestId('graph-selected-panel');
    expect(selected).toHaveTextContent('Person one');
    expect(screen.getByRole('button', { name: 'Open profile →' })).toBeInTheDocument();
  });

  it('pins located places on the globe and counts objects without a location as unknown', async () => {
    runtime.graphData = {
      status: 'ready',
      nodes: [
        node('p1', 'entity', 'Person one', { city: 'Atlanta', country: 'US', latitude: 33.75, longitude: -84.39 }),
        node('p2', 'entity', 'Person two'),
      ],
      edges: [],
      clusters: [],
    };
    renderWorkspace('/explore?view=trace&tv=flow');
    await screen.findByTestId('graph-flow');
    await userEvent.click(screen.getByRole('button', { name: 'Globe' }));
    expect(screen.getByTestId('location')).toHaveTextContent('tv=globe');

    expect(document.querySelector('[data-globe-place="Atlanta, US"]')).not.toBeNull();
    expect(screen.getByTestId('graph-globe-unknown')).toHaveTextContent('Location not reported for 1 object');
    await userEvent.click(screen.getByRole('button', { name: /Atlanta, US/ }));
    expect(screen.getByTestId('graph-place-panel')).toHaveTextContent('1 object in this read');
    expect(screen.getByRole('button', { name: /Person one/ })).toBeInTheDocument();
  });

  it('offers a replay scrubber only when the read carries timestamps', async () => {
    runtime.graphData = {
      status: 'ready',
      nodes: [node('p1', 'entity', 'Person one'), node('a1', 'Agent', 'Agent one'), node('o1', 'Organization', 'Store')],
      edges: [
        edge('e1', 'p1', 'a1', 'DELEGATES', { valid_from: '2026-09-01T00:00:00Z' }),
        edge('e2', 'a1', 'o1', 'PAYS', { valid_from: '2026-09-20T00:00:00Z' }),
      ],
      clusters: [],
    };
    renderWorkspace('/explore?view=trace');
    const replay = await screen.findByTestId('graph-replay');
    expect(replay).toHaveTextContent('2026-09-01');
    expect(replay).toHaveTextContent('2026-09-20');
    expect(document.querySelector('[data-lens="time"]')).not.toBeDisabled();
    expect(screen.queryByTestId('graph-replay-unavailable')).not.toBeInTheDocument();
  });
});

describe('ExplorePage trace scoping and globe arcs', () => {
  const read = () => ({
    status: 'ready',
    nodes: [
      node('p1', 'entity', 'Person one', { city: 'Atlanta', country: 'US', latitude: 33.75, longitude: -84.39 }),
      node('o1', 'Merchant', 'Store one', { city: 'Manchester', country: 'UK', latitude: 53.48, longitude: -2.24 }),
      node('far', 'entity', 'Far person', { city: 'Tokyo', country: 'JP', latitude: 35.68, longitude: 139.69 }),
      node('mid', 'Agent', 'Middle agent'),
      node('mid2', 'Agent', 'Second agent'),
    ],
    edges: [
      edge('e1', 'p1', 'o1', 'PURCHASED', { value: 418 }),
      edge('e2', 'o1', 'mid', 'USES'),
      edge('e3', 'mid', 'mid2', 'LAUNCHED_BY'),
      edge('e4', 'mid2', 'far', 'OWNED_BY'),
    ],
    clusters: [],
  });

  it('opens on the globe with arcs between linked places, scoped to the entity neighbourhood', async () => {
    runtime.graphData = read();
    renderWorkspace('/explore?view=trace&entity=p1');

    expect(await screen.findByTestId('graph-globe')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Person one · trace' })).toBeInTheDocument();
    expect(screen.getByTestId('graph-trace-sub')).toHaveTextContent('3 objects and 2 links within 2 hops');
    expect(document.querySelector('[data-globe-arc]')).not.toBeNull();
    // Tokyo is four hops away, so it is outside this trace.
    expect(document.querySelector('[data-globe-place="Tokyo, JP"]')).toBeNull();
  });

  it('goes back to the network view keeping the scope', async () => {
    runtime.graphData = read();
    renderWorkspace('/explore?view=trace&entity=p1&tv=both');
    expect(await screen.findByTestId('graph-flow')).toBeInTheDocument();
    expect(screen.getByTestId('graph-globe')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '← Back to graph' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/explore?entity=p1');
    expect(screen.getByTestId('location')).not.toHaveTextContent('view=');
    expect(screen.getByTestId('explore-network')).toBeInTheDocument();
  });
});

describe('ExplorePage network view (default)', () => {
  const read = () => ({
    status: 'ready',
    nodes: [
      node('p1', 'User', 'Person one', { city: 'Atlanta', country: 'US' }, { riskScore: 0.12 }),
      node('p2', 'User', 'Person two'),
      node('p3', 'User', 'Person three'),
      node('o1', 'Organization', 'Org one'),
      node('a1', 'Agent', 'Agent one'),
      node('a2', 'Agent', 'Lone agent'),
      node('w1', 'Wallet', 'Wallet one'),
      node('s1', 'Source', 'Source one'),
    ],
    edges: [
      edge('e1', 'p1', 'a1', 'DELEGATES', { volume_usd: 1842 }),
      edge('e2', 'p1', 'w1', 'OWNS_WALLET'),
      edge('e3', 's1', 'p1', 'ATTRIBUTED_TO'),
      edge('e4', 'p1', 'p2', 'SENT', { amount_usd: 500 }),
      edge('e5', 'p1', 'o1', 'BELONGS_TO'),
      edge('e6', 'o1', 'p3', 'EMPLOYS'),
      edge('e7', 'a2', 'w1', 'USES'),
    ],
    clusters: [],
  });

  it('shows loading, error and an honest empty state', async () => {
    renderWorkspace();
    expect(screen.getByTestId('graph-visual-loading')).toHaveTextContent('Reading the graph');
    cleanup();

    runtime.graphData = { status: 'error', nodes: [], edges: [], clusters: [] };
    renderWorkspace();
    expect(screen.getByTestId('graph-visual-error')).toHaveTextContent('graph read failed');
    expect(screen.queryByTestId('graph-visual-empty')).not.toBeInTheDocument();
    cleanup();

    runtime.graphData = { status: 'ready', nodes: [], edges: [], clusters: [] };
    renderWorkspace();
    expect(screen.getByTestId('graph-visual-empty')).toHaveTextContent('No objects in this graph read yet');
    expect(screen.queryByTestId('graph-path-strip')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Connect a source/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('/activation');
  });

  it('draws principal cards with what they own or use and labels links by amount only when one is reported', () => {
    runtime.graphData = read();
    renderWorkspace();

    const card = document.querySelector('[data-graph-card="p1"]') as HTMLElement;
    expect(card).toHaveTextContent('Person one');
    expect(card.querySelector('[data-graph-card-row="a1"]')).toHaveTextContent('$1.8K');
    expect(card.querySelector('[data-graph-card-row="w1"]')).toHaveTextContent('owns wallet');
    expect(card.querySelector('[data-graph-card-row="s1"]')).toHaveTextContent('attributed to');
    // An agent nobody owns gets its own card in "All".
    expect(document.querySelector('[data-graph-card="a2"]')).not.toBeNull();
    expect(document.querySelector('[data-graph-card="a1"]')).toBeNull();

    const links = screen.getByTestId('graph-card-links');
    expect(links).toHaveTextContent('Person one → Person two: $500');
    expect(links).toHaveTextContent('Person one → Org one: belongs to');
    expect(links.querySelector('[data-link-kind="money"]')).not.toBeNull();

    expect(document.querySelector('[data-category="people"]')).toHaveTextContent('People3');
    expect(document.querySelector('[data-category="agents"]')).toHaveTextContent('Agents2');
    expect(screen.getByTestId('graph-legend')).toHaveTextContent('sent money');
  });

  it('scopes from an existing "Open in Graph" link, limits hops and lists direct connections', async () => {
    runtime.graphData = read();
    renderWorkspace('/explore?entity=p1');

    expect(screen.getByTestId('graph-scope-chip')).toHaveTextContent('Scope: Person one');
    const inspector = screen.getByTestId('graph-inspector');
    expect(inspector).toHaveTextContent('Person one');
    expect(inspector).toHaveTextContent('risk 0.12');
    const connections = screen.getByTestId('graph-inspector-connections');
    expect(connections).toHaveTextContent('Agents');
    expect(connections).toHaveTextContent('Agent one · $1.8K');
    expect(connections).toHaveTextContent('Wallets');

    // Two hops (default) reaches Person three through Org one; one hop does not.
    expect(document.querySelector('[data-graph-card="p3"]')).not.toBeNull();
    await userEvent.click(document.querySelector('[data-hops="1"]') as HTMLElement);
    expect(document.querySelector('[data-graph-card="p3"]')).toBeNull();
    expect(document.querySelector('[data-category="people"]')).toHaveTextContent('People2');

    await userEvent.click(screen.getByRole('button', { name: 'Clear scope' }));
    expect(screen.getByTestId('location')).not.toHaveTextContent('entity=');
    expect(document.querySelector('[data-hops="1"]')).toBeDisabled();
  });

  it('draws the path strip from the scope to the selected object', async () => {
    runtime.graphData = read();
    renderWorkspace('/explore?entity=p1');
    expect(screen.getByTestId('graph-path-strip')).toHaveTextContent('Select another card or row');

    await userEvent.click(document.querySelector('[data-graph-card="p3"] button') as HTMLElement);
    const strip = screen.getByTestId('graph-path-strip');
    expect(strip).toHaveTextContent('Path from Person one to Person three');
    expect(strip).toHaveTextContent('belongs to →');
    expect(strip).toHaveTextContent('2 hops');
    expect(runtime.actions.selectObject).toHaveBeenCalledWith(expect.objectContaining({ id: 'p3' }));
    expect(screen.getByTestId('graph-inspector')).toHaveTextContent('Person three');
  });

  it('filters by perspective, object type and search', async () => {
    runtime.graphData = read();
    renderWorkspace();

    await userEvent.click(screen.getByRole('button', { name: 'Agent' }));
    expect(document.querySelector('[data-graph-card="a1"]')).not.toBeNull();
    expect(document.querySelector('[data-graph-card="p1"]')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'All' }));

    await userEvent.click(document.querySelector('[data-category="wallets"]') as HTMLElement);
    expect(document.querySelector('[data-graph-card-row="w1"]')).toBeNull();
    await userEvent.click(document.querySelector('[data-category="wallets"]') as HTMLElement);

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search the graph' }), 'org one');
    expect(document.querySelector('[data-graph-card="o1"]')).not.toBeNull();
    expect(document.querySelector('[data-graph-card="p2"]')).toBeNull();
    await userEvent.clear(screen.getByRole('searchbox', { name: 'Search the graph' }));
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search the graph' }), 'nothing-matches');
    expect(screen.getByTestId('graph-cards-none')).toHaveTextContent('Nothing matches these filters');
  });

  it('opens the globe trace and the advanced explorer from the toolbar', async () => {
    runtime.graphData = read();
    renderWorkspace('/explore?entity=p1&tmode=as_of');

    await userEvent.click(screen.getByRole('button', { name: 'Globe' }));
    expect(screen.getByTestId('location')).toHaveTextContent('view=trace');
    expect(screen.getByTestId('location')).toHaveTextContent('tv=globe');
    expect(screen.getByTestId('location')).toHaveTextContent('entity=p1');
    expect(screen.getByTestId('location')).toHaveTextContent('tmode=as_of');
    expect(screen.getByTestId('explore-trace')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '← Back to graph' }));
    await userEvent.click(screen.getByRole('button', { name: 'Advanced explorer →' }));
    expect(screen.getByTestId('location')).toHaveTextContent('view=advanced');
    expect(screen.getByTestId('real-graph-page')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '← Graph' }));
    expect(screen.getByTestId('explore-network')).toBeInTheDocument();
  });

  it('accepts the legacy selected_entity deep link as the scope', () => {
    runtime.graphData = read();
    renderWorkspace('/explore?selected_entity=o1');
    expect(screen.getByTestId('graph-scope-chip')).toHaveTextContent('Scope: Org one');
  });
});
