import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider, queryCache } from '@aether/ui';
import { HomePage } from '@aether-app/pages/home/home-page';
import { economicKpis, sinceVisit } from '@aether-app/pages/home/home-model';

const settled = (data: unknown) => ({ data, isLoading: false, error: null, refetch: vi.fn() });
const failed = (error: string) => ({ data: null, isLoading: false, error, refetch: vi.fn() });

const s = vi.hoisted(() => ({
  activation: null as unknown,
  readiness: null as unknown,
  integrations: null as unknown,
  summary: null as unknown,
  inventory: null as unknown,
  findings: null as unknown,
  campaigns: { campaigns: [] as unknown[], total: 0 } as unknown,
  economic: null as unknown,
  economicCalls: [] as string[],
}));

vi.mock('@aether-app/features/auth', () => ({ useAuth: () => ({ user: { id: 't1', displayName: 'Owner' } }) }));
vi.mock('@aether-app/features/activation/use-activation', () => ({ useActivationStatus: () => s.activation }));
vi.mock('@aether-app/features/activation/use-tenant-readiness', () => ({ useTenantReadiness: () => s.readiness }));
vi.mock('@aether-app/features/integrations', () => ({ useTenantIntegrations: () => s.integrations }));
vi.mock('@aether-app/features/agent-access', () => ({
  useAccessInventory: () => s.inventory,
  useCapabilityRiskFindings: () => s.findings,
}));
vi.mock('@aether-app/features/onboarding/use-workspace-setup', () => ({
  useAnalyticsSummary: () => s.summary,
  useOrganizationProfile: () => settled({ name: 'Northpeak', tenant_id: 't_np' }),
  useTenantApiKeys: () => settled({ api_keys: [{ id: 'k1' }] }),
}));
vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    campaigns: { list: () => Promise.resolve(s.campaigns) },
    economic: {
      overview: (window: string) => {
        s.economicCalls.push(window);
        return s.economic instanceof Error ? Promise.reject(s.economic) : Promise.resolve(s.economic);
      },
    },
  },
}));

const emptyInventory = { summary_known: true, observed_any: false, missing_inputs: [], counts: {} };
const emptyFindings = { items: [], counts: { total: 0, by_risk_level: {}, by_code: {} } };
const noValue = {
  tenant_id: 't',
  campaign_spend: { usd_amount: 0 },
  attributed_revenue: { usd_amount: 0 },
  warnings: [{ code: 'NO_SPEND_DATA', message: '', severity: 'warning' }, { code: 'NO_ATTRIBUTION_DATA', message: '', severity: 'info' }],
};

function renderHome() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function populate() {
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
      { id: 'c', family: 'klaviyo', display_name: 'Klaviyo', connected: true, enabled: true, sync_status: 'succeeded', last_synced_at: null, name: null, experience_category: null, secret_configured: true },
    ],
  });
  s.readiness = settled({
    tenant_id: 't',
    ready: false,
    blocking: [],
    recorded_at: new Date().toISOString(),
    checks: [{ name: 'events_received', status: 'passed' }, { name: 'identity_resolution_verified', status: 'failed' }],
  });
  s.campaigns = {
    campaigns: [
      { id: 'c1', name: 'Spring Upgrade', status: 'active', platform: 'shopify', impressions: 4200, cost_usd: 1000, revenue_usd: 4500, created_at: new Date().toISOString() },
      { id: 'c2', name: 'Winback', status: 'paused', platform: 'google_ads' },
    ],
    total: 2,
  };
  s.economic = {
    tenant_id: 't',
    campaign_spend: { usd_amount: 100_000 },
    attributed_revenue: { usd_amount: 284_000 },
    warnings: [{ code: 'PARTIAL_SOURCE_COVERAGE', message: '', severity: 'info' }],
  };
  s.inventory = settled({
    summary_known: true,
    observed_any: true,
    complete: true,
    missing_inputs: [],
    summary: '12 agents connect to 3 servers.',
    counts: { agents: 12, capabilities: 30, edges_connects_to: 6, edges_exposes: 3, edges_authorized_for: 1, authorizations_active: 4 },
  });
  s.findings = settled({
    items: [{ code: 'unbounded_spend_capability', risk_level: 'high', summary: 'A purchasing capability has no spend ceiling' }],
    counts: { total: 1, scope: 'all_matching_findings', by_risk_level: { high: 1 }, by_code: {} },
  });
}

