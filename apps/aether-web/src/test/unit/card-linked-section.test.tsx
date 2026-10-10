import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CardLinkedActivitySection } from '@aether-app/pages/payment-rails/card-linked-section';
import { CardLinkedOutcomesTab } from '@aether-app/pages/campaigns/card-linked-outcomes-tab';

vi.mock('@aether-app/features/card-linked', () => ({
  useCardLinkedFlows: vi.fn(() => ({
    data: {
      items: [
        {
          id: 'clf_1', tenant_id: 't1', card_program_id: 'redotpay', issuer_id: 'rain',
          payment_network: 'visa', basis: 'topup', rail: 'onchain', chain: 'base',
          asset: 'USDC', amount_usd: '100.00', source: 'onchain_observer',
          confidence: 'probable', reconciliation_state: 'matched',
          occurred_at: '2026-07-01T00:00:00Z',
        },
        {
          id: 'clf_2', tenant_id: 't1', card_program_id: 'redotpay', issuer_id: 'rain',
          payment_network: 'visa', basis: 'spend', rail: 'card', chain: null,
          asset: null, amount_usd: '12.00', source: 'provider_webhook',
          confidence: 'strong', reconciliation_state: 'matched',
          occurred_at: '2026-07-02T00:00:00Z',
        },
      ],
      count: 2,
    },
    isLoading: false, error: null, refetch: vi.fn(),
  })),
  useCardLinkedCampaignOutcomes: vi.fn(() => ({
    data: {
      campaign_id: 'camp_1', card_topup_users: 1, card_spend_users: 1,
      card_topup_volume_usd: '100.00', card_spend_volume_usd: '60.00',
      card_linked_flow_count: 6, active_card_wallets: 1,
      programs_observed: ['redotpay'], issuers_observed: ['rain'],
      payment_networks_observed: ['visa'], attribution_basis: 'direct',
      basis_breakdown: { topup: 1, spend: 5 },
      source_breakdown: { onchain_observer: 1, provider_webhook: 5 },
      confidence_breakdown: { probable: 1, strong: 5 },
    },
    isLoading: false, error: null, refetch: vi.fn(),
  })),
}));

describe('Card-linked Activity section', () => {
  it('renders flows with top-up and spend visibly separated', async () => {
    render(<CardLinkedActivitySection />);
    await waitFor(() => expect(screen.getByText('Card-linked Activity')).toBeInTheDocument());
    expect(screen.getAllByText('topup').length).toBeGreaterThan(0);
    expect(screen.getAllByText('spend').length).toBeGreaterThan(0);
    // no-execution boundary stated
    expect(screen.getByText(/never processes card payments/)).toBeInTheDocument();
  });
});

describe('Campaign360 card-linked outcomes tab', () => {
  it('separates top-up from spend and labels attribution basis', async () => {
    render(<CardLinkedOutcomesTab campaignId="camp_1" />);
    await waitFor(() => expect(screen.getByText('Card top-up users')).toBeInTheDocument());
    expect(screen.getByText('Card spend users')).toBeInTheDocument();
    expect(screen.getByText('never counted as spend')).toBeInTheDocument();
    expect(screen.getByText('direct')).toBeInTheDocument();
    expect(screen.getByText(/never causal claims/)).toBeInTheDocument();
  });
});
