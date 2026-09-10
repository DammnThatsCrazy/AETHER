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

vi.mock('@aether-app/pages/graph/graph-page', () => ({
  GraphPage: ({ embedded, onObjectSelected, onClusterSelected, onEdgeSelected }: {
    embedded?: boolean;
    onObjectSelected?: (node: { id: string; kind: string; label: string; metadata: Record<string, unknown> }) => void;
    onClusterSelected?: (cluster: { id: string; label: string; nodeIds: string[]; size: number }) => void;
    onEdgeSelected?: (edge: { id: string; source: string; target: string; relationType: string; interactionClass: string; weight: number; metadata: Record<string, unknown> }) => void;
  }) => (
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
  ),
}));

afterEach(cleanup);

beforeEach(() => {
  runtime.readiness = { data: { checks: [] }, isLoading: false, error: null };
  runtime.maturity = { state: 'ready', blocking: [] };
});

import { ExplorePage } from '@aether-app/pages/explore/explore-page';

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

function renderWorkspace() {
  return render(
    <MemoryRouter initialEntries={['/explore']}>
      <ExplorePage />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe('ExplorePage graph-first workspace', () => {
  it('composes the real GraphPage and preserves canonical scope/time labels', () => {
    renderWorkspace();

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
    renderWorkspace();

    await userEvent.click(screen.getByText('Query builder'));

    expect(screen.getByTestId('filter-builder')).toHaveTextContent('Filter builder');
    expect(screen.getByTestId('filter-bar')).toBeInTheDocument();
  });

  it('uses existing graph history actions and makes the selected destination explicit', async () => {
    renderWorkspace();

    await userEvent.click(screen.getByRole('button', { name: 'Previous' }));

    expect(runtime.actions.previousFocus).toHaveBeenCalledWith(runtime.context.selection.focused);
    expect(runtime.actions.focusObject).toHaveBeenCalledWith(expect.objectContaining({ id: 'entity-1' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/explore?tmode=as_of');
    expect(screen.getByTestId('location')).not.toHaveTextContent('entity=');
  });

  it('merges object selection into canonical context and records the production transition', async () => {
    renderWorkspace();

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
    renderWorkspace();

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
    renderWorkspace();

    expect(screen.queryByTestId('noesis-context-expanded')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Show context' }));
    expect(screen.getByTestId('noesis-context-expanded')).toBeInTheDocument();
    expect(screen.getByText('Open Noesis')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Open Noesis' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/noesis');
  });

  it.each([
    ['loading', { data: undefined, isLoading: true, error: null }, 'graph-maturity-loading', 'Checking graph foundations'],
    ['error', { data: undefined, isLoading: false, error: new Error('unavailable') }, 'graph-maturity-error', 'could not be checked'],
    ['unavailable', { data: undefined, isLoading: false, error: null }, 'graph-maturity-unavailable', 'is unavailable'],
  ])('renders an explicit %s readiness state while keeping the real graph mounted', (_name, query, testId, text) => {
    runtime.readiness = query;
    renderWorkspace();

    expect(screen.getByTestId(testId)).toHaveTextContent(text);
    expect(screen.getByTestId('real-graph-page')).toBeInTheDocument();
  });

  it('renders observed-data guidance and links to Activation for no-data maturity', async () => {
    runtime.maturity = { state: 'no_data', blocking: ['events_received'] };
    renderWorkspace();

    expect(screen.getByTestId('graph-maturity-no-data')).toHaveTextContent('needs observed events and links');
    await userEvent.click(screen.getByRole('link', { name: 'Connect a source in Activation' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/activate');
    expect(screen.getByTestId('real-graph-page')).toBeInTheDocument();
  });

  it('quantifies real blocking checks while the graph is building', () => {
    runtime.maturity = {
      state: 'building',
      blocking: ['identity_resolution_verified', 'graph_projection_verified'],
    };
    renderWorkspace();

    expect(screen.getByTestId('graph-maturity-building')).toHaveTextContent('2 checks still blocking verification');
    expect(screen.getByTestId('graph-maturity-building')).toHaveTextContent('identity_resolution_verified');
    expect(screen.getByTestId('graph-maturity-building')).toHaveTextContent('graph_projection_verified');
    expect(screen.getByTestId('real-graph-page')).toBeInTheDocument();
  });
});
