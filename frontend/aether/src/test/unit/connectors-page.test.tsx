import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConnectorsPage } from '@aether-app/pages/connectors';

// ConnectorsPage serves /settings/integrations/connectors (rehomed under the
// Settings shell) as well as the legacy /integrations compat path. The route-state
// matrix requires automated successful-empty and unavailable coverage for it.
const connectorsList = vi.hoisted(() => vi.fn(async () => ({ items: [
  { connector_type: 'slack', label: 'Slack', category: 'messaging', description: 'Ingest Slack activity.', premium: false, enabled: false, sync_status: 'never_synced' },
  { connector_type: 'webhook', label: 'Generic Signed Webhook', category: 'webhook', description: 'HMAC webhook.', premium: false, enabled: true, sync_status: 'healthy', secret_configured: true },
  { connector_type: 'hubspot', label: 'HubSpot', category: 'crm', description: 'CRM.', premium: true, enabled: false, sync_status: 'never_synced' },
]})));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { connectors: { list: connectorsList } },
}));

describe('Aether Connectors page', () => {
  beforeEach(() => {
    connectorsList.mockReset();
    connectorsList.mockResolvedValue({ items: [
      { connector_type: 'slack', label: 'Slack', category: 'messaging', description: 'Ingest Slack activity.', premium: false, enabled: false, sync_status: 'never_synced' },
      { connector_type: 'webhook', label: 'Generic Signed Webhook', category: 'webhook', description: 'HMAC webhook.', premium: false, enabled: true, sync_status: 'healthy', secret_configured: true },
      { connector_type: 'hubspot', label: 'HubSpot', category: 'crm', description: 'CRM.', premium: true, enabled: false, sync_status: 'never_synced' },
    ] });
  });

  it('renders connectors grouped by category with status', async () => {
    render(<ConnectorsPage />);
    await waitFor(() => expect(screen.getByText('Integrations & Connectors')).toBeInTheDocument());
    expect(screen.getByText('Slack')).toBeInTheDocument();
    expect(screen.getByText('Generic Signed Webhook')).toBeInTheDocument();
    expect(screen.getByText('HubSpot')).toBeInTheDocument();
    expect(screen.getByText('Connected')).toBeInTheDocument();
    for (const provider of ['slack', 'webhook', 'hubspot']) {
      expect(document.querySelector(`[data-provider="${provider}"][data-provider-mark="fallback"]`)).toBeInTheDocument();
    }
  });

  it('renders the successful-empty state when no connectors are available', async () => {
    connectorsList.mockResolvedValue({ items: [] });
    render(<ConnectorsPage />);
    expect(await screen.findByText('No connectors available')).toBeInTheDocument();
    expect(screen.queryByText('Unable to load connectors')).not.toBeInTheDocument();
  });

  it('renders the unavailable state and never a successful empty when the read fails', async () => {
    connectorsList.mockRejectedValue(new Error('connectors offline'));
    render(<ConnectorsPage />);
    expect(await screen.findByText('Unable to load connectors')).toBeInTheDocument();
    expect(screen.queryByText('No connectors available')).not.toBeInTheDocument();
  });
});
