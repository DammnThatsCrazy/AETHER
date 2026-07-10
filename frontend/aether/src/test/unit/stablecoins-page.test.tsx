import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { StablecoinsPage } from '@aether-app/pages/stablecoins';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { stablecoins: {
    assets: vi.fn(async () => ({ items: [
      { canonical_asset_id: 'usdc', symbol: 'USDC', peg_currency: 'USD', issuer_name: 'Circle' },
    ], count: 1 })),
    valuations: vi.fn(async () => ({ items: [
      { valuation_id: 'val_1', deployment_id: 'usdc-base', price_usd: '0.985000', peg_deviation_bps: '-150', peg_status: 'depegged', observed_at: '2026-07-08T00:00:00Z' },
    ], count: 1 })),
    flows: vi.fn(async () => ({ items: [], count: 0 })),
  } },
}));

describe('Stablecoins page', () => {
  it('renders assets and depeg count from observed data', async () => {
    render(<MemoryRouter><StablecoinsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Stablecoin Intelligence')).toBeInTheDocument());
    expect(screen.getByText('USDC')).toBeInTheDocument();
    expect(screen.getByText('Depegged now')).toBeInTheDocument();
    // observation-only banner
    expect(screen.getByText(/never executes, mints, or moves funds/)).toBeInTheDocument();
  });
});
