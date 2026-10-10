/**
 * Auth boot flow against the cookie-session backend.
 */

import type { ReactElement } from 'react';
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AuthProvider, useAuth } from '@kyber/features/auth';
import { ThemeProvider } from '@aether/ui';
import { NotificationProvider } from '@kyber/features/notifications';
import { makePrincipal, stubAuthRoutes } from '@kyber/test/kyber-auth-doubles';

function TestConsumer() {
  const { isAuthenticated, principal, status } = useAuth();
  return (
    <div>
      <span data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</span>
      <span data-testid="raw-status">{status}</span>
      {principal && <span data-testid="user-roles">{principal.role_template_ids.join(',')}</span>}
      {principal && <span data-testid="user-name">{principal.display_name}</span>}
    </div>
  );
}

function renderWithProviders(ui: ReactElement) {
  return render(
    <ThemeProvider>
      <AuthProvider pollIntervalMs={0}>
        <NotificationProvider>{ui}</NotificationProvider>
      </AuthProvider>
    </ThemeProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('Auth boot flow', () => {
  it('does not auto-authenticate when the backend has no session', async () => {
    stubAuthRoutes({ meStatus: 401 });
    renderWithProviders(<TestConsumer />);
    await waitFor(() =>
      expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated'),
    );
  });

  it('adopts the backend principal when a session cookie is present', async () => {
    stubAuthRoutes({ principal: makePrincipal({ display_name: 'Ada' }) });
    renderWithProviders(<TestConsumer />);
    await waitFor(() =>
      expect(screen.getByTestId('auth-status')).toHaveTextContent('authenticated'),
    );
    expect(screen.getByTestId('user-name')).toHaveTextContent('Ada');
    expect(screen.getByTestId('user-roles')).toHaveTextContent('kyber.role.support');
  });

  it('fails closed when the control plane is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('network down');
      }),
    );
    renderWithProviders(<TestConsumer />);
    await waitFor(() => expect(screen.getByTestId('raw-status')).toHaveTextContent('error'));
    expect(screen.getByTestId('auth-status')).toHaveTextContent('unauthenticated');
  });
});
