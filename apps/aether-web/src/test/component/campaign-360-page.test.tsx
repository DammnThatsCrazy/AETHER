import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider, TimeProvider, queryCache } from '@aether/ui';
import { Campaign360Page } from '@aether-app/pages/campaigns/campaign-360-page';

const s = vi.hoisted(() => ({
  get: vi.fn(),
  externalRefs: vi.fn(),
  aliases: vi.fn(),
  overview: null as unknown,
  attribution: null as unknown,
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { campaigns: { get: s.get, externalRefs: s.externalRefs, aliases: s.aliases } },
}));
vi.mock('@aether-app/features/campaigns/use-campaign-360', () => {
  const q = (data: unknown) => ({ data, loading: false, error: null, refetch: vi.fn() });
  return {
    useCampaign360Overview: () => s.overview,
    useCampaign360Population: () => q({ items: [] }),
    useCampaign360Clusters: () => q({ items: [] }),
    useCampaign360Conversions: () => q({ items: [] }),
    useCampaign360Attribution: () => s.attribution,
  };
});
vi.mock('@aether-app/features/integrations', () => ({
  attentionReasonLabel: (r: string) => r,
  contextualReadiness: () => ({ connect: null, attention: [] }),
  useTenantIntegrationReadiness: () => ({ data: { items: [] }, isLoading: false, error: null }),
}));
vi.mock('@aether-app/features/targeting-intelligence', () => ({ CampaignTargetingIntelligenceTab: () => <div>TARGETING</div> }));
vi.mock('@aether-app/features/projection-360', () => ({ ProjectionSurfacePanel: () => <div>PROJECTION</div> }));

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.search}</div>;
}

function renderPage(path = '/campaigns/c1') {
  return render(
    <ThemeProvider>
      <TimeProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/campaigns/:id" element={<><Campaign360Page /><Where /></>} />
          </Routes>
        </MemoryRouter>
      </TimeProvider>
    </ThemeProvider>,
  );
}

const q = (data: unknown) => ({ data, loading: false, error: null, refetch: vi.fn() });

describe('Campaign 360', () => {
  beforeEach(() => {
    queryCache.invalidatePrefix('campaign:');
    s.get.mockResolvedValue({ id: 'c1', name: 'Spring Upgrade', status: 'active', channel: 'email', platform: 'hubspot' });
    s.overview = q({
      observed_count: 1000, resolved_count: 800, engaged_count: 400, converted_count: 100, attributed_count: 90,
      spend_usd: 2000, impressions: 50000, clicks: 1500, roas: 3.1, gross_attributed_revenue: 6200,
      net_attributed_revenue: 5800, touchpoint_count: 4200, identity_resolution_rate: 0.8, attribution_model: 'last_touch',
    });
    s.attribution = q({ dimension_rollups: [
      { actor_type: 'human', source_class: 'email', conversions: 70, attributed_net_revenue: 4000 },
      { actor_type: 'agent', source_class: 'paid_social', conversions: 30, attributed_net_revenue: 1800 },
    ] });
  });

  it('renders overview KPIs and a breakdown that follows the selected KPI', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Spring Upgrade' })).toBeInTheDocument();
    expect(screen.getByTestId('campaign-kpi-reached')).toHaveTextContent('1,000');
    expect(screen.getByText('80% of the people this campaign reached are resolved to a known profile.')).toBeInTheDocument();
    const breakdown = screen.getByTestId('campaign-breakdown');
    expect(within(breakdown).getByText('Cost per 1,000')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('campaign-kpi-conversions'));
    expect(within(breakdown).getByText('Value per conversion')).toBeInTheDocument();
    expect(within(breakdown).getByText('70')).toBeInTheDocument();
    await userEvent.click(within(breakdown).getByRole('button', { name: 'Actor' }));
    expect(within(breakdown).getByText('agent')).toBeInTheDocument();
  });

  it('opens the participant stage from the funnel', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Spring Upgrade' });
    await userEvent.click(within(screen.getByTestId('campaign-funnel')).getByRole('button', { name: /Converted/ }));
    expect(screen.getByTestId('where')).toHaveTextContent('tab=population');
    expect(screen.getByTestId('where')).toHaveTextContent('population=converted');
    expect(screen.getByText('No entities')).toBeInTheDocument();
  });

  it('shows source campaigns and marks a degraded read as unavailable', async () => {
    s.externalRefs.mockResolvedValue({ items: [{ platform: 'hubspot', external_campaign_id: 'em_4412', external_campaign_name: 'Upgrade Reminder', external_status: 'SENT' }], source_status: 'available' });
    s.aliases.mockResolvedValue({ items: [], source_status: 'missing' });
    renderPage('/campaigns/c1?tab=sources');
    expect(await screen.findByText('Upgrade Reminder')).toBeInTheDocument();
    expect(await screen.findByText('Campaign aliases are unavailable right now.')).toBeInTheDocument();
    expect(screen.queryByText(/No aliases recorded/)).not.toBeInTheDocument();
  });

  it('shows the campaign read failure instead of tabs', async () => {
    s.get.mockRejectedValue(new Error('offline'));
    renderPage();
    expect(await screen.findByText('Failed to load campaign')).toBeInTheDocument();
    expect(screen.queryByTestId('campaign-overview')).not.toBeInTheDocument();
  });
});
