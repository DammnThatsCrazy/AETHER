// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';

const runtime = vi.hoisted(() => ({
  listSnapshots: vi.fn(),
  createSnapshot: vi.fn(),
  compareSnapshot: vi.fn(),
  bindSnapshot: vi.fn(),
  appendHistory: vi.fn(),
}));

vi.mock('@aether/ui/exploration', () => ({
  useGraph: () => ({
    client: {
      listSnapshots: runtime.listSnapshots,
      createSnapshot: runtime.createSnapshot,
      compareSnapshot: runtime.compareSnapshot,
    },
    actions: {
      bindSnapshot: runtime.bindSnapshot,
      appendHistory: runtime.appendHistory,
    },
  }),
  useGraphContext: () => ({
    scope: { tenant_id: 'tenant-a', workspace_id: 'workspace-a', environment_id: 'staging' },
  }),
  useExplorationContext: () => ({
    version: '1',
    scope: { tenant_id: 'tenant-a', surface: 'graph' },
    temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
  }),
}));

import { ExploreSnapshotControls } from '@aether-app/features/graph/explore-snapshot-controls';

const snapshot = {
  snapshot_id: 'snapshot-1',
  tenant_id: 'tenant-a',
  name: 'Morning graph',
  created_at: '2026-09-09T12:00:00Z',
};

function renderControls() {
  return render(<ExploreSnapshotControls />);
}

describe('ExploreSnapshotControls', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_FEATURE_FLAGS', JSON.stringify({ enableExplorationSnapshots: true }));
    Object.values(runtime).forEach((mock) => mock.mockReset());
    queryCache.invalidatePrefix('explore:snapshots:');
    runtime.listSnapshots.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
  });

  it('is flag-off and request-free by default', () => {
    vi.stubEnv('VITE_FEATURE_FLAGS', '{}');
    renderControls();
    expect(screen.queryByTestId('explore-snapshot-controls')).not.toBeInTheDocument();
    expect(runtime.listSnapshots).not.toHaveBeenCalled();
  });

  it('renders an honest empty state and captures through the typed client', async () => {
    const user = userEvent.setup();
    runtime.createSnapshot.mockResolvedValue({ snapshot });
    renderControls();

    expect(await screen.findByText('No immutable snapshots')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Capture snapshot' }));

    expect(runtime.createSnapshot).toHaveBeenCalledWith({
      context: expect.objectContaining({ scope: { tenant_id: 'tenant-a', surface: 'graph' } }),
      name: 'Graph exploration snapshot',
      limit: 500,
    });
    expect(runtime.bindSnapshot).toHaveBeenCalledWith({
      tenant_id: 'tenant-a', environment_id: 'staging', snapshot_id: 'snapshot-1',
    });
    expect(runtime.appendHistory).toHaveBeenCalledWith(expect.objectContaining({
      action: 'snapshot',
      object: expect.objectContaining({ kind: 'snapshot', id: 'snapshot-1' }),
    }));
  });

  it('compares a saved snapshot and surfaces the server comparison result', async () => {
    const user = userEvent.setup();
    runtime.listSnapshots.mockResolvedValue([snapshot]);
    runtime.compareSnapshot.mockResolvedValue({
      snapshot_id: 'snapshot-1', tenant_id: 'tenant-a', snapshot_watermark: 's1', current_watermark: 's2',
      changed: true, diff: {}, current_truth_state: 'ready', current_completeness: {}, warnings: [], computed_at: '2026-09-09T12:01:00Z',
    });
    renderControls();

    await user.click(await screen.findByRole('button', { name: 'Compare Morning graph with current graph' }));
    expect(await screen.findByText('Differences detected')).toBeInTheDocument();
    expect(runtime.compareSnapshot).toHaveBeenCalledWith('snapshot-1');
    expect(runtime.appendHistory).toHaveBeenCalledWith(expect.objectContaining({ action: 'diff' }));
  });

  it('shows a truthful load failure with retry', async () => {
    runtime.listSnapshots.mockRejectedValue(new Error('snapshot unavailable'));
    renderControls();
    expect(await screen.findByText('Saved exploration snapshots could not be loaded.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
