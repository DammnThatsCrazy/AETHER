import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AuthProvider, useAuth } from '@aether-app/features/auth';
import { ThemeProvider } from '@aether/ui';

// In local-mocked mode (default when VITE_AETHER_ENV is unset), AuthProvider
// auto-dispatches MOCK_LOGIN with the dev user in its useEffect.

function TestConsumer() {
  const { isAuthenticated, user, isLoading } = useAuth();
  return (
    <div>
      <span data-testid="loading">{isLoading ? 'loading' : 'ready'}</span>
      <span data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</span>
      {user && <span data-testid="user-email">{user.email}</span>}
      {user && <span data-testid="user-name">{user.displayName}</span>}
    </div>
  );
}

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <ThemeProvider>
      <AuthProvider>
        {ui}
      </AuthProvider>
    </ThemeProvider>,
  );
}

describe('Auth boot flow (local-mocked)', () => {
  it('auto-authenticates the dev user', async () => {
    renderWithProviders(<TestConsumer />);
    const status = await screen.findByTestId('auth-status');
    expect(status.textContent).toBe('authenticated');
  });

  it('surfaces the mock dev user identity', async () => {
    renderWithProviders(<TestConsumer />);
    const email = await screen.findByTestId('user-email');
    expect(email.textContent).toBe('dev@aether.local');
  });

  it('displays the mock display name', async () => {
    renderWithProviders(<TestConsumer />);
    const name = await screen.findByTestId('user-name');
    expect(name.textContent).toBe('Dev User');
  });

  it('transitions out of loading state', async () => {
    renderWithProviders(<TestConsumer />);
    const loading = await screen.findByTestId('loading');
    expect(loading.textContent).toBe('ready');
  });
});
