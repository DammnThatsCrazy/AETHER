import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PaymentRailsPage } from '@kyber/pages/payment-rails';

const mocks = vi.hoisted(() => ({
  isFeatureEnabled: vi.fn(() => true),
  paymentRailsHealth: vi.fn(),
  paymentRailsTenant: vi.fn(),
}));

vi.mock('@kyber/lib/featureFlags', () => ({
  isFeatureEnabled: mocks.isFeatureEnabled,
  featureFlags: {},
}));

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    paymentRailsHealth: mocks.paymentRailsHealth,
    paymentRailsTenant: mocks.paymentRailsTenant,
  } } },
}));

// Field names mirror the typed backend contract
// (services/integrations/providers/payment_rails/kyber_contract.py, v1.0.0).
// The five providers cover the distinct rendered states: healthy, degraded,
// not_configured (credential-waiting), disabled, and unknown (null operational
// fields). null reconciliation_matched_rate must render as "—", never 0.
const FLEET_FIXTURE = {
  contract_version: '1.0.0',
  tenants_observed: 3,
  totals: {
    configured_tenants: 3,
    enabled_tenants: 2,
    providers_degraded: 1,
    sessions_observed_24h: 877,
    sessions_completed_24h: 720,
    sessions_failed_24h: 41,
    sessions_pending: 12,
    sessions_stale: 3,
    sessions_unresolved: 9,
    webhook_verified_24h: 828,
    webhook_rejected_24h: 43,
    signature_failures_24h: 2,
    reconciliation_matched_rate: 0.91,
    reconciliation_conflicts: 4,
    oldest_incomplete_receipt_age_seconds: 320,
    canonical_backlog: 5,
    outbox_lag: null,
    repair_backlog: 1,
    dead_lettered: 0,
    worker_heartbeat: true,
    last_successful_worker_cycle: '2026-07-08T23:50:00.000Z',
  },
  providers: [
    {
      provider: 'privy',
      status: 'healthy',
      enabled: true,
      configured_tenants: 2,
      webhook_verified_24h: 640,
      webhook_rejected_24h: 2,
      signature_failures_24h: 0,
      sessions_observed_24h: 512,
      sessions_completed_24h: 488,
      sessions_failed_24h: 9,
      sessions_pending: 6,
      sessions_stale: 1,
      sessions_unresolved: 4,
      reconciliation_matched_rate: 0.982,
      reconciliation_conflicts: 0,
      polling_cursor_age_seconds: 12,
      provider_probe_status: 'ok',
    },
    {
      provider: 'coinbase',
      status: 'degraded',
      enabled: true,
      configured_tenants: 1,
      webhook_verified_24h: 188,
      webhook_rejected_24h: 41,
      signature_failures_24h: 2,
      sessions_observed_24h: 244,
      sessions_completed_24h: 190,
      sessions_failed_24h: 28,
      sessions_pending: 6,
      sessions_stale: 2,
      sessions_unresolved: 5,
      reconciliation_matched_rate: 0.706,
      reconciliation_conflicts: 4,
      polling_cursor_age_seconds: 640,
      provider_probe_status: 'slow',
    },
    {
      // Credential-waiting: configured for nobody, matched rate unknown (null).
      provider: 'moonpay',
      status: 'not_configured',
      enabled: false,
      configured_tenants: 0,
      webhook_verified_24h: 0,
      webhook_rejected_24h: 0,
      signature_failures_24h: 0,
      sessions_observed_24h: 0,
      sessions_completed_24h: 0,
      sessions_failed_24h: 0,
      sessions_pending: 0,
      sessions_stale: 0,
      sessions_unresolved: 0,
      reconciliation_matched_rate: null,
      reconciliation_conflicts: 0,
      polling_cursor_age_seconds: null,
      provider_probe_status: null,
    },
    {
      provider: 'stripe',
      status: 'disabled',
      enabled: false,
      configured_tenants: 1,
      webhook_verified_24h: 0,
      webhook_rejected_24h: 0,
      signature_failures_24h: 0,
      sessions_observed_24h: 0,
      sessions_completed_24h: 0,
      sessions_failed_24h: 0,
      sessions_pending: 0,
      sessions_stale: 0,
      sessions_unresolved: 0,
      reconciliation_matched_rate: null,
      reconciliation_conflicts: 0,
      polling_cursor_age_seconds: null,
      provider_probe_status: null,
    },
    {
      // Unknown: every operational depth field is null and must not crash.
      provider: 'bridge',
      status: 'unknown',
      enabled: true,
      configured_tenants: 1,
      webhook_verified_24h: 0,
      webhook_rejected_24h: 0,
      signature_failures_24h: 0,
      sessions_observed_24h: 0,
      sessions_completed_24h: 0,
      sessions_failed_24h: 0,
      sessions_pending: 0,
      sessions_stale: 0,
      sessions_unresolved: 0,
      reconciliation_matched_rate: null,
      reconciliation_conflicts: 0,
      polling_cursor_age_seconds: null,
      provider_probe_status: null,
    },
  ],
  tenants: [
    {
      tenant_id: 'tenant_001',
      status: 'healthy',
      providers_configured: 2,
      providers_degraded: 0,
      sessions_observed_24h: 733,
      sessions_unresolved: 4,
      reconciliation_conflicts: 0,
    },
    {
      tenant_id: 'tenant_002',
      status: 'degraded',
      providers_configured: 1,
      providers_degraded: 1,
      sessions_observed_24h: 144,
      sessions_unresolved: 5,
      reconciliation_conflicts: 4,
    },
  ],
};

