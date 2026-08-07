import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider, ToastProvider, queryCache } from '@aether/ui';
import {
  ContinueOnPhone,
  RecentActivity,
  SYNC_CHANGE_TYPE_LABELS,
  syncChangeTypeLabel,
} from '@aether-app/features/continuation';

const mocks = vi.hoisted(() => ({
  recent: vi.fn(),
  create: vi.fn(),
  handoff: vi.fn(),
  clientSync: vi.fn(),
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    continuations: {
      recent: mocks.recent,
      create: mocks.create,
      handoff: mocks.handoff,
    },
    clientSync: mocks.clientSync,
  },
}));

vi.mock('@aether/ui/exploration', () => ({
  useExplorationContext: () => ({
    version: '1',
    scope: { tenant_id: 'tenant-a', surface: '/noesis' },
    temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
    selection: { selected: [{ kind: 'user', id: 'usr_1' }] },
  }),
}));

const CONTEXT = {
  version: '1',
  scope: { tenant_id: 'tenant-a', surface: '/noesis' },
  temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
  selection: { selected: [{ kind: 'user', id: 'usr_1' }] },
} as const;

const continuation = {
  id: 'cont_1',
  principal_id: 'p1',
  tenant_id: 't1',
  app_kind: 'aether',
  source_client: 'mobile_ios',
  surface: 'noesis',
  resource_references: [{ kind: 'user', id: 'usr_1' }],
  canonical_context: {},
  summary: { title: 'Noesis exploration', subtitle: '/noesis' },
  state_revision: 1,
  sensitivity: 'standard',
  updated_at: '2026-08-06T10:00:00Z',
};

const selection = {
  token: 'sel_abc123',
  tenant_scope: 't:t1',
  principal_id: 'p1',
  mode: 'explicit',
  resource_ids: ['usr_1'],
  created_at: '2026-08-07T00:00:00Z',
};

const eventOne = {
  id: 'ev_1',
  scope_key: 't:t1',
  seq: 1,
  change_type: 'session_revoked',
  resource_kind: 'session',
  resource_id: 'sess_1',
  revision: '3',
  created_at: '2026-08-07T00:00:00Z',
};

const eventTwo = {
  id: 'ev_2',
  scope_key: 't:t1',
  seq: 2,
  change_type: 'continuation_changed',
  resource_kind: 'continuation',
  resource_id: 'cont_2',
  revision: '1',
  created_at: '2026-08-07T01:00:00Z',
};

function renderPhone() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <ContinueOnPhone />
      </ToastProvider>
    </ThemeProvider>,
  );
}

function renderActivity() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <RecentActivity />
      </ToastProvider>
    </ThemeProvider>,
  );
}

function flagsOn() {
  vi.stubEnv('VITE_FEATURE_FLAGS', JSON.stringify({
    enableContinuations: true,
    enableClientSyncConsumption: true,
  }));
}

