// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
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
    },
  };
});

vi.mock('@aether/ui/exploration', () => ({
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
  useGraphHistory: () => runtime.history,
  useGraphActions: () => runtime.actions,
}));

vi.mock('@aether-app/pages/graph/graph-page', () => ({
  GraphPage: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="real-graph-page" data-graph-embedded={embedded ? 'true' : 'false'}>
      <button type="button">Real graph canvas</button>
      <button type="button">Real first-click inspector</button>
    </div>
  ),
}));

afterEach(cleanup);

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
  });

  it('uses existing graph history actions and makes the selected destination explicit', async () => {
    renderWorkspace();

    await userEvent.click(screen.getByRole('button', { name: 'Previous' }));

    expect(runtime.actions.previousFocus).toHaveBeenCalledWith(runtime.context.selection.focused);
    expect(runtime.actions.focusObject).toHaveBeenCalledWith(expect.objectContaining({ id: 'entity-1' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/explore?entity=entity-1');
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
});
