import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { UserProfilePage } from '@aether-app/pages/user-profile';
import { profileNetwork, profileIdentity, timelineEvents } from '@aether-app/pages/user-profile/profile-model';

type Read = { data: unknown; isLoading: boolean; error: string | null; refetch: () => void };
const settled = (data: unknown): Read => ({ data, isLoading: false, error: null, refetch: vi.fn() });

const s = vi.hoisted(() => ({ reads: {} as Record<string, unknown> }));

vi.mock('@aether-app/features/users/use-user-profile', () => {
  const names = [
    'useUserProfile', 'useUserSessions', 'useUserDevices', 'useUserPlatforms', 'useUserJourneys',
    'useUserWallets', 'useUserFinancials', 'useUserRewards', 'useUserIdentifiers', 'useUserIntelligence',
    'useUserBehavioral', 'useUserWhyExplain', 'useUserGraph', 'useUserSemantic', 'useUserSocialIntelligence',
    'useUserRecommendations', 'useUserTier', 'useUserAssetComposition', 'useUserPnl', 'useUserTradingProfile',
    'useUserFunnel', 'useUserTimeToConvert', 'useUserJourneyEconomics', 'useUserDevicePerformance',
    'useUserProtocolMetrics', 'useUserGovernanceActivity', 'useUserQuality', 'useUserDataFreshness',
    'useUserWeb2Profile', 'useUserTimeline',
  ];
  return Object.fromEntries(names.map(n => [n, () => s.reads[n] ?? { data: undefined, isLoading: false, error: null, refetch: () => undefined }]));
});
vi.mock('@aether-app/features/profile360', () => ({ ProfileExplorationPanel: () => null }));
vi.mock('@aether-app/features/identity/Profile360IdentityPanel', () => ({ Profile360IdentityPanel: () => <div>IDENTITY PANEL</div> }));
vi.mock('@aether-app/components/outcome-ledger-panel', () => ({ OutcomeLedgerPanel: () => <div>OUTCOME LEDGER</div> }));
vi.mock('@aether-app/features/journey', () => ({
  useUnifiedJourney: () => ({ steps: [], loading: false, error: null }),
  TouchpointEvidenceInspector: () => null,
}));
vi.mock('@aether-app/features/integrations', () => ({
  useTenantIntegrationReadiness: () => ({ data: undefined, isLoading: true, error: null }),
  contextualReadiness: () => ({ connect: null, attention: [] }),
  attentionReasonLabel: (v: string) => v,
}));
vi.mock('@aether-app/lib/api/endpoints', () => ({ api: {} }));

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname}{loc.search}</div>;
}

