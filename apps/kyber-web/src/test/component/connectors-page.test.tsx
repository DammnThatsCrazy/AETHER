import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ConnectorsPage } from '@kyber/pages/connectors';

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    connectorsOverview: vi.fn(async () => ({
      available_connectors: 14, configured_count: 3, enabled_count: 2,
      enabled_by_status: { healthy: 1, never_synced: 1 },
      enabled_by_type: { webhook: 1, shopify: 1 },
      by_type_detail: [
        {
          connector_type: 'shopify', label: 'Shopify', category: 'ecommerce',
          supports_pull: true, supports_webhook: true,
          enabled_tenants: 1, status_breakdown: { healthy: 1 }, last_synced_at: '2026-06-11T10:00:00Z',
        },
        {
          connector_type: 'webhook', label: 'Generic Webhook', category: 'generic',
          supports_pull: false, supports_webhook: true,
          enabled_tenants: 1, status_breakdown: { never_synced: 1 }, last_synced_at: null,
        },
      ],
    })),
  } } },
}));

describe('Kyber Connector Health page', () => {
  it('renders aggregate connector health metrics', async () => {
    render(<MemoryRouter><ConnectorsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Connector Health')).toBeInTheDocument());
    expect(screen.getByText('Available connectors')).toBeInTheDocument();
    expect(screen.getByText('Status breakdown')).toBeInTheDocument();
    expect(screen.getByText('Per-connector health')).toBeInTheDocument();
    expect(screen.getByText('Shopify')).toBeInTheDocument();
  });
});