const TENANT_FIXTURE = {
  contract_version: '1.0.0',
  tenant_id: 'tenant_001',
  providers: [
    {
      provider: 'privy',
      adapter: {
        status: 'configured',
        environment: 'production',
        webhook_configured: true,
        polling_configured: true,
        webhook_endpoint_registered: true,
        credential_slots: [
          { slot_name: 'api_key', required: true, configured: true, state: 'active' },
        ],
      },
      health: {
        status: 'healthy',
        sessions_observed_24h: 256,
        sessions_completed_24h: 244,
        sessions_failed_24h: 4,
        sessions_unresolved: 2,
        webhook_verified_24h: 320,
        webhook_rejected_24h: 1,
        reconciliation_matched_rate: 0.982,
        reconciliation_conflicts: 0,
        last_event_at: '2026-07-08T21:42:00.000Z',
        last_poll_at: '2026-07-08T21:40:00.000Z',
        last_successful_poll_at: '2026-07-08T21:40:00.000Z',
        last_failed_poll_at: null,
        polling_cursor_age_seconds: 120,
        provider_poll_health: 'ok',
        connection_probe_result: 'ok',
      },
    },
  ],
  backlogs: {
    receipt_backlog: 0,
    canonical_backlog: 0,
    outbox_backlog: null,
    repair_backlog: 0,
    dead_lettered: 0,
    oldest_incomplete_receipt_age_seconds: null,
  },
  recent_audit: [],
  recent_repair_outcomes: [],
};

// A tenant whose provider is still waiting on credentials: environment,
// reconciliation_matched_rate and last_event_at are all null and must render
// as "—" in the drawer rather than crashing or showing a confident 0.
const TENANT_WAITING_FIXTURE = {
  contract_version: '1.0.0',
  tenant_id: 'tenant_002',
  providers: [
    {
      provider: 'coinbase',
      adapter: {
        status: 'credentials_pending',
        environment: null,
        webhook_configured: false,
        polling_configured: false,
        webhook_endpoint_registered: false,
        credential_slots: [
          { slot_name: 'api_key', required: true, configured: false, state: 'pending' },
        ],
      },
      health: {
        status: 'not_configured',
        sessions_observed_24h: 0,
        sessions_completed_24h: 0,
        sessions_failed_24h: 0,
        sessions_unresolved: 0,
        webhook_verified_24h: 0,
        webhook_rejected_24h: 0,
        reconciliation_matched_rate: null,
        reconciliation_conflicts: 0,
        last_event_at: null,
        last_poll_at: null,
        last_successful_poll_at: null,
        last_failed_poll_at: null,
        polling_cursor_age_seconds: null,
        provider_poll_health: null,
        connection_probe_result: null,
      },
    },
  ],
  backlogs: {
    receipt_backlog: 0,
    canonical_backlog: 0,
    outbox_backlog: null,
    repair_backlog: 0,
    dead_lettered: 0,
    oldest_incomplete_receipt_age_seconds: null,
  },
  recent_audit: [],
  recent_repair_outcomes: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.isFeatureEnabled.mockReturnValue(true);
  mocks.paymentRailsHealth.mockResolvedValue(FLEET_FIXTURE);
  mocks.paymentRailsTenant.mockResolvedValue(TENANT_FIXTURE);
});

