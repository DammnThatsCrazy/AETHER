import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { AppShell } from '@aether-app/components/app-shell';

const state = vi.hoisted(() => ({
  capabilities: null as { release: { excluded_domains: string[] }; feature_flags: Record<string, boolean> } | null,
}));

vi.mock('@aether/ui', async () => {
  const actual = await vi.importActual<typeof import('@aether/ui')>('@aether/ui');
  return {
    ...actual,
    useCapabilities: () => ({ capabilities: state.capabilities, loading: false, error: null, refresh: vi.fn() }),
    useBuildInfo: () => null,
    useTheme: () => ({ theme: 'dark', setTheme: vi.fn() }),
  };
});

vi.mock('@aether-app/features/auth', () => ({
  SESSION_KEY: 'aether-session',
  useAuth: () => ({ user: { email: 'acme@example.com' }, logout: vi.fn() }),
}));

vi.mock('@aether-app/features/demo-seed/use-demo-seed-status', () => ({
  useDemoSeedStatus: () => ({ data: null }),
}));

describe('Aether authenticated shell', () => {
  beforeEach(() => {
    state.capabilities = {
      release: { excluded_domains: [] },
      feature_flags: { connectors_enabled: true },
    };
    sessionStorage.setItem('aether-session', 'present');
  });

  it('maps the available target destinations to existing routes and keeps unbuilt destinations non-links', () => {
    render(
      <MemoryRouter initialEntries={['/explore']}>
        <AppShell><div>WORKSPACE</div></AppShell>
      </MemoryRouter>,
    );

    const navigation = screen.getByRole('navigation');
    expect(within(navigation).getAllByRole('link').map(link => link.textContent)).toEqual([
      'Graph',
      'Profiles',
      'Connectors',
      'Settings',
    ]);
    for (const label of ['Snapshot', 'Journeys', 'Signals', 'Lenses', 'Value']) {
      expect(within(navigation).getByLabelText(`${label} (not ready)`)).toHaveAttribute('aria-disabled', 'true');
      expect(within(navigation).queryByRole('link', { name: label })).not.toBeInTheDocument();
    }
    expect(within(navigation).getByRole('link', { name: 'Graph' })).toHaveAttribute('href', '/explore');
    expect(within(navigation).getByRole('link', { name: 'Profiles' })).toHaveAttribute('href', '/users');
    expect(within(navigation).getByRole('link', { name: 'Connectors' })).toHaveAttribute(
      'href',
      '/settings/integrations',
    );
    expect(within(navigation).getByRole('link', { name: 'Settings' })).toHaveAttribute(
      'href',
      '/settings',
    );
    expect(screen.getByText('WORKSPACE')).toBeInTheDocument();
  });

  it('hides Connectors when its backend capability is disabled, while keeping available routes', () => {
    state.capabilities = {
      release: { excluded_domains: [] },
      feature_flags: { connectors_enabled: false },
    };
    render(
      <MemoryRouter initialEntries={['/explore']}>
        <AppShell><div>WORKSPACE</div></AppShell>
      </MemoryRouter>,
    );

    const navigation = screen.getByRole('navigation');
    expect(within(navigation).queryByRole('link', { name: 'Connectors' })).not.toBeInTheDocument();
    expect(within(navigation).getByRole('link', { name: 'Graph' })).toHaveAttribute('href', '/explore');
    expect(within(navigation).getByRole('link', { name: 'Profiles' })).toHaveAttribute('href', '/users');
    expect(within(navigation).getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings');
    expect(screen.getByText('WORKSPACE')).toBeInTheDocument();
  });

  it('selects Connectors, not Settings, for the existing integrations route', () => {
    render(<MemoryRouter initialEntries={['/settings/integrations?family=example']}><AppShell><div>WORKSPACE</div></AppShell></MemoryRouter>);

    const navigation = screen.getByRole('navigation');
    expect(within(navigation).getByRole('link', { name: 'Connectors' })).toHaveAttribute('aria-current', 'page');
    expect(within(navigation).getByRole('link', { name: 'Settings' })).not.toHaveAttribute('aria-current');
  });

  it('fails closed on gated links until capabilities are available', () => {
    state.capabilities = null;
    render(<MemoryRouter initialEntries={['/settings/integrations?family=example']}><AppShell><div>WORKSPACE</div></AppShell></MemoryRouter>);

    const navigation = screen.getByRole('navigation');
    expect(within(navigation).queryByRole('link', { name: 'Connectors' })).not.toBeInTheDocument();
    expect(within(navigation).queryByRole('link', { name: 'Identity status' })).not.toBeInTheDocument();
    expect(within(navigation).queryByRole('link', { name: 'Identity reviews' })).not.toBeInTheDocument();
    expect(within(navigation).getByRole('link', { name: 'Graph' })).toHaveAttribute('href', '/explore');
    expect(screen.getByText('WORKSPACE')).toBeInTheDocument();
  });

  it('adds identity activation and review entry points only for enabled tenant features', () => {
    state.capabilities = {
      release: { excluded_domains: [] },
      feature_flags: {
      tenant_identity_activation_dashboard_enabled: true,
      identity_manual_review_enabled: true,
      },
    };
    render(
      <MemoryRouter initialEntries={['/identity/activation']}>
        <AppShell><div>WORKSPACE</div></AppShell>
      </MemoryRouter>,
    );

    const navigation = screen.getByRole('navigation');
    expect(within(navigation).getByRole('link', { name: 'Identity status' })).toHaveAttribute('href', '/identity/activation');
    expect(within(navigation).getByRole('link', { name: 'Identity reviews' })).toHaveAttribute('href', '/identity/reviews');
  });

  it('hides identity entry points when backend capabilities are off', () => {
    state.capabilities = {
      release: { excluded_domains: [] },
      feature_flags: {
        tenant_identity_activation_dashboard_enabled: false,
        identity_manual_review_enabled: false,
      },
    };
    render(<MemoryRouter initialEntries={['/explore']}><AppShell><div>WORKSPACE</div></AppShell></MemoryRouter>);
    expect(screen.queryByRole('link', { name: 'Identity status' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Identity reviews' })).not.toBeInTheDocument();
  });
});
