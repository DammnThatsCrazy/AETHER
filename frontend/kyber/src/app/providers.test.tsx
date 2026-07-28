import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  auth: vi.fn(),
  observed: vi.fn(),
}));

vi.mock('@kyber/features/auth', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
  useAuth: mocks.auth,
}));
vi.mock('@kyber/features/notifications', () => ({ NotificationProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@kyber/features/journey', () => ({ JourneyProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@kyber/lib/api/capabilities', () => ({ fetchOperatorCapabilities: vi.fn() }));
vi.mock('@kyber/lib/build-info', () => ({ BUILD_INFO: {} }));
vi.mock('@aether/ui', () => ({
  CapabilityProvider: ({ children }: { children: React.ReactNode }) => children,
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
  TimeProvider: ({ children }: { children: React.ReactNode }) => children,
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

const principal = {
  operator_id: 'operator-1',
  session_id: 'session-1',
  active_scope: null,
};

describe('Kyber ExplorationGate', () => {
  beforeEach(() => mocks.observed.mockClear());

  it('isolates fleet exploration to the backend operator session', () => {
    mocks.auth.mockReturnValue({ isAuthenticated: true, principal });
    render(
      <MemoryRouter initialEntries={['/mission?surface=mission&tmode=window']}>
        <ExplorationGate><span>fleet</span></ExplorationGate>
      </MemoryRouter>,
    );
    expect(screen.getByText('fleet')).toBeInTheDocument();
    expect(mocks.observed).toHaveBeenCalledWith(expect.objectContaining({
      tenantId: 'operator:operator-1:session-1',
      surface: '/mission',
      query: '?surface=mission&tmode=window',
    }));
  });

  it('uses only an active backend tenant scope as tenant authority', () => {
    mocks.auth.mockReturnValue({
      isAuthenticated: true,
      principal: {
        ...principal,
        active_scope: { scope_id: 'scope-9', tenant_id: 'tenant-9', status: 'active' },
      },
    });
    render(<MemoryRouter initialEntries={['/tenant-mirror']}><ExplorationGate><span>tenant</span></ExplorationGate></MemoryRouter>);
    expect(mocks.observed).toHaveBeenCalledWith(expect.objectContaining({ tenantId: 'tenant-9' }));
  });

  it('does not create exploration state before workforce authentication', () => {
    mocks.auth.mockReturnValue({ isAuthenticated: false, principal: null });
    render(<MemoryRouter><ExplorationGate><span>login</span></ExplorationGate></MemoryRouter>);
    expect(screen.getByText('login')).toBeInTheDocument();
    expect(mocks.observed).not.toHaveBeenCalled();
  });
});
