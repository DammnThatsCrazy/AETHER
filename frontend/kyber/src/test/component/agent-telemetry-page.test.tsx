import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentTelemetryPage } from '@kyber/pages/agent-telemetry';

const mocks = vi.hoisted(() => ({
  isFeatureEnabled: vi.fn(() => true),
  agentTelemetryDeployments: vi.fn(),
  agentTelemetryDeployment: vi.fn(),
}));

vi.mock('@kyber/lib/featureFlags', () => ({
  isFeatureEnabled: mocks.isFeatureEnabled,
  featureFlags: {},
}));

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    agentTelemetryDeployments: mocks.agentTelemetryDeployments,
    agentTelemetryDeployment: mocks.agentTelemetryDeployment,
  } } },
}));

const FLEET_FIXTURE = {
  total_deployments: 2,
  active_deployments: 1,
  tenants_with_deployments: 2,
  events_24h: 5022,
  counts_by_status: { active: 1, error: 1 },
  counts_by_platform: { discord_bot: 1, mcp_server: 1 },
  deployments: [
    {
      tenant_id: 'tenant_001',
      id: 'dep_discord_support_001',
      display_name: 'Support Bot — Discord',
      external_platform: 'discord_bot',
      environment: 'production',
      status: 'active',
      event_count_24h: 4210,
      accepted_count_24h: 4102,
      rejected_count_24h: 61,
      error_count_24h: 12,
      consent_blocked_count_24h: 35,
      health_score: 0.97,
      last_event_at: '2026-07-08T21:42:00.000Z',
    },
    {
      tenant_id: 'tenant_002',
      id: 'dep_mcp_research_003',
      display_name: 'Research Assistant — MCP',
      external_platform: 'mcp_server',
      environment: 'staging',
      status: 'error',
      event_count_24h: 812,
      accepted_count_24h: 640,
      rejected_count_24h: 118,
      error_count_24h: 54,
      consent_blocked_count_24h: 0,
      health_score: 0.62,
      last_event_at: '2026-07-08T19:10:00.000Z',
    },
  ],
};

const DETAIL_FIXTURE = {
  deployment: {
    tenant_id: 'tenant_001',
    id: 'dep_discord_support_001',
    display_name: 'Support Bot — Discord',
    external_platform: 'discord_bot',
    environment: 'production',
    status: 'active',
    consent_mode: 'platform_managed',
    last_event_at: '2026-07-08T21:42:00.000Z',
  },
  health: {
    event_count_24h: 4210,
    accepted_count_24h: 4102,
    rejected_count_24h: 61,
    error_count_24h: 12,
    consent_blocked_count_24h: 35,
    health_score: 0.97,
  },
  diagnostics: {
    rejection_reasons: { schema_validation_failed: 42 },
    consent_block_rate: 0.008,
    ingest_lag_ms: 240,
    last_error: null,
  },
  recent_activity: [
    { id: 'act_001', action: 'created', actor: 'tenant-admin', occurred_at: '2026-05-01T14:00:00.000Z' },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.isFeatureEnabled.mockReturnValue(true);
  mocks.agentTelemetryDeployments.mockResolvedValue(FLEET_FIXTURE);
  mocks.agentTelemetryDeployment.mockResolvedValue(DETAIL_FIXTURE);
});

describe('Kyber Agent Telemetry page', () => {
  it('shows loading while the fleet request is pending', () => {
    mocks.agentTelemetryDeployments.mockReturnValue(new Promise(() => undefined));
    const { container } = render(<MemoryRouter><AgentTelemetryPage /></MemoryRouter>);
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('renders fleet aggregates and the per-deployment table', async () => {
    render(<MemoryRouter><AgentTelemetryPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Agent Telemetry')).toBeInTheDocument());
    expect(screen.getByText('Total deployments')).toBeInTheDocument();
    expect(screen.getByText('Deployments by status')).toBeInTheDocument();
    expect(screen.getByText('Deployments by platform')).toBeInTheDocument();
    expect(screen.getByText('Support Bot — Discord')).toBeInTheDocument();
    expect(screen.getByText('Research Assistant — MCP')).toBeInTheDocument();
    expect(screen.getByText('4102')).toBeInTheDocument();
    expect(screen.getByText(/Aether observes deployments — it does not publish, host, or execute agents\./)).toBeInTheDocument();
  });

  it('opens the diagnostics drawer when a deployment row is clicked', async () => {
    render(<MemoryRouter><AgentTelemetryPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Support Bot — Discord')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Support Bot — Discord'));
    await waitFor(() => expect(screen.getByText('Deployment diagnostics')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('schema_validation_failed')).toBeInTheDocument());
    expect(mocks.agentTelemetryDeployment).toHaveBeenCalledWith('tenant_001', 'dep_discord_support_001');
  });

  it('shows the empty state when no deployments exist', async () => {
    mocks.agentTelemetryDeployments.mockResolvedValue({
      ...FLEET_FIXTURE,
      total_deployments: 0,
      active_deployments: 0,
      counts_by_status: {},
      counts_by_platform: {},
      deployments: [],
    });
    render(<MemoryRouter><AgentTelemetryPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('No external agent deployments')).toBeInTheDocument());
  });

  it('shows the error state when the fleet request fails', async () => {
    mocks.agentTelemetryDeployments.mockRejectedValue(new Error('fleet unavailable'));
    render(<MemoryRouter><AgentTelemetryPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Unable to load agent telemetry')).toBeInTheDocument());
    expect(screen.getByText('fleet unavailable')).toBeInTheDocument();
  });

  it('shows the flag-off state and does not fetch when the feature is disabled', async () => {
    mocks.isFeatureEnabled.mockReturnValue(false);
    render(<MemoryRouter><AgentTelemetryPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('External agent telemetry is disabled')).toBeInTheDocument());
    expect(mocks.agentTelemetryDeployments).not.toHaveBeenCalled();
  });
});
