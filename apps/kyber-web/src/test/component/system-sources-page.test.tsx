import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { api } from '@kyber/lib/api';
import { SystemSourcesPage } from '@kyber/pages/system-sources';

vi.mock('@kyber/components/layout', () => ({
  PageWrapper: ({ title, children }: { title: string; children: React.ReactNode }) => <div><h1>{title}</h1>{children}</div>,
}));

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: { providerConnections: { systemSources: vi.fn() } } } },
}));

function renderPage() {
  return render(<ThemeProvider><MemoryRouter><SystemSourcesPage /></MemoryRouter></ThemeProvider>);
}

describe('SystemSourcesPage', () => {
  it('shows Olympus sources in full and tenant sources by provider only', async () => {
    vi.mocked(api.admin.kyber.providerConnections.systemSources).mockResolvedValue({
      olympus: {
        connections: [{ connection_id: 'c1', provider_identity: 'dune.analytics.query', display_name: 'Dune (Olympus)', state: 'connected', credential_stored: true, account_count: 1, updated_at: null }],
        grants: [{ grant_id: 'g1', source_id: 'provider-account:c1:acct', connector_id: 'dune.analytics.query', connector_class: 'olympus_provider', olympus_baseline_allowed: true, model_training_allowed: false, commercial_reuse_allowed: false, granted_at: '2026-11-21T00:00:00Z' }],
      },
      tenants: { providers: { 'shopify.admin.orders_read': { connections: { connected: 3 }, grants: { organization_system: 3 } } }, tenant_count: 2, connection_count: 3 },
      truncated: false,
    });
    renderPage();
    expect(await screen.findByText('Dune (Olympus)')).toBeTruthy();
    expect(screen.getByText('stored')).toBeTruthy();
    expect(screen.getByText('baseline yes')).toBeTruthy();
    expect(screen.getByText('shopify.admin.orders_read')).toBeTruthy();
    expect(screen.getByText('Organization system 3')).toBeTruthy();
  });

  it('says plainly when there are no Olympus sources', async () => {
    vi.mocked(api.admin.kyber.providerConnections.systemSources).mockResolvedValue({
      olympus: { connections: [], grants: [] },
      tenants: { providers: {}, tenant_count: 0, connection_count: 0 },
      truncated: false,
    });
    renderPage();
    expect(await screen.findByText('No Olympus sources yet')).toBeTruthy();
  });
});