describe('Kyber Payment Rails page', () => {
  it('shows loading while the fleet request is pending', () => {
    mocks.paymentRailsHealth.mockReturnValue(new Promise(() => undefined));
    const { container } = render(<MemoryRouter><PaymentRailsPage /></MemoryRouter>);
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('renders fleet aggregates and the per-provider health table', async () => {
    render(<MemoryRouter><PaymentRailsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Payment Rails')).toBeInTheDocument());
    expect(screen.getByText('Configured tenants')).toBeInTheDocument();
    expect(screen.getByText('Per-provider fleet health (24h)')).toBeInTheDocument();
    expect(screen.getByText('Privy')).toBeInTheDocument();
    expect(screen.getByText('Coinbase')).toBeInTheDocument();
    expect(screen.getByText('MoonPay')).toBeInTheDocument();
    expect(screen.getByText('Stripe')).toBeInTheDocument();
    expect(screen.getByText('Bridge')).toBeInTheDocument();
    expect(screen.getByText('98.2%')).toBeInTheDocument();
    expect(screen.getByText(/Aether observes payment rails — it does not execute or settle payments, or custody funds\./)).toBeInTheDocument();
  });

  it('renders each distinct provider status with its own badge label', async () => {
    render(<MemoryRouter><PaymentRailsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Per-provider fleet health (24h)')).toBeInTheDocument());
    // healthy + degraded appear on both a provider row and a tenant row.
    expect(screen.getAllByText('healthy').length).toBeGreaterThan(0);
    expect(screen.getAllByText('degraded').length).toBeGreaterThan(0);
    expect(screen.getByText('not configured')).toBeInTheDocument();
    expect(screen.getByText('disabled')).toBeInTheDocument();
    expect(screen.getByText('unknown')).toBeInTheDocument();
  });

  it('renders a null reconciliation rate as "—" and never as 0 in the provider table', async () => {
    render(<MemoryRouter><PaymentRailsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('MoonPay')).toBeInTheDocument());

    const moonpayRow = screen.getByText('MoonPay').closest('tr');
    expect(moonpayRow).not.toBeNull();
    // Matched-rate cell for a null rate is an em dash, not "0.0%".
    expect(within(moonpayRow as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(within(moonpayRow as HTMLElement).queryByText('0.0%')).toBeNull();

    // The unknown-status provider with all-null operational fields still renders.
    const bridgeRow = screen.getByText('Bridge').closest('tr');
    expect(bridgeRow).not.toBeNull();
    expect(within(bridgeRow as HTMLElement).getByText('—')).toBeInTheDocument();
  });

  it('opens the tenant diagnostics drawer when a tenant row is clicked', async () => {
    render(<MemoryRouter><PaymentRailsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('tenant_001')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tenant_001'));
    await waitFor(() => expect(screen.getByText('Tenant payment rail diagnostics')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('Adapter status')).toBeInTheDocument());
    expect(screen.getByText('Webhook configured')).toBeInTheDocument();
    expect(screen.getByText('Matched rate')).toBeInTheDocument();
    expect(screen.getByText(/raw tenant payment payloads are never shown in Kyber/)).toBeInTheDocument();
    expect(mocks.paymentRailsTenant).toHaveBeenCalledWith('tenant_001');
  });

  it('renders null adapter/health diagnostics as "—" in the tenant drawer', async () => {
    mocks.paymentRailsTenant.mockResolvedValue(TENANT_WAITING_FIXTURE);
    render(<MemoryRouter><PaymentRailsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('tenant_002')).toBeInTheDocument());
    await userEvent.click(screen.getByText('tenant_002'));
    await waitFor(() => expect(screen.getByText('Tenant payment rail diagnostics')).toBeInTheDocument());
    expect(mocks.paymentRailsTenant).toHaveBeenCalledWith('tenant_002');

    // null environment, matched rate and last event all render as em dashes.
    const environmentRow = screen.getByText('Environment').closest('div');
    expect(within(environmentRow as HTMLElement).getByText('—')).toBeInTheDocument();
    const matchedRow = screen.getByText('Matched rate').closest('div');
    expect(within(matchedRow as HTMLElement).getByText('—')).toBeInTheDocument();
    const lastEventRow = screen.getByText('Last event').closest('div');
    expect(within(lastEventRow as HTMLElement).getByText('—')).toBeInTheDocument();
  });

  it('shows the empty states when no providers or tenants exist', async () => {
    mocks.paymentRailsHealth.mockResolvedValue({
      contract_version: '1.0.0',
      tenants_observed: 0,
      totals: { configured_tenants: 0, sessions_observed_24h: 0, sessions_unresolved: 0, reconciliation_conflicts: 0 },
      providers: [],
      tenants: [],
    });
    render(<MemoryRouter><PaymentRailsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('No payment rail providers')).toBeInTheDocument());
    expect(screen.getByText('No tenants with payment rails')).toBeInTheDocument();
  });

  it('shows the error state when the fleet request fails', async () => {
    mocks.paymentRailsHealth.mockRejectedValue(new Error('fleet unavailable'));
    render(<MemoryRouter><PaymentRailsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Unable to load payment rail health')).toBeInTheDocument());
    expect(screen.getByText('fleet unavailable')).toBeInTheDocument();
  });

  it('shows the flag-off state and does not fetch when the feature is disabled', async () => {
    mocks.isFeatureEnabled.mockReturnValue(false);
    render(<MemoryRouter><PaymentRailsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Payment rail observability is disabled')).toBeInTheDocument());
    expect(mocks.paymentRailsHealth).not.toHaveBeenCalled();
  });
});
