import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ConnectorsPage } from '@aether-app/pages/connectors';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { connectors: {
    list: vi.fn(async () => ({ items: [
      { connector_type: 'slack', label: 'Slack', category: 'messaging', description: 'Ingest Slack activity.', premium: false, enabled: false, sync_status: 'never_synced' },
      { connector_type: 'webhook', label: 'Generic Signed Webhook', category: 'webhook', description: 'HMAC webhook.', premium: false, enabled: true, sync_status: 'healthy' },
      { connector_type: 'hubspot', label: 'HubSpot', category: 'crm', description: 'CRM.', premium: true, enabled: false, sync_status: 'never_synced' },
    ] })),
  } },
}));

describe('Aether Connectors page', () => {
  it('renders connectors grouped by category with status', async () => {
    render(<ConnectorsPage />);
    await waitFor(() => expect(screen.getByText('Integrations & Connectors')).toBeInTheDocument());
    expect(screen.getByText('Slack')).toBeInTheDocument();
    expect(screen.getByText('Generic Signed Webhook')).toBeInTheDocument();
    expect(screen.getByText('HubSpot')).toBeInTheDocument();
    expect(screen.getByText('healthy')).toBeInTheDocument();
  });
});
