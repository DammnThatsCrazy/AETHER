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

  it('renders the minimal rail in order and keeps not-ready entries non-links', () => {
    render(
      <MemoryRouter initialEntries={['/explore']}>
        <AppShell><div>WORKSPACE</div></AppShell>
      </MemoryRouter>,
    );

    const navigation = screen.getByRole('navigation');
    expect(within(navigation).getAllByRole('link').map(link => link.textContent)).toEqual([
      'Explore',
      'Sources',
      'Settings',
    ]);
    expect(within(navigation).getByLabelText('Findings (not ready)')).toHaveAttribute('aria-disabled', 'true');
    expect(within(navigation).getByLabelText('Investigations (not ready)')).toHaveAttribute('aria-disabled', 'true');
    expect(within(navigation).getByLabelText('Outcomes (not ready)')).toHaveAttribute('aria-disabled', 'true');
    expect(within(navigation).getByLabelText('Reports (not ready)')).toHaveAttribute('aria-disabled', 'true');
    expect(within(navigation).queryByRole('link', { name: /Findings/ })).not.toBeInTheDocument();
    expect(within(navigation).getByRole('link', { name: 'Sources' })).toHaveAttribute(
      'href',
      '/settings/integrations',
    );
    expect(within(navigation).getByRole('link', { name: 'Settings' })).toHaveAttribute(
      'href',
      '/settings',
    );
    expect(screen.getByText('WORKSPACE')).toBeInTheDocument();
  });

  it('hides the sources link when connectors are not available', () => {
    state.capabilities = {
      release: { excluded_domains: [] },
      feature_flags: { connectors_enabled: false },
    };
    render(
      <MemoryRouter initialEntries={['/explore']}>
        <AppShell><div>WORKSPACE</div></AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByRole('navigation')).not.toHaveTextContent('Sources');
  });
});
