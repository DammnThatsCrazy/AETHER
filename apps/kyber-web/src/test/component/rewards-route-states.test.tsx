import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RewardsHealthPage } from '@kyber/pages/rewards/rewards-health-page';
import { RewardsDrilldownPage } from '@kyber/pages/rewards/rewards-drilldown-page';

const mocks = vi.hoisted(() => ({
  rewardsHealth: vi.fn(),
  campaigns: vi.fn(),
  decisions: vi.fn(),
  actions: vi.fn(),
  audit: vi.fn(),
}));

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    rewardsHealth: mocks.rewardsHealth,
    tenantRewardCampaigns: mocks.campaigns,
    tenantRewardDecisions: mocks.decisions,
    tenantRewardActions: mocks.actions,
    tenantRewardAudit: mocks.audit,
  } } },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function renderHealth() {
  return render(<MemoryRouter><RewardsHealthPage /></MemoryRouter>);
}

function renderDrilldown() {
  return render(
    <MemoryRouter initialEntries={['/rewards/tenant-a']}>
      <Routes><Route path="/rewards/:tenantId" element={<RewardsDrilldownPage />} /></Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.rewardsHealth.mockResolvedValue({
    summary: { active_campaigns: 2, eligible_decisions_24h: 7, blocked_fraud_24h: 1 },
    top_tenants: [{ tenant_id: 'tenant-a', campaigns: 2, decisions_24h: 8 }],
    recent_decisions: [],
    blocked_decisions: [],
    action_status_breakdown: {},
    failed_deliveries: [],
    rail_stats: [],
    fraud_summary: {},
  });
  mocks.campaigns.mockResolvedValue({ campaigns: [{ id: 'campaign-a', name: 'Measured campaign' }], has_more: false });
  mocks.decisions.mockResolvedValue({ decisions: [], has_more: false });
  mocks.actions.mockResolvedValue({ actions: [], has_more: false });
  mocks.audit.mockResolvedValue({ entries: [], has_more: false });
});

describe('Kyber rewards route data states', () => {
  it('renders loading and populated states for reward health', async () => {
    const request = deferred<Record<string, unknown>>();
    mocks.rewardsHealth.mockReturnValue(request.promise);
    const view = renderHealth();
    expect(view.container.querySelectorAll('.animate-pulse, .aether-skeleton').length).toBeGreaterThan(0);
    request.resolve({
      summary: { active_campaigns: 2, eligible_decisions_24h: 7, blocked_fraud_24h: 1 },
      top_tenants: [{ tenant_id: 'tenant-a', campaigns: 2, decisions_24h: 8 }],
    });
    await waitFor(() => expect(screen.getByText('tenant-a')).toBeInTheDocument());
  });

  it('renders success-empty separately from unavailable reward health', async () => {
    mocks.rewardsHealth.mockResolvedValue({});
    renderHealth();
    await waitFor(() => expect(screen.getByText('No tenant activity')).toBeInTheDocument());
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
  });

  it('renders reward-health errors without fixture records', async () => {
    mocks.rewardsHealth.mockRejectedValue(new Error('reward service unavailable'));
    renderHealth();
    await waitFor(() => expect(screen.getByText('Unable to load reward health data')).toBeInTheDocument());
    expect(screen.getByText('reward service unavailable')).toBeInTheDocument();
    expect(screen.queryByText('tenant-a')).not.toBeInTheDocument();
  });

  it('renders loading, populated, and success-empty tenant sections', async () => {
    const request = deferred<Record<string, unknown>>();
    mocks.campaigns.mockReturnValue(request.promise);
    const view = renderDrilldown();
    expect(view.container.querySelectorAll('.animate-pulse, .aether-skeleton').length).toBeGreaterThan(0);
    request.resolve({ campaigns: [{ id: 'campaign-a', name: 'Measured campaign' }], has_more: false });
    await waitFor(() => expect(screen.getByText('Measured campaign')).toBeInTheDocument());
    expect(screen.getByText('No eligibility decisions')).toBeInTheDocument();
    expect(screen.getByText('No action payloads')).toBeInTheDocument();
    expect(screen.getByText('No audit events')).toBeInTheDocument();
  });

  it('renders tenant request errors rather than browser fallback data', async () => {
    mocks.campaigns.mockRejectedValue(new Error('campaign read unavailable'));
    renderDrilldown();
    await waitFor(() => expect(screen.getByText('campaign read unavailable')).toBeInTheDocument());
    expect(screen.queryByText('Measured campaign')).not.toBeInTheDocument();
  });
});
