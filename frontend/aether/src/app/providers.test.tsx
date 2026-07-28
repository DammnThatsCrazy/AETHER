import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  auth: vi.fn(),
  observed: vi.fn(),
}));

vi.mock('@aether-app/features/auth', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
  useAuth: mocks.auth,
}));
vi.mock('@aether-app/lib/auth/auth0-provider', () => ({ AetherAuth0Provider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@aether-app/features/journey', () => ({ JourneyProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@aether-app/lib/api/capabilities', () => ({ fetchTenantCapabilities: vi.fn() }));
vi.mock('@aether-app/lib/build-info', () => ({ BUILD_INFO: {} }));
vi.mock('@aether/ui', () => ({
  CapabilityProvider: ({ children }: { children: React.ReactNode }) => children,
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
  TimeProvider: ({ children }: { children: React.ReactNode }) => children,
  ToastProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('@aether/ui/exploration', () => ({
  ExplorationProvider: (props: {
    tenantId: string;
    surface: string;
    query?: string;
    children: React.ReactNode;
  }) => {
    mocks.observed(props);
    return props.children;
  },
}));

import { ExplorationGate } from './providers';

describe('Aether ExplorationGate', () => {
  beforeEach(() => mocks.observed.mockClear());

  it('mounts canonical exploration from backend identity and the complete URL', () => {
    mocks.auth.mockReturnValue({ isAuthenticated: true, user: { id: 'tenant-7' } });
    render(
      <MemoryRouter initialEntries={['/graph?surface=graph&tmode=as_of&tas=2026-01-01T00%3A00%3A00Z']}>
        <ExplorationGate><span>mounted</span></ExplorationGate>
      </MemoryRouter>,
    );

    expect(screen.getByText('mounted')).toBeInTheDocument();
    expect(mocks.observed).toHaveBeenCalledWith(expect.objectContaining({
      tenantId: 'tenant-7',
      surface: '/graph',
      query: '?surface=graph&tmode=as_of&tas=2026-01-01T00%3A00%3A00Z',
    }));
  });

  it('does not create exploration state before authentication', () => {
    mocks.auth.mockReturnValue({ isAuthenticated: false, user: null });
    render(<MemoryRouter><ExplorationGate><span>login</span></ExplorationGate></MemoryRouter>);
    expect(screen.getByText('login')).toBeInTheDocument();
    expect(mocks.observed).not.toHaveBeenCalled();
  });
});