describe('Continue-on-phone + recent mobile activity surfaces (M5c)', () => {
  beforeEach(() => {
    queryCache.invalidatePrefix('continuations-recent-');
    queryCache.invalidatePrefix('client-sync');
    vi.unstubAllEnvs();
    Object.values(mocks).forEach(m => m.mockReset());
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe('feature flags default OFF (D8)', () => {
    it('renders nothing and fires no requests for ContinueOnPhone', () => {
      renderPhone();
      expect(screen.queryByText('Continue on phone')).not.toBeInTheDocument();
      expect(mocks.create).not.toHaveBeenCalled();
      expect(mocks.handoff).not.toHaveBeenCalled();
    });

    it('renders nothing and fires no requests for RecentActivity', () => {
      renderActivity();
      expect(screen.queryByText('Recent mobile activity')).not.toBeInTheDocument();
      expect(mocks.recent).not.toHaveBeenCalled();
      expect(mocks.clientSync).not.toHaveBeenCalled();
    });
  });

  describe('ContinueOnPhone (flag ON)', () => {
    beforeEach(() => {
      flagsOn();
      mocks.create.mockResolvedValue(continuation);
      mocks.handoff.mockResolvedValue(selection);
    });

    it('renders the affordance when the flag is on', () => {
      renderPhone();
      expect(screen.getByText('Continue on phone')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Create resume link' })).toBeInTheDocument();
    });

    it('materializes the exploration context into a continuation + handoff token', async () => {
      const user = userEvent.setup();
      renderPhone();
      await user.click(screen.getByRole('button', { name: 'Create resume link' }));

      await waitFor(() => {
        expect(mocks.create).toHaveBeenCalledTimes(1);
        expect(mocks.create).toHaveBeenCalledWith({
          source_client: 'web',
          surface: 'noesis',
          summary: { title: 'Noesis exploration', subtitle: expect.any(String) },
          canonical_context: {
            route: expect.any(String),
            filters: CONTEXT,
          },
          resource_references: [{ kind: 'user', id: 'usr_1' }],
          sensitivity: 'standard',
          freshness: 'live',
        });
      });
      expect(mocks.handoff).toHaveBeenCalledWith('cont_1', { mode: 'explicit', resource_ids: ['usr_1'] });

      expect(await screen.findByText('sel_abc123')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
    });

    it('surfaces a failure without a token when the handoff cannot mint', async () => {
      const user = userEvent.setup();
      mocks.handoff.mockResolvedValue(null);
      renderPhone();
      await user.click(screen.getByRole('button', { name: 'Create resume link' }));

      expect(await screen.findByText('The resume link could not be minted.')).toBeInTheDocument();
      expect(screen.queryByText('sel_abc123')).not.toBeInTheDocument();
    });
  });

  describe('RecentActivity (flag ON)', () => {
    beforeEach(() => {
      flagsOn();
    });

    it('lists recent continuations with surface + label', async () => {
      mocks.recent.mockResolvedValue({ continuations: [continuation] });
      mocks.clientSync.mockResolvedValue({ events: [], cursor: 'c0', has_more: false, reset: false });
      renderActivity();

      expect(await screen.findByText('Noesis exploration')).toBeInTheDocument();
      expect(screen.getByText('noesis')).toBeInTheDocument();
    });

    it('renders client-sync events with readable change-type labels', async () => {
      mocks.recent.mockResolvedValue({ continuations: [] });
      mocks.clientSync.mockResolvedValue({ events: [eventOne, eventTwo], cursor: 'c0', has_more: false, reset: false });
      renderActivity();

      expect(await screen.findByText('Session revoked')).toBeInTheDocument();
      expect(screen.getByText('Continuation updated')).toBeInTheDocument();
      expect(screen.getByText(/session · sess_1 · rev 3/)).toBeInTheDocument();
      expect(screen.getByText(/continuation · cont_2 · rev 1/)).toBeInTheDocument();
    });

    it('respects has_more and loads the next page from the returned cursor', async () => {
      const user = userEvent.setup();
      mocks.recent.mockResolvedValue({ continuations: [] });
      mocks.clientSync.mockImplementation((cursor?: string) =>
        cursor === 'c1'
          ? Promise.resolve({ events: [eventTwo], cursor: 'c2', has_more: false, reset: false })
          : Promise.resolve({ events: [eventOne], cursor: 'c1', has_more: true, reset: false }),
      );
      renderActivity();

      const loadMore = await screen.findByRole('button', { name: 'Load more' });
      await user.click(loadMore);

      expect(await screen.findByText('Continuation updated')).toBeInTheDocument();
      expect(screen.getByText('Session revoked')).toBeInTheDocument();
      expect(mocks.clientSync).toHaveBeenLastCalledWith('c1', 200);
      await waitFor(() => expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument());
    });

    it('discloses a backend feed reset', async () => {
      mocks.recent.mockResolvedValue({ continuations: [] });
      mocks.clientSync.mockResolvedValue({ events: [eventOne], cursor: 'c0', has_more: false, reset: true });
      renderActivity();

      expect(await screen.findByText(/Feed was reset/)).toBeInTheDocument();
    });

    it('renders empty states for both surfaces', async () => {
      mocks.recent.mockResolvedValue({ continuations: [] });
      mocks.clientSync.mockResolvedValue({ events: [], cursor: 'c0', has_more: false, reset: false });
      renderActivity();

      expect(await screen.findByText('No continuations yet')).toBeInTheDocument();
      expect(screen.getByText('No sync events')).toBeInTheDocument();
    });

    it('renders an error state when the continuation list fails', async () => {
      mocks.recent.mockRejectedValue(new Error('continuations offline'));
      mocks.clientSync.mockResolvedValue({ events: [], cursor: 'c0', has_more: false, reset: false });
      renderActivity();

      expect(await screen.findByText('Failed to load recent activity')).toBeInTheDocument();
    });
  });

  describe('sync change-type label mapping', () => {
    it('labels every one of the ten change types', () => {
      expect(Object.keys(SYNC_CHANGE_TYPE_LABELS)).toHaveLength(10);
      expect(SYNC_CHANGE_TYPE_LABELS.session_revoked).toBe('Session revoked');
      expect(SYNC_CHANGE_TYPE_LABELS.continuation_changed).toBe('Continuation updated');
      expect(SYNC_CHANGE_TYPE_LABELS.command_receipt_changed).toBe('Command receipt updated');
      expect(SYNC_CHANGE_TYPE_LABELS.installation_revoked).toBe('Installation revoked');
    });

    it('falls back to a humanised label for unknown change types', () => {
      expect(syncChangeTypeLabel('unknown_event_changed')).toBe('unknown event changed');
    });
  });
});
