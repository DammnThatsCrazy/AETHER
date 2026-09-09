import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  auth: vi.fn(),
  profile: vi.fn(),
  profileQuery: { data: null as unknown, isLoading: false, error: null as string | null },
  observed: vi.fn(),
  explorationClient: {},
}));

vi.mock('@aether-app/features/auth', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
  useAuth: mocks.auth,
}));
vi.mock('@aether-app/lib/auth/auth0-provider', () => ({ AetherAuth0Provider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@aether-app/features/journey', () => ({ JourneyProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@aether-app/lib/api/endpoints', () => ({ api: { me: { profile: mocks.profile } } }));
vi.mock('@aether-app/lib/api/capabilities', () => ({ fetchTenantCapabilities: vi.fn() }));
vi.mock('@aether-app/lib/api/exploration', () => ({ explorationClient: mocks.explorationClient }));
vi.mock('@aether-app/lib/build-info', () => ({ BUILD_INFO: {} }));
vi.mock('@aether/ui', () => ({
  CapabilityProvider: ({ children }: { children: React.ReactNode }) => children,
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
  TimeProvider: ({ children }: { children: React.ReactNode }) => children,
  ToastProvider: ({ children }: { children: React.ReactNode }) => children,
  LoadingState: () => <div data-testid="loading-state">Loading graph context</div>,
  ErrorState: ({ title, message }: { title?: string; message?: string }) => (
    <div data-testid="error-state">{title}: {message}</div>
  ),
  useQuery: ({ enabled, fetcher }: { enabled?: boolean; fetcher: () => unknown }) => {
    if (enabled) void fetcher();
    return enabled
      ? mocks.profileQuery
      : { data: null, isLoading: false, error: null };
  },
}));
vi.mock('@aether/ui/exploration', () => ({
  GraphContextProvider: (props: {
    scope: {
      tenant_id: string;
      workspace_id: string;
      environment_id: string;
      scope_model: string;
    };
    surface: string;
    query?: string;
    client?: unknown;
    children: React.ReactNode;
  }) => {
    mocks.observed(props);
    return props.children;
  },
}));

import { ExplorationGate } from './providers';

describe('Aether ExplorationGate', () => {
  beforeEach(() => {
    mocks.observed.mockClear();
    mocks.profile.mockClear();
    mocks.profileQuery = { data: null, isLoading: false, error: null };
  });

  it('mounts graph context from the returned profile scope and preserves URL surface/query state', () => {
    mocks.auth.mockReturnValue({ isAuthenticated: true, user: { id: 'auth-user-not-authority' } });
    mocks.profileQuery = {
      data: {
        tenant_id: 'tenant-from-profile',
        graph_scope: {
          tenant_id: 'tenant-from-profile',
          workspace_id: 'tenant-from-profile',
          environment_id: 'production',
          scope_model: 'single_workspace_tenant_v1',
        },
      },
      isLoading: false,
      error: null,
    };
    render(
      <MemoryRouter initialEntries={['/graph?tenant_id=spoofed&workspace_id=spoofed&environment_id=staging&surface=graph&tmode=as_of&tas=2026-01-01T00%3A00%3A00Z']}>
        <ExplorationGate><span>mounted</span></ExplorationGate>
      </MemoryRouter>,
    );

    expect(screen.getByText('mounted')).toBeInTheDocument();
    expect(mocks.profile).toHaveBeenCalledOnce();
    expect(mocks.observed).toHaveBeenCalledWith(expect.objectContaining({
      scope: {
        tenant_id: 'tenant-from-profile',
        workspace_id: 'tenant-from-profile',
        environment_id: 'production',
        scope_model: 'single_workspace_tenant_v1',
      },
      surface: '/graph',
      query: '?tenant_id=spoofed&workspace_id=spoofed&environment_id=staging&surface=graph&tmode=as_of&tas=2026-01-01T00%3A00%3A00Z',
      client: mocks.explorationClient,
    }));
  });

  it('fails closed while the authenticated profile is loading or unavailable', () => {
    mocks.auth.mockReturnValue({ isAuthenticated: true, user: { id: 'tenant-7' } });
    mocks.profileQuery = { data: null, isLoading: true, error: null };
    const { rerender } = render(<MemoryRouter><ExplorationGate><span>graph-child</span></ExplorationGate></MemoryRouter>);
    expect(screen.getByTestId('loading-state')).toBeInTheDocument();
    expect(screen.queryByText('graph-child')).not.toBeInTheDocument();
    expect(mocks.observed).not.toHaveBeenCalled();

    mocks.profileQuery = { data: null, isLoading: false, error: 'profile unavailable' };
    rerender(<MemoryRouter><ExplorationGate><span>graph-child</span></ExplorationGate></MemoryRouter>);
    expect(screen.getByTestId('error-state')).toHaveTextContent('Graph context unavailable');
    expect(screen.queryByText('graph-child')).not.toBeInTheDocument();
    expect(mocks.observed).not.toHaveBeenCalled();
  });

  it('does not create exploration state before authentication', () => {
    mocks.auth.mockReturnValue({ isAuthenticated: false, user: null });
    render(<MemoryRouter><ExplorationGate><span>login</span></ExplorationGate></MemoryRouter>);
    expect(screen.getByText('login')).toBeInTheDocument();
    expect(mocks.observed).not.toHaveBeenCalled();
  });
});
