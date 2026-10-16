import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { UsersPage } from '@aether-app/pages/users';
import type { UserRow } from '@aether-app/features/users/use-users';

type Read = { data: unknown; isLoading: boolean; error: string | null; refetch: () => void };
const settled = (data: unknown): Read => ({ data, isLoading: false, error: null, refetch: vi.fn() });

const s = vi.hoisted(() => ({
  users: [] as UserRow[],
  isLoading: false,
  error: null as string | null,
  reload: vi.fn(),
  setSearch: vi.fn(),
  summary: null as unknown,
  graph: null as unknown,
}));

vi.mock('@aether-app/features/users/use-users', () => ({
  useUsers: () => ({
    users: s.users,
    search: '',
    setSearch: s.setSearch,
    isLoading: s.isLoading,
    error: s.error,
    reload: s.reload,
  }),
}));

vi.mock('@aether-app/features/users/use-user-profile', () => ({
  useUserProfile: () => s.summary,
  useUserGraph: () => s.graph,
}));

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname}{loc.search}</div>;
}

function renderProfiles(route = '/users') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/users" element={<><UsersPage /><LocationProbe /></>} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

const ROWS: UserRow[] = [
  { id: 'u-old', displayName: 'Older Person', lastSeenAt: new Date(Date.now() - 5 * 86_400_000).toISOString(), trustScore: 0.4 },
  { id: 'u-new', displayName: 'Ada Lovelace', email: 'ada@example.com', lastSeenAt: new Date(Date.now() - 12 * 60_000).toISOString(), trustScore: 0.92, riskScore: 0.08, sessionCount30d: 14, platforms: ['web', 'ios'], churnRisk: 'low' },
];

const GRAPH = {
  nodes: [
    { entity_id: 'u-new', kind: 'human' },
    { entity_id: 'agent-1', kind: 'agent', actor_class: 'A', display_name: 'Atlas' },
    { entity_id: 'p-2', kind: 'human', display_name: 'Grace Hopper' },
  ],
  edges: [
    { edge_id: 'e1', from_entity_id: 'u-new', to_entity_id: 'agent-1', relation_type: 'delegates_to', interaction_class: 'H2A', confidence: 0.9, is_inferred: false },
    { edge_id: 'e2', from_entity_id: 'p-2', to_entity_id: 'u-new', relation_type: 'household', interaction_class: 'H2H', confidence: 0.7, is_inferred: false },
  ],
};

describe('Profiles', () => {
  beforeEach(() => {
    s.users = [];
    s.isLoading = false;
    s.error = null;
    s.reload = vi.fn();
    s.summary = settled({ snapshot: { entity: { displayLabel: 'Ada Lovelace', type: 'human', known: true }, counts: { agents: 1, wallets: 0, journey_chains: 3 } } });
    s.graph = settled(GRAPH);
  });

  it('shows a distinct loading state', () => {
    s.isLoading = true;
    renderProfiles();
    expect(screen.getByTestId('profiles-loading')).toBeInTheDocument();
    expect(screen.queryByText('No profiles found')).not.toBeInTheDocument();
  });

  it('says what is missing for a new workspace instead of showing sample profiles', () => {
    renderProfiles();
    expect(screen.getByText('No profiles found')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Connect your first source' })).toHaveAttribute('href', '/activation');
  });

  it('marks an unavailable list as unavailable, never as empty, and can retry', async () => {
    s.error = 'entities offline';
    renderProfiles();
    expect(screen.getByText('Failed to load profiles')).toBeInTheDocument();
    expect(screen.queryByText('No profiles found')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(s.reload).toHaveBeenCalled();
  });

  it('lists real profiles most recent first and expands a row in place with its relationships', async () => {
    s.users = ROWS;
    renderProfiles();
    const rows = screen.getAllByRole('button', { expanded: false });
    expect(within(rows[0]!).getByText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText(/ada@example.com · Active 12m ago/)).toBeInTheDocument();
    expect(screen.queryByTestId('profile-expanded')).not.toBeInTheDocument();

    await userEvent.click(rows[0]!);
    expect(screen.getByTestId('location')).toHaveTextContent('/users?profile=u-new');
    const expanded = screen.getByTestId('profile-expanded');
    expect(within(expanded).getByText('Atlas')).toBeInTheDocument();
    expect(within(expanded).getByText('Grace Hopper')).toBeInTheDocument();
    // Facts come from the summary snapshot and the graph read.
    expect(within(expanded).getByText('Journeys').previousSibling).toHaveTextContent('3');
    expect(within(expanded).getAllByText('Relationships')[0]!.previousSibling).toHaveTextContent('2');

    await userEvent.click(within(expanded).getByTestId('open-profile-360'));
    expect(screen.getByTestId('location')).toHaveTextContent('/users/u-new');
  });

  it('opens with the linked profile expanded at the top (?profile=)', () => {
    s.users = ROWS;
    renderProfiles('/users?profile=u-old');
    const list = screen.getByTestId('profiles-list');
    const first = list.querySelector('[data-profile-row]');
    expect(first).toHaveAttribute('data-profile-row', 'u-old');
    expect(within(first as HTMLElement).getByTestId('profile-expanded')).toBeInTheDocument();
  });

  it('keeps an unavailable relationship read distinct from an empty one', async () => {
    s.users = ROWS;
    s.graph = { data: null, isLoading: false, error: 'graph offline', refetch: vi.fn() };
    renderProfiles('/users?profile=u-new');
    expect(screen.getByText('Relationships are unavailable right now.')).toBeInTheDocument();
    expect(screen.queryByText('No relationships recorded in the graph yet.')).not.toBeInTheDocument();
  });

  it('maps the selected profile from its real graph in Relationship Map view', () => {
    s.users = ROWS;
    renderProfiles('/users?view=map&profile=u-new');
    const map = screen.getByTestId('profile-network-map');
    expect(map.querySelector('[data-network-node="agent-1"]')).not.toBeNull();
    expect(map.querySelector('[data-network-node="p-2"]')).not.toBeNull();
  });

  it('orders the Activity view by last seen', () => {
    s.users = ROWS;
    renderProfiles('/users?view=activity');
    const activity = screen.getByTestId('profiles-activity');
    const names = within(activity).getAllByRole('button').map(b => b.textContent ?? '');
    expect(names[0]).toContain('Ada Lovelace');
    expect(names[1]).toContain('Older Person');
  });
});
