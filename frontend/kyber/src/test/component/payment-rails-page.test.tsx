import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PaymentRailsPage } from '@kyber/pages/payment-rails';

const mocks = vi.hoisted(() => ({
  isFeatureEnabled: vi.fn(() => true),
  paymentRailsHealth: vi.fn(),
  paymentRailsTenant: vi.fn(),
  cardLinkedPaymentRailsDiagnostics: vi.fn(),
}));

vi.mock('@kyber/lib/featureFlags', () => ({
  isFeatureEnabled: mocks.isFeatureEnabled,
  featureFlags: {},
}));

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    paymentRailsHealth: mocks.paymentRailsHealth,
    paymentRailsTenant: mocks.paymentRailsTenant,
    cardLinkedPaymentRailsDiagnostics: mocks.cardLinkedPaymentRailsDiagnostics,
  } } },
}));

const FLEET_FIXTURE = {
  totals: {
    configured_tenants: 2,
    sessions_observed_24h: 877,
    sessions_unresolved: 9,
    reconciliation_conflicts: 4,
  },
  providers: [
    {
      provider: 'privy',
      status: 'healthy',
      configured_tenants: 2,
      webhook_verified_24h: 640,
      webhook_rejected_24h: 2,
      sessions_observed_24h: 512,
      sessions_completed_24h: 488,
      sessions_failed_24h: 9,
      sessions_unresolved: 4,
      reconciliation_matched_rate: 0.982,
      reconciliation_conflicts: 0,
    },
    {
      provider: 'coinbase',
      status: 'degraded',
      configured_tenants: 1,
      webhook_verified_24h: 188,
      webhook_rejected_24h: 41,
      sessions_observed_24h: 244,
      sessions_completed_24h: 190,
      sessions_failed_24h: 28,
      sessions_unresolved: 5,
      reconciliation_matched_rate: 0.706,
      reconciliation_conflicts: 4,
    },
    {
      provider: 'moonpay',
      status: 'not_configured',
      configured_tenants: 0,
      webhook_verified_24h: 0,
      webhook_rejected_24h: 0,
      sessions_observed_24h: 0,
      sessions_completed_24h: 0,
      sessions_failed_24h: 0,
      sessions_unresolved: 0,
      reconciliation_matched_rate: null,
      reconciliation_conflicts: 0,
    },
  ],
  tenants: [
    {
      tenant_id: 'tenant_001',
      providers_configured: 2,
      providers_degraded: 0,
      sessions_observed_24h: 733,
      sessions_unresolved: 4,
      reconciliation_conflicts: 0,
      status: 'healthy',
    },
    {
      tenant_id: 'tenant_002',
      providers_configured: 1,
      providers_degraded: 1,
      sessions_observed_24h: 144,
      sessions_unresolved: 5,
      reconciliation_conflicts: 4,
      status: 'degraded',
    },
  ],
};

const TENANT_FIXTURE = {
  tenant_id: 'tenant_001',
  providers: [
    {
      provider: 'privy',
      adapter: {
        status: 'configured',
        environment: 'production',
        webhook_configured: true,
        polling_configured: true,
        last_synced_at: '2026-07-08T23:45:00.000Z',
      },
      health: {
        status: 'healthy',
        webhook_verified_24h: 320,
        webhook_rejected_24h: 1,
        sessions_observed_24h: 256,
        sessions_completed_24h: 244,
        sessions_failed_24h: 4,
        sessions_unresolved: 2,
        reconciliation_matched_rate: 0.982,
        reconciliation_conflicts: 0,
        last_event_at: '2026-07-08T21:42:00.000Z',
      },
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.isFeatureEnabled.mockReturnValue(true);
  mocks.paymentRailsHealth.mockResolvedValue(FLEET_FIXTURE);
  mocks.paymentRailsTenant.mockResolvedValue(TENANT_FIXTURE);
  mocks.cardLinkedPaymentRailsDiagnostics.mockResolvedValue({
    paymentscan_status: 'catalog_and_benchmarks_only',
    card_program_count: 23,
    issuer_count: 6,
    flow_count: 3,
    region_restricted_records: 1,
    topup_support: 1,
    spend_support: 2,
    unmatched_events: 1,
    reconciliation_conflicts: 0,
    consent_blocked_records: 0,
    blocked_pii_attempts: 0,
    payment_network_count: 3,
    chain_count: 9,
    currency_count: 8,
    basis_mislabeling_warnings: ['Top-up/funding records exist without provider spend coverage; do not report them as card spend.'],
  });
});

describe('Kyber Payment Rails page', () => {
  it('renders fleet aggregates and the per-provider health table', async () => {
    render(<MemoryRouter><PaymentRailsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Payment Rails')).toBeInTheDocument());
    expect(screen.getByText('Configured tenants')).toBeInTheDocument();
    expect(screen.getByText('Per-provider fleet health (24h)')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Card-linked Observability')).toBeInTheDocument());
    expect(screen.getByText('Card programs')).toBeInTheDocument();
    expect(screen.getByText('Privy')).toBeInTheDocument();
    expect(screen.getByText('Coinbase')).toBeInTheDocument();
    expect(screen.getByText('MoonPay')).toBeInTheDocument();
    expect(screen.getByText('98.2%')).toBeInTheDocument();
    expect(screen.getAllByText('degraded').length).toBeGreaterThan(0);
    expect(screen.getByText('not configured')).toBeInTheDocument();
    expect(screen.getByText(/Aether observes payment rails — it does not execute or settle payments, or custody funds\./)).toBeInTheDocument();
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

  it('shows the empty states when no providers or tenants exist', async () => {
    mocks.paymentRailsHealth.mockResolvedValue({
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