describe('Home', () => {
  beforeEach(() => {
    window.localStorage.clear();
    queryCache.invalidate('home:campaigns');
    for (const w of ['24h', '7d', '30d', '90d']) queryCache.invalidate(`home:economic:${w}`);
    s.activation = settled({ state: 'complete', waiting_reason: null });
    s.readiness = settled({ tenant_id: 't', ready: false, blocking: [], checks: [] });
    s.integrations = settled({ items: [] });
    s.summary = settled({ total_events: 0, unique_users: 0, total_sessions: 0, top_event_types: [] });
    s.inventory = settled(emptyInventory);
    s.findings = settled(emptyFindings);
    s.campaigns = { campaigns: [], total: 0 };
    s.economic = noValue;
    s.economicCalls = [];
  });

  it('keeps the frame title and section order', async () => {
    renderHome();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Here is what changed across your network');
    await screen.findByText(/No campaigns yet/);
    const order = ['home-controls', 'home-query', 'home-since', 'home-kpis', 'home-hero', 'home-campaigns', 'home-relationships', 'home-risk', 'home-attention', 'home-connections', 'home-rollup-people', 'home-rollup-where', 'home-domains'];
    const nodes = order.map(id => screen.getByTestId(id));
    for (let i = 1; i < nodes.length; i++) {
      expect(nodes[i - 1]!.compareDocumentPosition(nodes[i]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it('says what is missing instead of showing illustrative data for a new workspace', async () => {
    renderHome();
    expect(screen.getByText('Your graph is waiting for its first events')).toBeInTheDocument();
    expect(screen.getByText(/No events in the last 24 hours\. Install/)).toBeInTheDocument();
    expect(screen.getByText(/No sources connected yet\./)).toBeInTheDocument();
    expect(await screen.findByText(/No campaigns yet/)).toBeInTheDocument();
    expect(screen.getByText('Nothing needs you right now.')).toBeInTheDocument();
    expect(screen.getByTestId('home-subline')).toHaveTextContent('Nothing needs your attention right now');
    expect(screen.getByText(/No agent relationships observed yet/)).toBeInTheDocument();
    expect(screen.getByText(/No capability risk findings/)).toBeInTheDocument();
    expect(screen.getByText(/No activity recorded yet/)).toBeInTheDocument();
    expect(screen.getByText(/first visit on this device/)).toBeInTheDocument();
    // No attribution / no spend: revenue and ROAS say so instead of "$0".
    await waitFor(() => expect(within(screen.getByTestId('kpi-revenue')).getByText('no attribution credits yet')).toBeInTheDocument());
    expect(within(screen.getByTestId('kpi-roas')).getByText('no spend reported')).toBeInTheDocument();
    expect(within(screen.getByTestId('home-kpis')).queryByText(/\$0/)).not.toBeInTheDocument();
  });

  it('renders KPIs without a backing read as "not reported"', () => {
    renderHome();
    for (const id of ['kpi-orders', 'kpi-new-users', 'kpi-aov', 'kpi-repeat']) {
      const tile = screen.getByTestId(id);
      expect(tile).toHaveAttribute('data-not-reported', 'true');
      expect(within(tile).getByText('not reported')).toBeInTheDocument();
    }
  });

  it('marks unavailable reads as unavailable, never as empty', async () => {
    s.summary = failed('analytics offline');
    s.integrations = failed('integrations offline');
    s.readiness = failed('readiness offline');
    s.inventory = failed('inventory offline');
    s.findings = failed('findings offline');
    s.economic = new Error('economic offline');
    renderHome();
    expect(screen.getByText('Event totals are unavailable right now.')).toBeInTheDocument();
    expect(screen.getByText('Connections are unavailable right now.')).toBeInTheDocument();
    expect(screen.getByText('Readiness checks are temporarily unavailable.')).toBeInTheDocument();
    expect(screen.getByText('Relationship totals are unavailable right now.')).toBeInTheDocument();
    expect(screen.getByText('Risk findings are unavailable right now.')).toBeInTheDocument();
    expect(screen.queryByText(/No sources connected yet\./)).not.toBeInTheDocument();
    expect(document.querySelector('[data-stage="events_received"]')).toHaveAttribute('data-stage-status', 'unknown');
    await waitFor(() => expect(within(screen.getByTestId('kpi-revenue')).getByText('unavailable right now')).toBeInTheDocument());
  });

  it('distinguishes loading from empty for the story cards', () => {
    s.inventory = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    s.findings = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    renderHome();
    expect(screen.getByText('Loading relationships…')).toBeInTheDocument();
    expect(screen.getByText('Loading risk findings…')).toBeInTheDocument();
    expect(screen.queryByText(/No agent relationships observed yet/)).not.toBeInTheDocument();
  });

  it('renders real reads: KPIs, event mix, story cards, attention items, connections and campaigns', async () => {
    populate();
    renderHome();
    expect(screen.getByText('Your graph is building from live events')).toBeInTheDocument();
    expect(within(screen.getByTestId('home-growth')).getByText('1.5k')).toBeInTheDocument();
    expect(within(screen.getByTestId('home-hero')).getByText('page_view')).toBeInTheDocument();
    expect(within(screen.getByTestId('home-hero')).getByText('79%')).toBeInTheDocument();
    expect(screen.getByText(/Growth over time is not reported yet/)).toBeInTheDocument();
    expect(screen.getByText(/Representative journeys are not reported/)).toBeInTheDocument();

    // Revenue and ROAS come from /v1/economic/overview.
    await waitFor(() => expect(within(screen.getByTestId('kpi-revenue')).getByText('$284K')).toBeInTheDocument());
    expect(within(screen.getByTestId('kpi-roas')).getByText('2.8x')).toBeInTheDocument();
    expect(within(screen.getByTestId('kpi-roas')).getByText('ad spend $100K')).toBeInTheDocument();
    expect(s.economicCalls).toContain('7d');

    const attention = screen.getByTestId('home-attention');
    expect(within(attention).getByText('Finish workspace setup')).toBeInTheDocument();
    expect(within(attention).getByText('HubSpot sync needs attention')).toBeInTheDocument();
    expect(within(attention).getByText('identity resolution verified failed')).toBeInTheDocument();
    expect(screen.getByTestId('home-subline')).toHaveTextContent('3 things are worth your attention');

    expect(within(screen.getByTestId('home-relationships')).getByText('12 agents reach 30 capabilities')).toBeInTheDocument();
    expect(within(screen.getByTestId('home-risk')).getByText('A purchasing capability has no spend ceiling')).toBeInTheDocument();
    expect(within(screen.getByTestId('home-risk')).getByText('Risk · elevated')).toBeInTheDocument();

    const connections = screen.getByTestId('home-connections');
    expect(within(connections).getByText('Shopify')).toBeInTheDocument();
    expect(connections.querySelector('[data-provider="shopify"][data-provider-mark="reviewed-local"]')).not.toBeNull();
    expect(within(connections).getByText('1 delayed')).toBeInTheDocument();

    expect(await screen.findByText('Spring Upgrade')).toBeInTheDocument();
    expect(document.querySelector('[data-stage="identity_resolution_verified"]')).toHaveAttribute('data-stage-status', 'failed');

    // Campaign sources show the provider's name, never the raw platform token.
    const table = screen.getByTestId('home-campaigns');
    expect(within(table).getAllByText('Shopify').length).toBeGreaterThan(0);
    expect(within(table).getByText('Google Ads')).toBeInTheDocument();
    expect(within(table).queryByText('google_ads')).not.toBeInTheDocument();
    expect(within(table).queryByText('shopify')).not.toBeInTheDocument();
    expect(within(table).getByText('across 2 platforms', { exact: false })).toBeInTheDocument();

    // Spend and ROAS when the row reports them; "—" (not reported) otherwise; trends never drawn.
    const spring = table.querySelector('[data-campaign-row="c1"]') as HTMLElement;
    expect(within(spring).getByText('$1K')).toBeInTheDocument();
    expect(within(spring).getByText('4.5x')).toBeInTheDocument();
    const winback = table.querySelector('[data-campaign-row="c2"]') as HTMLElement;
    expect(within(winback).getAllByText('—').length).toBeGreaterThanOrEqual(3);
    expect(within(table).getByTestId('home-campaigns-note')).toHaveTextContent('trend lines need a per-campaign series');

    // Activity lists real dated moments.
    const activity = screen.getByTestId('home-activity');
    expect(within(activity).getByText('Spring Upgrade imported')).toBeInTheDocument();
    expect(within(activity).getByText('Graph checks ran')).toBeInTheDocument();
  });

  it('keeps controls without a backing read disabled and never fakes an interpretation', async () => {
    populate();
    renderHome();
    expect(screen.getByTestId('home-control-lens')).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByTestId('home-control-perspective')).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByRole('textbox', { name: 'Ask across your network' })).toBeDisabled();
    expect(within(screen.getByTestId('home-query')).getByText(/query interpretation is not available/)).toBeInTheDocument();
  });

  it('drives the economic window from the Time control', async () => {
    populate();
    renderHome();
    await waitFor(() => expect(s.economicCalls).toContain('7d'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Time window for revenue and ROAS' }), { target: { value: '30d' } });
    await waitFor(() => expect(s.economicCalls).toContain('30d'));
    await waitFor(() => expect(within(screen.getByTestId('kpi-revenue')).getByText('attributed · last 30 days')).toBeInTheDocument());
  });

  it('summarises changes since the last visit and records this visit', async () => {
    populate();
    const before = Date.now() - 60 * 60_000;
    window.localStorage.setItem('aether.home.lastVisit:t_np', String(before));
    renderHome();
    const line = screen.getByTestId('home-since');
    await waitFor(() => expect(within(line).getByText('1 campaign imported')).toBeInTheDocument());
    expect(within(line).getByText('1 connection synced')).toBeInTheDocument();
    expect(within(line).getByText('1 connection failing')).toBeInTheDocument();
    expect(Number(window.localStorage.getItem('aether.home.lastVisit:t_np'))).toBeGreaterThan(before);
  });

  it('collapses rollups to two rows until expanded', () => {
    populate();
    renderHome();
    const where = screen.getByTestId('home-rollup-where');
    const performance = screen.getByTestId('home-connections');
    expect(within(performance).queryByText('Klaviyo')).not.toBeInTheDocument();
    fireEvent.click(within(performance).getByRole('button', { name: /Show all 3/ }));
    expect(within(performance).getByText('Klaviyo')).toBeInTheDocument();
    expect(within(where).getByText('page_view')).toBeInTheDocument();
  });

  it('no longer hosts the legacy outcome, decision or model-routing panels (they live on Value)', async () => {
    vi.stubEnv('VITE_FEATURE_FLAGS', JSON.stringify({ enableModelHarness: true }));
    renderHome();
    await screen.findByText(/No campaigns yet/);
    expect(screen.queryByText('Model routing preference')).not.toBeInTheDocument();
    vi.unstubAllEnvs();
    expect(screen.queryByText('Outcome Ledger')).not.toBeInTheDocument();
    expect(screen.queryByText('Decision intelligence feed')).not.toBeInTheDocument();
    expect(screen.queryByText('Playbooks')).not.toBeInTheDocument();
    expect(document.querySelector('.ae-legacy')).toBeNull();
  });
});

describe('home-model', () => {
  it('reports revenue and ROAS only when the overview carries them', () => {
    expect(economicKpis(null)).toBeNull();
    expect(economicKpis(noValue as never)).toMatchObject({ revenue: null, spend: null, roas: null, noAttribution: true, noSpend: true });
    expect(economicKpis({ tenant_id: 't', attributed_revenue: { usd_amount: 500 }, campaign_spend: { usd_amount: 0 }, warnings: [] } as never))
      .toMatchObject({ revenue: 500, spend: null, roas: null });
    expect(economicKpis({ tenant_id: 't', attributed_revenue: { usd_amount: 500 }, campaign_spend: { usd_amount: 250 }, warnings: [{ code: 'COMPUTATION_ERROR', message: '', severity: 'error' }] } as never))
      .toMatchObject({ revenue: null, roas: null, failed: true });
    expect(economicKpis({ tenant_id: 't', attributed_revenue: { usd_amount: 500 }, campaign_spend: { usd_amount: 250 } } as never))
      .toMatchObject({ revenue: 500, spend: 250, roas: 2 });
  });

  it('counts only changes after the last visit', () => {
    const since = Date.parse('2026-10-01T00:00:00Z');
    const out = sinceVisit(
      since,
      [{ created_at: '2026-10-02T00:00:00Z' }, { created_at: '2026-09-01T00:00:00Z' }, {}],
      [],
      '2026-09-30T00:00:00Z',
    );
    expect(out).toEqual({ campaignsImported: 1, connectionsSynced: 0, connectionsFailing: 0, checksRan: false });
  });
});
