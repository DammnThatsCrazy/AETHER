import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ConnectorsPage } from '@kyber/pages/connectors';

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    connectorsOverview: vi.fn(async () => ({
      available_connectors: 14, configured_count: 3, enabled_count: 2,
      enabled_by_status: { healthy: 1, never_synced: 1 }, enabled_by_type: { webhook: 1, shopify: 1 },
    })),
  } } },
}));

describe('Kyber Connector Health page', () => {
  it('renders aggregate connector health metrics', async () => {
    render(<MemoryRouter><ConnectorsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Connector Health')).toBeInTheDocument());
    expect(screen.getByText('Available connectors')).toBeInTheDocument();
    expect(screen.getByText('Enabled by status')).toBeInTheDocument();
  });
});
