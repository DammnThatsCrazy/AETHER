import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AiEfficiencyPage } from '@kyber/pages/ai-efficiency';

const mocks = vi.hoisted(() => ({
  isFeatureEnabled: vi.fn(() => true),
  aiEfficiencyHealth: vi.fn(),
  aiEfficiencyTenant: vi.fn(),
}));

vi.mock('@kyber/lib/featureFlags', () => ({
  isFeatureEnabled: mocks.isFeatureEnabled,
  featureFlags: {},
}));

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    aiEfficiencyHealth: mocks.aiEfficiencyHealth,
    aiEfficiencyTenant: mocks.aiEfficiencyTenant,
  } } },
}));

const FLEET_FIXTURE = {
  fact_count: 48210,
  cost_coverage: 0.91,
  unknown_cost_share: 0.09,
  tenants_observed: 3,
  detector_counts: {
    retry_waste: 4,
    model_overqualification: 2,
    deterministic_replacement_candidate: 1,
    cache_opportunity: 3,
    failed_workflow_concentration: 1,
  },
  tenants: [
    {
      tenant_id: 'tenant_001',
      fact_count: 26410,
      cost_coverage: 0.97,
      unknown_cost_share: 0.03,
      open_findings: 2,
      status: 'healthy',
    },
    {
      tenant_id: 'tenant_002',
      fact_count: 14580,
      cost_coverage: 0.72,
      unknown_cost_share: 0.28,
      open_findings: 6,
      status: 'degraded',
    },
  ],
};

const TENANT_FIXTURE = {
  tenant_id: 'tenant_002',
  fact_count: 14580,
  cost_coverage: 0.72,
  unknown_cost_share: 0.28,
  workflow_count: 340,
  detector_counts: {
    retry_waste: 4,
    model_overqualification: 1,
    deterministic_replacement_candidate: 0,
    cache_opportunity: 0,
    failed_workflow_concentration: 1,
  },
  models: [
    { provider: 'openai', model: 'gpt-4o', invocations: 14580 },
  ],
  findings: [
    { detector: 'retry_waste', severity: 'high', title: 'Retry storms on gpt-4o support replies' },
    { detector: 'failed_workflow_concentration', severity: 'high', title: 'Failed-execution cost concentrated in one workflow' },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.isFeatureEnabled.mockReturnValue(true);
  mocks.aiEfficiencyHealth.mockResolvedValue(FLEET_FIXTURE);
  mocks.aiEfficiencyTenant.mockResolvedValue(TENANT_FIXTURE);
});

describe('Kyber AI Efficiency Health page', () => {
  it('renders fleet aggregates, the cost coverage gauge, and detector counts', async () => {
    render(<MemoryRouter><AiEfficiencyPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('AI Efficiency Health')).toBeInTheDocument());
    expect(screen.getByText('AI execution facts')).toBeInTheDocument();
    expect(screen.getByText('48210')).toBeInTheDocument();
    expect(screen.getByText('Tenants observed')).toBeInTheDocument();
    expect(screen.getAllByText('Cost coverage').length).toBeGreaterThan(0);
    expect(screen.getByText('91.0%')).toBeInTheDocument();
    expect(screen.getByText('Unknown-cost share')).toBeInTheDocument();
    expect(screen.getByText('9.0%')).toBeInTheDocument();
    expect(screen.getByText('Detector findings (fleet)')).toBeInTheDocument();
    for (const label of [
      'Retry waste',
      'Model overqualification',
      'Deterministic replacement',
      'Cache opportunity',
      'Failed workflow concentration',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText('tenant_001')).toBeInTheDocument();
    expect(screen.getByText('tenant_002')).toBeInTheDocument();
    expect(screen.getByText('degraded')).toBeInTheDocument();
    expect(screen.getByText('72.0%')).toBeInTheDocument();
    expect(
      screen.getByText(/Aether observes AI execution economics — proposals only, never automatic changes to models, prompts, or routing\./),
    ).toBeInTheDocument();
  });

  it('opens the tenant drilldown drawer when a tenant row is clicked', async () => {
    render(<MemoryRouter><AiEfficiencyPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('tenant_002')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tenant_002'));
    await waitFor(() => expect(screen.getByText('Tenant AI efficiency diagnostics')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('Retry storms on gpt-4o support replies')).toBeInTheDocument());
    expect(screen.getByText('Workflows observed')).toBeInTheDocument();
    expect(screen.getByText('openai / gpt-4o')).toBeInTheDocument();
    expect(screen.getByText(/raw invocation payloads are never shown in Kyber/)).toBeInTheDocument();
    expect(mocks.aiEfficiencyTenant).toHaveBeenCalledWith('tenant_002');
  });

  it('shows the empty states when no detectors or tenants exist', async () => {
    mocks.aiEfficiencyHealth.mockResolvedValue({
      fact_count: 0,
      cost_coverage: null,
      unknown_cost_share: null,
      tenants_observed: 0,
      detector_counts: {},
      tenants: [],
    });
    render(<MemoryRouter><AiEfficiencyPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('No detector findings')).toBeInTheDocument());
    expect(screen.getByText('No tenants with AI executions')).toBeInTheDocument();
  });

  it('shows the error state when the fleet request fails', async () => {
    mocks.aiEfficiencyHealth.mockRejectedValue(new Error('fleet unavailable'));
    render(<MemoryRouter><AiEfficiencyPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Unable to load AI efficiency health')).toBeInTheDocument());
    expect(screen.getByText('fleet unavailable')).toBeInTheDocument();
  });

  it('shows the flag-off state and does not fetch when the feature is disabled', async () => {
    mocks.isFeatureEnabled.mockReturnValue(false);
    render(<MemoryRouter><AiEfficiencyPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('AI efficiency health is disabled')).toBeInTheDocument());
    expect(mocks.aiEfficiencyHealth).not.toHaveBeenCalled();
  });
});
