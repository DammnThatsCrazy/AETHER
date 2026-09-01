import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { RightsOperationsPage } from '@kyber/pages/rights/rights-operations-page';

const mocks = vi.hoisted(() => ({
  reconciliation: vi.fn(),
  impacts: vi.fn(),
  executeImpact: vi.fn(),
}));

vi.mock('@kyber/lib/api/endpoints', () => ({
  api: {
    rightsAuthority: {
      reconciliation: mocks.reconciliation,
      impacts: mocks.impacts,
      executeImpact: mocks.executeImpact,
    },
  },
}));

describe('RightsOperationsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.reconciliation.mockResolvedValue({
      rights_mode: 'enforce',
      totals: { rows_scanned: 0, rights_attached: 0, rightsless: 0 },
      migration: { status: 'no_rightsless_rows_found', next_action: 'No action required', mutation_performed: false },
    });
    mocks.impacts.mockResolvedValue({ items: [] });
  });

  it('renders a successful empty remediation queue', async () => {
    render(<RightsOperationsPage />);

    expect(await screen.findByText('Rights Operations')).toBeInTheDocument();
    expect(screen.getByText('No rights impacts recorded')).toBeInTheDocument();
    expect(screen.getByText('no_rightsless_rows_found')).toBeInTheDocument();
  });

  it('renders unavailable authority instead of a healthy empty queue', async () => {
    mocks.reconciliation.mockRejectedValueOnce(new Error('operator rights backend offline'));

    render(<RightsOperationsPage />);

    expect(await screen.findByText('Rights authority unavailable')).toBeInTheDocument();
    expect(screen.getByText('operator rights backend offline')).toBeInTheDocument();
    expect(screen.queryByText('No rights impacts recorded')).not.toBeInTheDocument();
  });
});