function renderProfile(route = '/users/u1') {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path="/users/:id" element={<><UserProfilePage /><LocationProbe /></>} />
            <Route path="*" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

const SUMMARY = {
  entity_id: 'u1',
  snapshot: {
    entity: { id: 'u1', type: 'human', displayLabel: 'Ada Lovelace', known: true, timestamps: { createdAt: '2023-03-01T00:00:00Z' } },
    counts: { agents: 2, wallets: 1, journey_chains: 4, agent_executions: 7, active_delegations_granted: 1, active_delegations_received: 0 },
  },
  last_seen_at: new Date(Date.now() - 12 * 60_000).toISOString(),
  trust_score: 0.92,
};

const GRAPH = {
  nodes: [
    { entity_id: 'u1', kind: 'human' },
    { entity_id: 'agent-1', kind: 'agent', actor_class: 'A', display_name: 'Atlas Shopping Agent', trust_score: 0.8 },
    { entity_id: 'p-2', kind: 'human', display_name: 'Grace Hopper' },
    { entity_id: 'w-1', kind: 'wallet', display_name: '0xabc' },
  ],
  edges: [
    { edge_id: 'e1', from_entity_id: 'u1', to_entity_id: 'agent-1', to_kind: 'agent', relation_type: 'delegates_to', interaction_class: 'H2A', confidence: 0.9, is_inferred: false },
    { edge_id: 'e2', from_entity_id: 'p-2', to_entity_id: 'u1', from_kind: 'human', relation_type: 'household', interaction_class: 'H2H', confidence: 0.88, is_inferred: false },
    { edge_id: 'e3', from_entity_id: 'u1', to_entity_id: 'w-1', to_kind: 'wallet', relation_type: 'owns', interaction_class: 'H2S', confidence: 0.6, is_inferred: true },
  ],
};

describe('Profile 360', () => {
  beforeEach(() => {
    s.reads = { useUserProfile: settled(SUMMARY) };
  });

  it('renders the identity hero from the real summary and wires its actions', async () => {
    renderProfile();
    const hero = screen.getByTestId('profile-hero');
    expect(within(hero).getByRole('heading', { name: 'Ada Lovelace' })).toBeInTheDocument();
    expect(within(hero).getByText('Human · Known profile')).toBeInTheDocument();
    expect(within(hero).getByText('Trust 92')).toBeInTheDocument();
    expect(within(hero).getByText('2 agents')).toBeInTheDocument();
    expect(within(hero).getByText(/active 12m ago/)).toBeInTheDocument();
    expect(within(hero).getByText('since 2023')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Profiles/ })).toHaveAttribute('href', '/users?profile=u1');

    await userEvent.click(screen.getByTestId('profile-view-journey'));
    expect(screen.getByTestId('location')).toHaveTextContent('/users/u1/journey');
  });

  it('opens the profile in the graph workspace', async () => {
    renderProfile();
    await userEvent.click(screen.getByTestId('profile-open-graph'));
    expect(screen.getByTestId('location')).toHaveTextContent('/explore?entity=u1');
  });

  it('shows an unavailable profile as an error, not an empty profile', () => {
    s.reads.useUserProfile = { data: null, isLoading: false, error: 'profile backend offline', refetch: vi.fn() };
    renderProfile();
    expect(screen.getByText('Failed to load user profile')).toBeInTheDocument();
    expect(screen.queryByTestId('profile-hero')).not.toBeInTheDocument();
  });

  it('gives honest empty states on the overview when nothing is reported yet', () => {
    s.reads.useUserProfile = settled({ snapshot: SUMMARY.snapshot });
    renderProfile();
    expect(screen.getByText(/Session and event totals are not reported/)).toBeInTheDocument();
    expect(screen.getByText('No relationships are recorded in the graph for this profile yet.')).toBeInTheDocument();
    expect(screen.getByText('No events have been recorded for this profile yet.')).toBeInTheDocument();
    expect(screen.getByText(/The profile summary lists 2 owned agent configurations/)).toBeInTheDocument();
    expect(screen.getByText('No semantic signal yet')).toBeInTheDocument();
  });

  it('marks an unavailable graph read as unavailable on the overview', () => {
    s.reads.useUserGraph = { data: null, isLoading: false, error: 'graph offline', refetch: vi.fn() };
    renderProfile();
    const card = screen.getByTestId('profile-network-card');
    expect(within(card).getByText(/unavailable right now/)).toBeInTheDocument();
    expect(screen.queryByText('No relationships are recorded in the graph for this profile yet.')).not.toBeInTheDocument();
  });

  it('summarises network, agents, identity and recent activity from real reads', () => {
    s.reads.useUserGraph = settled(GRAPH);
    s.reads.useUserIdentifiers = settled({ emails: ['ada@example.com', 'ada@work.example'], devices: ['d_1'] });
    s.reads.useUserTimeline = settled({ user_id: 'u1', count: 1, events: [{ event_id: 'ev1', event_type: 'purchase', timestamp: new Date(Date.now() - 5 * 60_000).toISOString(), source: 'shopify' }] });
    renderProfile();
    expect(within(screen.getByTestId('profile-network-card')).getByText('Network · 3 relationships')).toBeInTheDocument();
    expect(within(screen.getByTestId('profile-agents-card')).getByText('Atlas Shopping Agent')).toBeInTheDocument();
    expect(within(screen.getByTestId('profile-identity-card')).getByText('ada@example.com')).toBeInTheDocument();
    expect(within(screen.getByTestId('profile-identity-card')).getByText('+1')).toBeInTheDocument();
    expect(within(screen.getByTestId('profile-recent-activity')).getByText('purchase')).toBeInTheDocument();
  });

  it('switches tabs through the URL and keeps legacy tab links working', async () => {
    s.reads.useUserGraph = settled(GRAPH);
    renderProfile('/users/u1?tab=relationships');
    expect(screen.getByRole('tab', { name: 'Network' })).toHaveAttribute('aria-selected', 'true');
    const map = screen.getByTestId('profile-network-map');
    expect(map.querySelector('[data-network-node="agent-1"]')).not.toBeNull();
    // Inferred links are hidden until asked for.
    expect(map.querySelector('[data-network-node="w-1"]')).toBeNull();
    await userEvent.click(within(map).getByRole('button', { name: /Show 1 inferred/ }));
    expect(map.querySelector('[data-network-node="w-1"]')).not.toBeNull();

    await userEvent.click(map.querySelector('[data-network-node="p-2"]') as HTMLElement);
    const strip = screen.getByTestId('network-selection');
    expect(within(strip).getByText(/household · H2H · confidence 88%/)).toBeInTheDocument();
    await userEvent.click(within(strip).getByRole('button', { name: /Open Profile 360/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('/users/p-2');
  });

  it('lists agents acting for the profile with links to Agent 360', async () => {
    s.reads.useUserGraph = settled(GRAPH);
    renderProfile();
    await userEvent.click(screen.getByRole('tab', { name: 'Agents' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/users/u1?tab=agents');
    const agents = screen.getByTestId('profile-agents');
    expect(within(agents).getByText('Agent executions').nextSibling).toHaveTextContent('7');
    expect(within(agents).getByText(/delegates to · H2A · 90%/)).toBeInTheDocument();
    await userEvent.click(within(agents).getByRole('button', { name: /Open agent/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('/agents/agent-1');
  });

  it('shows the event timeline with type filters', async () => {
    const now = Date.now();
    s.reads.useUserTimeline = settled({
      events: [
        { event_id: 'a', event_type: 'page_view', timestamp: new Date(now - 60_000).toISOString() },
        { event_id: 'b', event_type: 'purchase', timestamp: new Date(now - 120_000).toISOString() },
        { event_id: 'c', event_type: 'page_view', timestamp: new Date(now - 180_000).toISOString() },
      ],
    });
    renderProfile('/users/u1?tab=timeline');
    const tl = screen.getByTestId('profile-timeline');
    expect(within(tl).getByText('Timeline · 3 latest events')).toBeInTheDocument();
    expect(within(tl).getAllByRole('listitem')).toHaveLength(3);
    await userEvent.click(within(tl).getByRole('button', { name: 'purchase · 1' }));
    expect(within(tl).getAllByRole('listitem')).toHaveLength(1);
  });

  it('keeps the journey explorer reachable from the Journeys tab', () => {
    renderProfile('/users/u1?tab=journeys');
    expect(screen.getByTestId('profile-journey-explorer-link')).toHaveAttribute('href', '/users/u1/journey');
    expect(screen.getByText('No journeys')).toBeInTheDocument();
  });

  it('keeps every legacy signal reachable under More signals', async () => {
    renderProfile();
    for (const name of ['Sessions & Devices', 'Communications', 'Social', 'Web3 Wallets', 'Financials', 'Behavior', 'Attribution', 'Outcomes', 'DeFi', 'Funnel', 'Protocols', 'Insights']) {
      expect(screen.getByRole('tab', { name })).toBeInTheDocument();
    }
    await userEvent.click(screen.getByRole('tab', { name: 'Outcomes' }));
    expect(screen.getByText('OUTCOME LEDGER')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Identity' }));
    expect(screen.getByText('IDENTITY PANEL')).toBeInTheDocument();
  });
});

describe('profile-model', () => {
  it('reads the canonical summary snapshot and the flat legacy shape', () => {
    expect(profileIdentity(SUMMARY, 'u1')).toMatchObject({ name: 'Ada Lovelace', kind: 'human', known: true, counts: { agents: 2, wallets: 1, journeys: 4 } });
    const flat = profileIdentity({ display_name: 'Grace', last_seen_at: '2026-01-01T00:00:00Z' }, 'u2');
    expect(flat).toMatchObject({ name: 'Grace', kind: null, known: null, counts: { agents: null, wallets: null, journeys: null } });
    expect(profileIdentity({}, 'u3')).toMatchObject({ name: 'u3', nameIsId: true });
  });

  it('builds the ego network without the root and groups neighbours', () => {
    const n = profileNetwork(GRAPH, 'u1');
    expect(n.nodes.map(x => [x.id, x.group])).toEqual([['agent-1', 'agents'], ['p-2', 'people'], ['w-1', 'assets']]);
    expect(n.links).toHaveLength(3);
    expect(n.links.find(l => l.other === 'w-1')?.inferred).toBe(true);
    expect(n.byClass[0]).toEqual({ cls: 'H2A', count: 1 });
    expect(profileNetwork(undefined, 'u1')).toEqual({ nodes: [], links: [], byClass: [] });
  });

  it('normalises timeline events newest first', () => {
    const ev = timelineEvents({ events: [
      { event_type: 'a', timestamp: '2026-01-01T00:00:00Z' },
      { event_type: 'b', timestamp: '2026-02-01T00:00:00Z' },
    ] });
    expect(ev.map(e => e.type)).toEqual(['b', 'a']);
  });
});
