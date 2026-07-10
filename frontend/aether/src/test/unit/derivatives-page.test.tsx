import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { DerivativesPage } from '@aether-app/pages/derivatives';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { derivatives: {
    venues: vi.fn(async () => ({ items: [{ venue_id: 'venue-sim' }], count: 1 })),
    accounts: vi.fn(async () => ({ items: [
      { trading_account_id: 'acct_1', venue_id: 'venue-sim', owner_entity_id: 'ent_1', status: 'linked' },
    ], count: 1 })),
    positions: vi.fn(async () => ({ items: [
      { position_id: 'pos_1', trading_account_id: 'acct_1', canonical_market_id: 'BTC-PERP', side: 'long', size: '1.5', status: 'open' },
    ], count: 1 })),
    pnl: vi.fn(async () => ({ items: [], count: 0 })),
    reconciliationVariances: vi.fn(async () => ({ items: [], count: 0 })),
  } },
}));

describe('Derivatives page', () => {
  it('renders linked accounts and open position stats', async () => {
    render(<MemoryRouter><DerivativesPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Derivatives Intelligence')).toBeInTheDocument());
    expect(screen.getByText('acct_1')).toBeInTheDocument();
    expect(screen.getByText('Open positions')).toBeInTheDocument();
    // observation-only banner
    expect(screen.getByText(/never places, modifies, or recommends orders/)).toBeInTheDocument();
  });
});
