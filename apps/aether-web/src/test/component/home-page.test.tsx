import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider, queryCache } from '@aether/ui';
import { HomePage } from '@aether-app/pages/home/home-page';

const settled = (data: unknown) => ({ data, isLoading: false, error: null, refetch: vi.fn() });

const s = vi.hoisted(() => ({
  activation: null as unknown,
  readiness: null as unknown,
  integrations: null as unknown,
  summary: null as unknown,
  campaigns: { campaigns: [] as unknown[], total: 0 },
}));

vi.mock('@aether-app/components/outcome-ledger-panel', () => ({ OutcomeLedgerPanel: () => <div>OUTCOME LEDGER</div> }));
vi.mock('@aether-app/components/decision-intelligence-panel', () => ({ DecisionIntelligencePanel: () => <div>DECISION INTELLIGENCE</div> }));
vi.mock('@aether-app/features/auth', () => ({ useAuth: () => ({ user: { id: 't1', displayName: 'Owner' } }) }));
vi.mock('@aether-app/features/activation/use-activation', () => ({ useActivationStatus: () => s.activation }));
vi.mock('@aether-app/features/activation/use-tenant-readiness', () => ({ useTenantReadiness: () => s.readiness }));
vi.mock('@aether-app/features/integrations', () => ({ useTenantIntegrations: () => s.integrations }));
vi.mock('@aether-app/features/onboarding/use-workspace-setup', () => ({
  useAnalyticsSummary: () => s.summary,
  useOrganizationProfile: () => settled({ name: 'Northpeak' }),
  useTenantApiKeys: () => settled({ api_keys: [{ id: 'k1' }] }),
}));
vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { campaigns: { list: () => Promise.resolve(s.campaigns) } },
}));

function renderHome() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Home', () => {
  beforeEach(() => {
    queryCache.invalidate('home:campaigns');
    s.activation = settled({ state: 'complete', waiting_reason: null });
    s.readiness = settled({ tenant_id: 't', ready: false, blocking: [], checks: [] });
    s.integrations = settled({ items: [] });
    s.summary = settled({ total_events: 0, unique_users: 0, total_sessions: 0, top_event_types: [] });
    s.campaigns = { campaigns: [], total: 0 };
  });

  it('says what is missing instead of showing illustrative data for a new workspace', async () => {
    renderHome();
    expect(screen.getByText('Your graph is waiting for its first events')).toBeInTheDocument();
    expect(screen.getByText(/No events in the last 24 hours/)).toBeInTheDocument();
    expect(screen.getByText('No sources connected yet.')).toBeInTheDocument();
    expect(await screen.findByText(/No campaigns yet/)).toBeInTheDocument();
    expect(screen.getByText('Nothing needs you right now.')).toBeInTheDocument();
  });

  it('renders real reads: event mix, connections with marks, attention items and campaigns', async () => {
    s.activation = settled({ state: 'waiting_for_event', waiting_reason: 'no_events_received_yet' });
    s.summary = settled({
      total_events: 1520,
      unique_users: 88,
      total_sessions: 140,
      top_event_types: [{ event_type: 'page_view', count: 1200 }, { event_type: 'purchase', count: 320 }],
    });
    s.integrations = settled({
      items: [
        { id: 'a', family: 'shopify', display_name: 'Shopify', connected: true, enabled: true, sync_status: 'succeeded', last_synced_at: new Date().toISOString(), name: null, experience_category: null, secret_configured: true },
        { id: 'b', family: 'hubspot', display_name: 'HubSpot', connected: false, enabled: true, sync_status: 'sync_failed', last_synced_at: null, name: null, experience_category: null, secret_configured: true },
      ],
    });
    s.readiness = settled({
      tenant_id: 't',
      ready: false,
      blocking: [],
      checks: [{ name: 'events_received', status: 'passed' }, { name: 'identity_resolution_verified', status: 'failed' }],
    });
    s.campaigns = { campaigns: [{ id: 'c1', name: 'Spring Upgrade', status: 'active', platform: 'meta', impressions: 4200 }], total: 1 };

    renderHome();
    expect(screen.getByText('Your graph is building from live events')).toBeInTheDocument();
    expect(within(screen.getByTestId('home-kpis')).getByText('1.5k')).toBeInTheDocument();
    expect(screen.getByText('page_view')).toBeInTheDocument();
    expect(screen.getByText(/79%/)).toBeInTheDocument();

    const attention = screen.getByTestId('home-attention');
    expect(within(attention).getByText('Finish workspace setup')).toBeInTheDocument();
    expect(within(attention).getByText('HubSpot sync needs attention')).toBeInTheDocument();
    expect(within(attention).getByText('identity resolution verified failed')).toBeInTheDocument();

    const connections = screen.getByTestId('home-connections');
    expect(within(connections).getByText('Shopify')).toBeInTheDocument();
    expect(connections.querySelector('[data-provider="shopify"][data-provider-mark="reviewed-local"]')).not.toBeNull();

    expect(await screen.findByText('Spring Upgrade')).toBeInTheDocument();
    expect(document.querySelector('[data-stage="identity_resolution_verified"]')).toHaveAttribute('data-stage-status', 'failed');
  });
});
