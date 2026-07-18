import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider, queryCache } from '@aether/ui';
import { PaymentRailsPage } from '@aether-app/pages/payment-rails';

// The shared queryCache tracks in-flight fetches with `promise.finally(...)`,
// which leaks an unhandled rejection when a fetcher rejects even though the
// UI handles the error (useQuery sets its error state). Patch it test-locally
// so the error-state tests do not trip vitest's unhandled-error detector.
beforeAll(() => {
  const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

/**
 * Badge text can collide with filter <option> text; scope to badge elements.
 * Matches both plain badges (text on the `.ui-badge` node) and the shared
 * CapabilityStateBadge (label nested inside `.ui-badge` alongside a glyph).
 */
function getBadge(text: string): HTMLElement {
  const match = screen
    .getAllByText(text)
    .find(el => el.classList.contains('ui-badge') || el.closest('.ui-badge') !== null);
  expect(match).toBeDefined();
  return (match?.closest('.ui-badge') ?? match) as HTMLElement;
}

const mocks = vi.hoisted(() => ({
  fetchFundingSessions: vi.fn(),
  fetchFundingSession: vi.fn(),
  fetchReconciliationRecords: vi.fn(),
  fetchPaymentRailHealth: vi.fn(),
  fetchProviderStatus: vi.fn(),
  syncProviderStatus: vi.fn(),
}));

vi.mock('@aether-app/features/payment-rails/api', () => mocks);

const SESSION_FIXTURES = [
  {
    id: 'fs_privy_onramp_001',
    tenant_id: 'tenant_demo_001',
    provider: 'privy',
    provider_detail: 'stripe',
    flow_type: 'fiat_onramp',
    rail: 'card',
    status: 'completed',
    provider_status: 'onramp_completed',
    reconciliation_state: 'matched',
    actor_kind: 'human',
    user_id: 'user_0001',
    journey_id: 'jrn_onboarding_001',
    campaign_id: 'camp_q3_funding',
    source_amount: '100.00',
    fiat_currency: 'USD',
    destination_asset: 'USDC',
    destination_chain: 'base',
    destination_amount: '99.20',
    fee_amount: '0.80',
    fee_currency: 'USD',
    provider_session_id: 'privy_sess_8842',
    provider_transaction_id: 'privy_tx_5521',
    idempotency_key: 'idem_privy_8842',
    occurred_at: '2026-07-08T14:05:00.000Z',
    created_at: '2026-07-08T14:05:04.000Z',
    updated_at: '2026-07-08T14:07:11.000Z',
  },
  {
    id: 'fs_coinbase_offramp_003',
    tenant_id: 'tenant_demo_001',
    provider: 'coinbase',
    flow_type: 'offramp',
    rail: 'ach',
    status: 'failed',
    provider_status: 'transaction_failed',
    status_reason: 'aml_review',
    reconciliation_state: 'conflict',
    actor_kind: 'agent',
    agent_id: 'agent_treasury_v1',
    org_id: 'org_acme',
    journey_id: 'jrn_treasury_007',
    source_asset: 'USDC',
    source_chain: 'base',
    source_amount: '5000.00',
    fiat_currency: 'USD',
    destination_amount: '4998.10',
    provider_session_id: 'cb_sess_4410',
    provider_transaction_id: 'cb_tx_7702',
    idempotency_key: 'idem_coinbase_4410',
    occurred_at: '2026-07-07T09:45:00.000Z',
    created_at: '2026-07-07T09:45:03.000Z',
    updated_at: '2026-07-08T06:15:40.000Z',
  },
];

const RECONCILIATION_FIXTURES = [
  {
    id: 'rec_001',
    tenant_id: 'tenant_demo_001',
    funding_session_id: 'fs_privy_onramp_001',
    provider: 'privy',
    state: 'matched',
    last_source: 'webhook',
    sdk_event_id: 'evt_sdk_7001',
    provider_event_id: 'evt_privy_9001',
    first_observed_at: '2026-07-08T14:05:04.000Z',
    last_checked_at: '2026-07-08T14:07:11.000Z',
    resolved_at: '2026-07-08T14:07:11.000Z',
    created_at: '2026-07-08T14:05:04.000Z',
    updated_at: '2026-07-08T14:07:11.000Z',
  },
  {
    id: 'rec_003',
    tenant_id: 'tenant_demo_001',
    funding_session_id: 'fs_coinbase_offramp_003',
    provider: 'coinbase',
    state: 'conflict',
    last_source: 'polling',
    sdk_event_id: 'evt_sdk_7003',
    provider_event_id: 'evt_cb_9103',
    discrepancies: [
      { field: 'status', sdk_value: 'completed', provider_value: 'failed' },
      { field: 'destination_amount', sdk_value: '4998.10', provider_value: '0.00' },
    ],
    first_observed_at: '2026-07-07T09:45:03.000Z',
    last_checked_at: '2026-07-08T06:15:40.000Z',
    resolved_at: null,
    created_at: '2026-07-07T09:45:03.000Z',
    updated_at: '2026-07-08T06:15:40.000Z',
  },
];

const HEALTH_FIXTURES = [
  {
    tenant_id: 'tenant_demo_001',
    provider: 'privy',
    configured: true,
    enabled: true,
    webhook_verified_24h: 182,
    webhook_rejected_24h: 0,
    sessions_observed_24h: 41,
    sessions_completed_24h: 38,
    sessions_failed_24h: 1,
    sessions_unresolved: 0,
    reconciliation_matched_rate: 0.982,
    reconciliation_conflicts: 0,
    last_event_at: '2026-07-08T14:07:11.000Z',
    status: 'healthy',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
  {
    tenant_id: 'tenant_demo_001',
    provider: 'coinbase',
    configured: true,
    enabled: true,
    webhook_verified_24h: 44,
    webhook_rejected_24h: 11,
    sessions_observed_24h: 9,
    sessions_completed_24h: 5,
    sessions_failed_24h: 3,
    sessions_unresolved: 1,
    reconciliation_matched_rate: 0.706,
    reconciliation_conflicts: 2,
    last_event_at: '2026-07-08T06:15:40.000Z',
    status: 'degraded',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
  {
    tenant_id: 'tenant_demo_001',
    provider: 'moonpay',
    configured: false,
    enabled: false,
    webhook_verified_24h: 0,
    webhook_rejected_24h: 0,
    sessions_observed_24h: 0,
    sessions_completed_24h: 0,
    sessions_failed_24h: 0,
    sessions_unresolved: 0,
    reconciliation_matched_rate: null,
    reconciliation_conflicts: 0,
    last_event_at: null,
    status: 'not_configured',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
];

function renderPage() {
  return render(
    <ToastProvider>
      <PaymentRailsPage />
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  queryCache.invalidatePrefix('payment-rails');
  mocks.fetchFundingSessions.mockResolvedValue({ sessions: SESSION_FIXTURES, notConfigured: false });
  mocks.fetchFundingSession.mockResolvedValue(SESSION_FIXTURES[1]);
  mocks.fetchReconciliationRecords.mockResolvedValue(RECONCILIATION_FIXTURES);
  mocks.fetchPaymentRailHealth.mockResolvedValue({ providers: HEALTH_FIXTURES, notConfigured: false });
  mocks.fetchProviderStatus.mockResolvedValue({
    provider: 'coinbase',
    status: 'error',
    environment: 'production',
    webhook_configured: true,
    polling_configured: true,
    last_synced_at: '2026-07-08T22:10:00.000Z',
  });
  mocks.syncProviderStatus.mockResolvedValue({ sync_requested: true });
});

describe('Aether Payment Rails page', () => {
  it('renders provider health cards, reconciliation summary, and session fixtures', async () => {
    renderPage();
    await waitFor(() => expect(getBadge('completed')).toBeInTheDocument());
    // All five named providers render a health card (Stripe and Bridge fall
    // back to not-configured cards since the backend returned no record).
    for (const label of ['Privy', 'Stripe', 'Coinbase', 'MoonPay', 'Bridge']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(getBadge('healthy')).toBeInTheDocument();
    expect(getBadge('degraded')).toBeInTheDocument();
    expect(screen.getAllByText('not configured').length).toBeGreaterThan(0);
    expect(screen.getByText('Reconciliation summary')).toBeInTheDocument();
    expect(getBadge('matched')).toBeInTheDocument();
    expect(getBadge('conflict')).toBeInTheDocument();
    // Native amounts stay in their own units — never converted or summed.
    expect(screen.getByText('100.00 USD')).toBeInTheDocument();
    expect(screen.getByText('5000.00 USDC')).toBeInTheDocument();
    expect(
      screen.getByText(/Aether observes payment rails — it does not execute or settle payments, or custody funds\./),
    ).toBeInTheDocument();
  });

  it('filters sessions by provider', async () => {
    renderPage();
    await waitFor(() => expect(mocks.fetchFundingSessions).toHaveBeenCalledWith({}));
    await userEvent.selectOptions(screen.getByLabelText('Filter by provider'), 'stripe');
    await waitFor(() => expect(mocks.fetchFundingSessions).toHaveBeenCalledWith({ provider: 'stripe' }));
  });

  it('filters sessions by reconciliation state', async () => {
    renderPage();
    await waitFor(() => expect(mocks.fetchFundingSessions).toHaveBeenCalledWith({}));
    await userEvent.selectOptions(screen.getByLabelText('Filter by reconciliation state'), 'conflict');
    await waitFor(() =>
      expect(mocks.fetchFundingSessions).toHaveBeenCalledWith({ reconciliation_state: 'conflict' }),
    );
  });

  it('opens the session detail drawer with attribution, provider references, and discrepancies', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Offramp')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Offramp'));
    await waitFor(() => expect(screen.getByText('Funding session')).toBeInTheDocument());
    expect(mocks.fetchFundingSession).toHaveBeenCalledWith('fs_coinbase_offramp_003');
    // Attribution
    await waitFor(() => expect(screen.getByText('jrn_treasury_007')).toBeInTheDocument());
    expect(screen.getByText('agent_treasury_v1')).toBeInTheDocument();
    // Provider references
    expect(screen.getByText('cb_tx_7702')).toBeInTheDocument();
    expect(screen.getByText('idem_coinbase_4410')).toBeInTheDocument();
    // Reconciliation record + discrepancies
    expect(screen.getByText('Discrepancies')).toBeInTheDocument();
    expect(screen.getByText('destination_amount')).toBeInTheDocument();
    expect(screen.getByText('0.00')).toBeInTheDocument();
  });

  it('requests a provider status sync with success feedback', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByText('Sync status').length).toBeGreaterThan(0));
    // Cards render in canonical provider order; the first configured card is Privy.
    await userEvent.click(screen.getAllByText('Sync status')[0] as HTMLElement);
    await waitFor(() => expect(mocks.syncProviderStatus).toHaveBeenCalledWith('privy'));
    await waitFor(() => expect(screen.getByText('Privy status sync requested')).toBeInTheDocument());
  });

  it('shows error feedback when a sync fails', async () => {
    mocks.syncProviderStatus.mockRejectedValue(new Error('sync unavailable'));
    renderPage();
    await waitFor(() => expect(screen.getAllByText('Sync status').length).toBeGreaterThan(0));
    await userEvent.click(screen.getAllByText('Sync status')[0] as HTMLElement);
    await waitFor(() => expect(screen.getByText('Failed to sync Privy status')).toBeInTheDocument());
  });

  it('shows the empty state when there are no sessions', async () => {
    mocks.fetchFundingSessions.mockResolvedValue({ sessions: [], notConfigured: false });
    renderPage();
    await waitFor(() => expect(screen.getByText('No funding sessions observed yet')).toBeInTheDocument());
  });

  it('shows the not-configured state when observability is not enabled', async () => {
    mocks.fetchFundingSessions.mockResolvedValue({ sessions: [], notConfigured: true });
    mocks.fetchPaymentRailHealth.mockResolvedValue({ providers: [], notConfigured: true });
    renderPage();
    await waitFor(() =>
      expect(screen.getAllByText('Payment rail observability is not configured').length).toBeGreaterThan(0),
    );
  });

  it('shows the error state when the sessions request fails', async () => {
    mocks.fetchFundingSessions.mockRejectedValue(new Error('boom'));
    renderPage();
    await waitFor(() => expect(screen.getByText('Failed to load funding sessions')).toBeInTheDocument());
    expect(screen.getByText('boom')).toBeInTheDocument();
  });
});
