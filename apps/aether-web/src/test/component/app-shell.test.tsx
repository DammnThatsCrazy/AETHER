import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { AppShell } from '@aether-app/components/app-shell';

const state = vi.hoisted(() => ({
  capabilities: null as { release: { excluded_domains: string[] }; feature_flags: Record<string, boolean> } | null,
  integrations: null as { items: Array<Record<string, unknown>> } | null,
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

vi.mock('@aether-app/features/integrations', () => ({
  useTenantIntegrations: () => ({ data: state.integrations, isLoading: false, error: null, refetch: vi.fn() }),
}));

describe('Aether authenticated shell', () => {
  beforeEach(() => {
    state.capabilities = {
      release: { excluded_domains: [] },
      feature_flags: { connectors_enabled: true },
    };
    state.integrations = null;
    sessionStorage.setItem('aether-session', 'present');
    window.innerWidth = 1280;
  });

  it('maps every design destination to its route, in the design order', () => {
    render(
      <MemoryRouter initialEntries={['/explore']}>
        <AppShell><div>WORKSPACE</div></AppShell>
      </MemoryRouter>,
    );

    const navigation = screen.getByRole('navigation');
    const hrefs: Record<string, string> = {
      Home: '/home',
      Graph: '/explore',
      Profiles: '/users',
      Agents: '/agent-access',
      Syndicates: '/syndicates',
      Relationships: '/relationships',
      Campaigns: '/campaigns',
      Communications: '/communications',
      Journeys: '/journeys',
      Episodes: '/episodes',
      Geography: '/geo',
      Signals: '/signals',
      Value: '/value-review',
      Risk: '/risk',
      Connectors: '/settings/integrations',
      Settings: '/settings',
    };
    expect(within(navigation).getAllByRole('link').map(link => link.getAttribute('aria-label'))).toEqual(Object.keys(hrefs));
    for (const [name, href] of Object.entries(hrefs)) {
      expect(within(navigation).getByRole('link', { name })).toHaveAttribute('href', href);
    }
    expect(within(navigation).queryByText(/not ready/)).not.toBeInTheDocument();
    expect(within(navigation).getByRole('link', { name: 'Graph' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('WORKSPACE')).toBeInTheDocument();
  });

  it('flags Settings with an amber dot only when a configured connection is failing', () => {
    state.integrations = { items: [{ id: 'i1', enabled: true, sync_status: 'sync_failed' }] };
    const { container } = render(
      <MemoryRouter initialEntries={['/home']}>
        <AppShell><div>WORKSPACE</div></AppShell>
      </MemoryRouter>,
    );
    const settings = within(container).getByRole('link', { name: 'Settings' });
    expect(settings.querySelector('span[style*="--ae-amber"]')).not.toBeNull();
  });

  it('collapses to an icon rail and remembers the choice', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    render(
      <MemoryRouter initialEntries={['/home']}>
        <AppShell><div>WORKSPACE</div></AppShell>
      </MemoryRouter>,
    );
    expect(screen.getByText('Home')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }));
    expect(screen.queryByText('Home')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/home');
    expect(window.localStorage.getItem('aether:rail-expanded')).toBe('0');
    window.localStorage.removeItem('aether:rail-expanded');
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
