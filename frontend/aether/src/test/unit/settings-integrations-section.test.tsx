import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IntegrationsSection } from '@aether-app/pages/settings/integrations-section';
import type { TenantIntegrationItem } from '@aether-app/features/integrations';

const useTenantIntegrations = vi.hoisted(() => vi.fn());

vi.mock('@aether-app/features/integrations', () => ({
  useTenantIntegrations: useTenantIntegrations,
}));

const item = (partial: Partial<TenantIntegrationItem>): TenantIntegrationItem => ({
  id: 'x',
  family: 'x',
  name: null,
  display_name: 'X',
  experience_category: 'advertising_campaigns',
  connected: true,
  enabled: true,
  secret_configured: true,
  sync_status: 'never_synced',
  last_synced_at: null,
  ...partial,
});

function renderSection(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <IntegrationsSection />
    </MemoryRouter>,
  );
}

describe('Settings → Integrations section', () => {
  beforeEach(() => {
    useTenantIntegrations.mockReset();
  });

  it('renders an honest unavailable state when the read model is unreachable', () => {
    useTenantIntegrations.mockReturnValue({
      data: null,
      isLoading: false,
      error: 'not found',
      refetch: vi.fn(),
    });
    renderSection();
    expect(screen.getByText('Integrations unavailable')).toBeInTheDocument();
    expect(screen.getByText(/SDK ingestion is always available/)).toBeInTheDocument();
  });

  it('renders an empty state when no integrations are configured', () => {
    useTenantIntegrations.mockReturnValue({
      data: { tenant_id: 't1', count: 0, items: [] },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderSection();
    expect(screen.getByText('No integrations connected')).toBeInTheDocument();
  });

  it('groups configured integrations by experience category in canonical order', () => {
    useTenantIntegrations.mockReturnValue({
      data: {
        tenant_id: 't1',
        count: 3,
        items: [
          item({ id: 'klaviyo', family: 'klaviyo', display_name: 'Klaviyo', experience_category: 'communications_lifecycle', sync_status: 'healthy', last_synced_at: '2026-09-01T00:00:00Z' }),
          item({ id: 'google_ads', family: 'google_ads', display_name: 'Google Ads', experience_category: 'advertising_campaigns', sync_status: 'syncing' }),
          item({ id: 'shopify', family: 'shopify', display_name: 'Shopify', experience_category: 'commerce_revenue', enabled: false, connected: false, secret_configured: false }),
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderSection();

    // §6 group labels in canonical order.
    const headings = screen.getAllByRole('heading', { level: 2 }).map(h => h.textContent);
    expect(headings).toEqual(['Advertising', 'Commerce & Revenue', 'Communications']);

    expect(screen.getByText('Google Ads')).toBeInTheDocument();
    expect(screen.getByText('Klaviyo')).toBeInTheDocument();
    expect(screen.getByText('Shopify')).toBeInTheDocument();

    // Connection-fact labels: syncing + connected + not-connected; never "Ready".
    expect(screen.getByText('Syncing')).toBeInTheDocument();
    expect(screen.getByText('Connected')).toBeInTheDocument();
    expect(screen.getAllByText('Not connected').length).toBeGreaterThan(0);
    expect(screen.queryByText('Ready')).not.toBeInTheDocument();
    expect(screen.queryByText(/partner live/i)).not.toBeInTheDocument();
  });

  it('surfaces manifest catalog baseline captions without claiming tenant readiness', () => {
    useTenantIntegrations.mockReturnValue({
      data: {
        tenant_id: 't1',
        count: 1,
        items: [
          item({
            id: 'klaviyo',
            family: 'klaviyo',
            display_name: 'Klaviyo',
            experience_category: 'communications_lifecycle',
            readiness: { state: 'credential_waiting', rank: 4, level: 3 },
          }),
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderSection();
    expect(screen.getByText(/Catalog: awaiting provider activation/)).toBeInTheDocument();
    expect(screen.getAllByText('Never synced').length).toBeGreaterThan(0);
  });

  it('links Manage rows to the connector manager route', () => {
    useTenantIntegrations.mockReturnValue({
      data: {
        tenant_id: 't1',
        count: 1,
        items: [item({ id: 'shopify', family: 'shopify', display_name: 'Shopify', experience_category: 'commerce_revenue' })],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderSection();
    const manage = screen.getAllByRole('link', { name: 'Manage' })[0];
    expect(manage).toHaveAttribute('href', '/settings/integrations/connectors');
  });

  it('routes advertising rows into the ad connect flow while other rows stay on the connector manager', () => {
    useTenantIntegrations.mockReturnValue({
      data: {
        tenant_id: 't1',
        count: 2,
        items: [
          item({
            id: 'google_ads',
            family: 'google_ads',
            display_name: 'Google Ads',
            experience_category: 'advertising_campaigns',
            connected: false,
            enabled: false,
            secret_configured: false,
          }),
          item({
            id: 'shopify',
            family: 'shopify',
            display_name: 'Shopify',
            experience_category: 'commerce_revenue',
            connected: false,
            enabled: false,
            secret_configured: false,
          }),
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderSection();

    const adRow = screen.getByText('Google Ads').closest('[data-provider-family="google_ads"]');
    const nonAdRow = screen.getByText('Shopify').closest('[data-provider-family="shopify"]');
    expect(adRow).not.toBeNull();
    expect(nonAdRow).not.toBeNull();

    const adLink = within(adRow as HTMLElement).getByRole('link', { name: 'Connect' });
    expect(adLink).toHaveAttribute(
      'href',
      '/campaign-intelligence/sources?connect=google_ads&return=%2Fsettings%2Fintegrations',
    );

    const nonAdLink = within(nonAdRow as HTMLElement).getByRole('link', { name: 'Manage' });
    expect(nonAdLink).toHaveAttribute('href', '/settings/integrations/connectors');
  });

  it('labels an already-connected advertising row Manage and keeps it in the ad flow', () => {
    useTenantIntegrations.mockReturnValue({
      data: {
        tenant_id: 't1',
        count: 1,
        items: [
          item({
            id: 'google_ads',
            family: 'google_ads',
            display_name: 'Google Ads',
            experience_category: 'advertising_campaigns',
          }),
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderSection();

    const adRow = screen.getByText('Google Ads').closest('[data-provider-family="google_ads"]');
    expect(adRow).not.toBeNull();
    const adLink = within(adRow as HTMLElement).getByRole('link', { name: 'Manage' });
    expect(adLink).toHaveAttribute(
      'href',
      '/campaign-intelligence/sources?connect=google_ads&return=%2Fsettings%2Fintegrations',
    );
  });

  it('forwards a validated incoming return target through the ad connect deep link (reconciled bridge)', () => {
    useTenantIntegrations.mockReturnValue({
      data: {
        tenant_id: 't1',
        count: 1,
        items: [
          item({
            id: 'google_ads',
            family: 'google_ads',
            display_name: 'Google Ads',
            experience_category: 'advertising_campaigns',
            connected: false,
            enabled: false,
            secret_configured: false,
          }),
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    // The tenant reached Settings from the Campaign Sources empty state, which
    // deep-links back here with ?return=<the sources list>. The ad connect deep
    // link forwards that target so the round trip completes where it started.
    renderSection('/settings/integrations?return=/campaign-intelligence/sources');
    const adRow = screen.getByText('Google Ads').closest('[data-provider-family="google_ads"]');
    expect(adRow).not.toBeNull();
    const adLink = within(adRow as HTMLElement).getByRole('link', { name: 'Connect' });
    expect(adLink).toHaveAttribute(
      'href',
      '/campaign-intelligence/sources?connect=google_ads&return=%2Fcampaign-intelligence%2Fsources',
    );
  });

  it('never forwards an off-origin return target — falls back to the Settings default', () => {
    useTenantIntegrations.mockReturnValue({
      data: {
        tenant_id: 't1',
        count: 1,
        items: [
          item({
            id: 'google_ads',
            family: 'google_ads',
            display_name: 'Google Ads',
            experience_category: 'advertising_campaigns',
            connected: false,
            enabled: false,
            secret_configured: false,
          }),
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderSection('/settings/integrations?return=https%3A%2F%2Fevil.example%2Fphish');
    const adRow = screen.getByText('Google Ads').closest('[data-provider-family="google_ads"]');
    expect(adRow).not.toBeNull();
    const adLink = within(adRow as HTMLElement).getByRole('link', { name: 'Connect' });
    expect(adLink).toHaveAttribute(
      'href',
      '/campaign-intelligence/sources?connect=google_ads&return=%2Fsettings%2Fintegrations',
    );
  });
});
