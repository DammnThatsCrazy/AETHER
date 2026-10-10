import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { AppRouter } from '@aether-app/app/router';

const runtime = vi.hoisted(() => ({
  featureFlags: {
    tenant_identity_activation_dashboard_enabled: true,
    identity_manual_review_enabled: true,
  } as Record<string, boolean>,
}));

vi.mock('@aether-app/features/auth', () => ({
  RequireAuth: ({ children }: { children: React.ReactNode }) => children,
  SESSION_KEY: 'aether-session',
  useAuth: () => ({ user: { id: 'tenant-a', email: 'operator@example.test' }, logout: vi.fn() }),
}));

vi.mock('@aether/ui', async () => {
  const actual = await vi.importActual<typeof import('@aether/ui')>('@aether/ui');
  return {
    ...actual,
    useCapabilities: () => ({ capabilities: { release: { excluded_domains: [] }, feature_flags: runtime.featureFlags }, loading: false, error: null, refresh: vi.fn() }),
    useBuildInfo: () => null,
    useTheme: () => ({ theme: 'dark', setTheme: vi.fn() }),
  };
});

vi.mock('@aether-app/features/demo-seed/use-demo-seed-status', () => ({
  useDemoSeedStatus: () => ({ data: null }),
}));

vi.mock('@aether-app/lib/featureFlags', () => ({
  isFeatureEnabled: (flag: string) => runtime.featureFlags[flag] === true,
}));

vi.mock('@aether-app/features/identity/TenantActivationDashboard', () => ({
  TenantActivationDashboard: () => <div>Tenant activation route content</div>,
}));

vi.mock('@aether-app/features/identity/IdentityReviewQueue', () => ({
  IdentityReviewQueue: () => <div>Identity review route content</div>,
}));

describe('authenticated identity continuity routes', () => {
  beforeEach(() => {
    sessionStorage.setItem('aether-session', 'present');
    runtime.featureFlags = {
      tenant_identity_activation_dashboard_enabled: true,
      identity_manual_review_enabled: true,
    };
  });

  it.each([
    ['/identity/activation', 'Tenant activation route content'],
    ['/identity/reviews', 'Identity review route content'],
  ])('mounts %s inside the tenant app route tree', async (path, content) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <AppRouter />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText(content)).toBeInTheDocument());
    const navigation = within(screen.getByRole('navigation'));
    expect(navigation.getByRole('link', { name: 'Identity status' })).toBeInTheDocument();
    expect(navigation.getByRole('link', { name: 'Identity reviews' })).toBeInTheDocument();
  });
});
